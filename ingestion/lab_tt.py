"""Parse the EVEN lab timetable, one table per lab room (ROADMAP S7).

Pure parsing: reads ``data/real/Lab CE_Time_Table-Even_sem_25-26.docx`` through
:mod:`ingestion.docx_reader` and returns plain dataclasses. Nothing is written to
the database.

The paragraphs before each table name its room ("ROOM NO: 607-B") and print its
utilisation ("Lab Utilization in %= 24/30= 80.00 %"). One :class:`LabEntry` per
non-empty, non-break grid cell, with every decision recorded on it:

- **room**: labels are normalised per D27 and D30 ("607-B" = 607B, "509 new
  CSE" = 509, "703-A" = sub-room A of 703). A sub-room label beyond the lab's
  declared split (603-7, 606-4, 606-5) is reported and mapped to the parent lab
  (D30). A bracketed room inside a cell ("(601)") is recorded and reported; the
  table's room is kept, since its utilisation line counts the cell and the class
  timetable agrees with it. Rooms outside D8/D10 are reported and not
  used for generation (D28 for 505, D29 for the rest).
- **cell**: ``SUBJECT / BATCH / INITIALS`` then an audience line ("SE COMP B",
  or "TE COMP" for a cross-division elective). Subjects match scheme codes only
  through :data:`ingestion.class_tt.SUBJECT_ALIASES`.
- **faculty**: initials resolve through the audience division's own legend, as
  in class_tt (no borrowing); "SRD" resolves per D25. An elective cell names no
  division, so it takes the resolution of the matching class-timetable line.
- **utilisation**: occupied (day, period) slots of the table, coffee break
  excluded, over the printed denominator, compared with the printed figure.

:func:`room_inventory` is the D8 + D10 room set used for generation, and
:func:`cross_check` compares every in-scope practical with the class timetable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from lxml.etree import _Element

from ingestion.class_tt import (
    _BATCH,
    _ELECTIVE_GROUP,
    COFFEE_PERIOD,
    DAYS,
    SUBJECT_ALIASES,
    ClassTimetable,
    Entry,
    FacultyIndex,
    _span,
    faculty_index,
    parse_class_timetable,
    subject_key,
    time_rows,
)
from ingestion.docx_reader import logical_cells, open_document, paragraph_text, walk_body
from ingestion.initials_legend import name_key, normalise_whitespace
from ingestion.seed_legends import LegendScope
from ingestion.seed_reference import SeedBlocked, parse_classrooms
from ingestion.survey import REAL_DIR

LAB_FILE = REAL_DIR / "Lab CE_Time_Table-Even_sem_25-26.docx"
LAB_CAPACITIES_YAML = REAL_DIR / "lab_capacities.yaml"

NEEDS_HUMAN = "needs human"


@dataclass(frozen=True)
class Finding:
    """One anomaly: what kind, where, what was seen, and what resolves it.

    ``resolution`` is the ROADMAP decision id that settles it ("D30"), or
    :data:`NEEDS_HUMAN`.
    """

    category: str
    location: str
    message: str
    resolution: str


# --------------------------------------------------------------------------- #
# Faculty resolution (division-scoped, plus D25)
# --------------------------------------------------------------------------- #

#: D25: "SRD" is in no legend; ROADMAP D25 names the person.
D25_INITIALS = "SRD"
D25_NAME = "Dr. Dholay Surekha Rajesh"

_DIV_KEY = re.compile(r"\b(SE|TE)\W*COMP\W*([A-D])\b", re.IGNORECASE)
#: The form division_key returns.
_KEY = re.compile(r"(SE|TE)-[A-D]")


def division_key(label: str) -> str | None:
    """'SE-Comp A', 'TE Comp - C', 'SE COMP B', 'SECOMP C' -> 'SE-A' / 'TE-C' / ..."""
    match = _DIV_KEY.search(label)
    return f"{match[1].upper()}-{match[2].upper()}" if match else None


def d25_member(faculty: FacultyIndex) -> str:
    """The 41-list member D25 names: every word of their name is in D25's name."""
    words = set(name_key(D25_NAME).split())
    found = [n for n in faculty.ce_faculty if set(name_key(n).split()) <= words]
    if len(found) != 1:
        raise SeedBlocked(f"D25 name {D25_NAME!r} matches {found} in the faculty list, not one")
    return found[0]


def legend_scopes(faculty: FacultyIndex) -> dict[str, LegendScope]:
    """EVEN legend scope per audience key: 'SE-A'..'TE-D', 'BE', 'M.Tech'."""
    scopes: dict[str, LegendScope] = {}
    for scope in faculty.by_scope:
        if scope.term.value != "EVEN":
            continue
        key = division_key(scope.division)
        if key is None and scope.programme == "M.Tech":
            key = "M.Tech"
        elif key is None and scope.semester_number == 8:
            key = "BE"
        if key:
            scopes[key] = scope
    return scopes


def resolve(
    initials: str | None,
    audience: str | None,
    faculty: FacultyIndex,
    scopes: dict[str, LegendScope],
) -> tuple[str, list[str]]:
    """``(status, candidates)`` for initials seen with an audience key.

    status: resolved | ambiguous | resolved_d25 | not_in_division_legend |
    no_division | missing.
    """
    if initials is None:
        return "missing", []
    scope = scopes.get(audience) if audience else None
    candidates = faculty.by_scope.get(scope, {}).get(initials) if scope else None
    if candidates:
        return ("resolved" if len(candidates) == 1 else "ambiguous"), list(candidates)
    if initials == D25_INITIALS:
        return "resolved_d25", [d25_member(faculty)]
    return ("not_in_division_legend" if scope else "no_division"), []


def class_resolution(e: Entry, faculty: FacultyIndex) -> tuple[str | None, list[str]]:
    """A class-timetable entry's faculty resolution, with D25 applied to "SRD"."""
    if e.faculty_status == "not_in_division_legend" and e.faculty_initials_raw == D25_INITIALS:
        return "resolved_d25", [d25_member(faculty)]
    return e.faculty_status, list(e.faculty_candidates)


def attributed(status: str | None, candidates: list[str]) -> str | None:
    """The one faculty member a resolution names, or ``None``."""
    return candidates[0] if status in ("resolved", "resolved_d25") else None


# --------------------------------------------------------------------------- #
# Rooms (D8, D10, D27-D30)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InventoryRoom:
    """A room usable for generation: a D8 lab or a D10 classroom."""

    code: str
    capacity: int
    room_type: str  # class | lab | unknown
    used_as: str  # verbatim classrooms.xlsx
    separation: str | None
    #: Batch places in parallel (D8); 1 for a classroom.
    parallel: int
    #: (code, capacity), e.g. ("603-2", 20).
    sub_rooms: tuple[tuple[str, int], ...]


@dataclass
class Inventory:
    rooms: dict[str, InventoryRoom]
    #: classrooms.xlsx codes, all rows (the D10 exclusions are reported from it).
    xlsx_codes: frozenset[str]
    findings: list[Finding]

    def classrooms(self) -> list[InventoryRoom]:
        return [r for r in self.rooms.values() if r.room_type != "lab"]

    def labs(self) -> list[InventoryRoom]:
        return [r for r in self.rooms.values() if r.room_type == "lab"]


_LAB_USES = ("lab", "as a lab", "Mtech lab")
#: classrooms.xlsx 'used as' -> contract room_type (decision log 2026-09-25).
_ROOM_TYPE = {
    "class": "class", "lab": "lab", "as a lab": "lab", "Mtech lab": "lab", "unsure": "unknown",
}
#: D10: the 6th and 7th floors belong to CE.
_CE_FLOORS = ("6", "7")


def load_lab_capacities(path: Path = LAB_CAPACITIES_YAML) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def room_inventory() -> Inventory:
    caps = load_lab_capacities()
    batch = caps["batch_size_students"]
    xlsx = parse_classrooms()
    rows: dict[str, list] = {}
    for r in xlsx:
        rows.setdefault(r.code, []).append(r)
    findings: list[Finding] = []
    rooms: dict[str, InventoryRoom] = {}

    for code, found in rows.items():
        if len(found) > 1:
            uses = ", ".join(f"capacity {r.capacity} '{r.used_as}'" for r in found)
            findings.append(Finding(
                "duplicate_room", f"classrooms.xlsx {code}",
                f"room {code} appears {len(found)} times ({uses}); the lab row is used, "
                "as D8 lists it as a lab", "D8",
            ))

    lab_codes = {lab["room"] for lab in caps["labs"]}
    for lab in caps["labs"]:
        code = lab["room"]
        if not lab["btech_use"]:
            findings.append(Finding(
                "lab_excluded", f"lab_capacities.yaml {code}",
                f"lab {code} is not for B.Tech ({lab.get('note', 'btech_use false')})", "D8",
            ))
            continue
        candidates = [r for r in rows.get(code, []) if r.used_as in _LAB_USES]
        if len(candidates) != 1:
            raise SeedBlocked(f"lab {code}: {len(candidates)} lab rows in classrooms.xlsx")
        row, parallel = candidates[0], lab["parallel_batches"]
        capacity = row.capacity
        if capacity != parallel * batch:
            capacity = parallel * batch
            findings.append(Finding(
                "lab_capacity_conflict", f"classrooms.xlsx {code}",
                f"lab {code}: classrooms.xlsx capacity {row.capacity}, lab_capacities.yaml "
                f"{parallel} batches x {batch} = {capacity}; lab_capacities.yaml is used",
                "D27" if code == "509" else NEEDS_HUMAN,
            ))
        sub_rooms: tuple[tuple[str, int], ...] = ()
        if parallel > 1:
            if len(row.sub_rooms) == parallel:
                sub_rooms = tuple((f"{code}-{s.label}", s.capacity) for s in row.sub_rooms)
            elif code == "703":
                # D30: "703-A"/"703-B" are the two sub-rooms of 703.
                sub_rooms = ((f"{code}-A", batch), (f"{code}-B", batch))
            else:
                # Digits, as seed_reference labels an unlettered separation.
                sub_rooms = tuple((f"{code}-{i + 1}", batch) for i in range(parallel))
                findings.append(Finding(
                    "sub_room_labels_derived", f"lab_capacities.yaml {code}",
                    f"lab {code} has {parallel} batch places but no separation or printed "
                    f"sub-room labels; emitted as {', '.join(s for s, _ in sub_rooms)}",
                    NEEDS_HUMAN,
                ))
        rooms[code] = InventoryRoom(
            code, capacity, "lab", row.used_as, row.separation, parallel, sub_rooms
        )

    for r in xlsx:
        if r.code in lab_codes or r.code in rooms:
            continue
        if r.code[0] not in _CE_FLOORS:
            findings.append(Finding(
                "room_not_ce", f"classrooms.xlsx {r.code}",
                f"room {r.code} ('{r.used_as}', capacity {r.capacity}) is not on the 6th or 7th "
                "floor and is not lab 507/509: not used in v1", "D10",
            ))
            continue
        room_type = _ROOM_TYPE[r.used_as]
        if room_type == "unknown":
            findings.append(Finding(
                "unknown_room_usage", f"classrooms.xlsx {r.code}",
                f"room {r.code} 'used as' reads '{r.used_as}': emitted as room_type unknown",
                NEEDS_HUMAN,
            ))
        rooms[r.code] = InventoryRoom(r.code, r.capacity, room_type, r.used_as, r.separation, 1, ())
    return Inventory(rooms, frozenset(rows), findings)


@dataclass(frozen=True)
class RoomRef:
    """A room label from a timetable, normalised against the inventory."""

    raw: str
    #: Inventory code, or None when the room is not used for generation.
    room: str | None
    sub_room: str | None
    #: (category, message, resolution) when normalising changed or rejected it.
    note: tuple[str, str, str] | None = None


def label_key(raw: str) -> str:
    """Comparison form of a room label: '607-B' == '607B', '509 new CSE' == '509'."""
    return re.sub(r"[\s-]", "", raw.upper()).replace("NEWCSE", "")


def normalise_room(raw: str, inv: Inventory) -> RoomRef:
    text = normalise_whitespace(raw)
    if match := re.fullmatch(r"(\d{3})\s+new\s+CSE", text, re.IGNORECASE):
        code = match[1]
        note = ("room_label_normalised", f"'{text}' read as lab {code}", "D27")
        return RoomRef(text, code if code in inv.rooms else None, None, note)
    if text in inv.rooms:
        return RoomRef(text, text, None)
    match = re.fullmatch(r"(\d{3})\s*-?\s*([A-Z0-9])", text, re.IGNORECASE)
    if match:
        parent, label = match[1], match[2].upper()
        if parent + label in inv.rooms:
            note = ("room_label_normalised", f"'{text}' read as room {parent + label}", "D30")
            return RoomRef(text, parent + label, None, note)
        if parent in inv.rooms:
            sub = f"{parent}-{label}"
            if sub in {code for code, _ in inv.rooms[parent].sub_rooms}:
                return RoomRef(text, parent, sub)
            declared = ", ".join(c for c, _ in inv.rooms[parent].sub_rooms) or "none"
            note = (
                "subroom_beyond_split",
                f"'{text}': room {parent} declares sub-rooms {declared}; mapped to {parent}",
                "D30",
            )
            return RoomRef(text, parent, None, note)
        return RoomRef(text, None, None, (
            "room_not_generation", f"'{text}' is outside D8/D10: recorded, not used", "D29",
        ))
    code = text.split()[0] if text else text
    if code == "505":
        reason = ("room_not_generation", "lab 505 is not used for generation in v1", "D28")
    elif code in inv.xlsx_codes:
        reason = ("room_not_generation", f"room {code} is excluded by D10", "D10")
    else:
        reason = (
            "room_not_generation",
            f"'{text}' is not in classrooms.xlsx: recorded, not used", "D29",
        )
    return RoomRef(text, None, None, reason)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

LAB_KINDS = ("practical", "elective", "mdm", "exam", "out_of_scope", "unparsed")


@dataclass
class LabEntry:
    """One non-empty cell of one lab table."""

    table: int
    row: int
    col: int
    #: The table's ROOM NO as printed, e.g. '607-B', '606-4'.
    room_label: str
    day: str
    periods: list[int]
    #: Cell text, non-empty lines joined with ' | '.
    raw: str
    kind: str
    subject_raw: str | None = None
    scheme_code: str | None = None
    batch: str | None = None
    elective_group: str | None = None
    faculty_initials_raw: str | None = None
    #: 'SE-B', 'TE-C' for a division; 'TE', 'TE&BE', 'BE', 'M.Tech' otherwise.
    audience: str | None = None
    #: A bracketed room in the cell, recorded and reported but not used.
    room_override_raw: str | None = None
    #: The table's room (inventory code), or None if not used for generation.
    room: str | None = None
    sub_room: str | None = None
    faculty_status: str | None = None
    faculty_candidates: list[str] = field(default_factory=list)
    #: Matched to a class-timetable line (practical or elective).
    matched: bool = False

    @property
    def where(self) -> str:
        return f"t{self.table} {self.room_label} {self.day[:3]} {_span(self.periods)}"

    @property
    def division(self) -> str | None:
        return self.audience if self.audience and _KEY.fullmatch(self.audience) else None

    @property
    def teaching_periods(self) -> list[int]:
        return [p for p in self.periods if p != COFFEE_PERIOD]


@dataclass
class LabTable:
    index: int
    room_label: str | None
    room: str | None
    sub_room: str | None
    utilisation_raw: str | None
    #: (occupied, denominator, percent) as printed.
    printed: tuple[int, int, float] | None
    #: Occupied (day, period) slots counted from the grid, coffee break excluded.
    occupied: int = 0

    @property
    def computed_percent(self) -> float | None:
        return 100 * self.occupied / self.printed[1] if self.printed else None

    @property
    def matches_printed(self) -> bool:
        if self.printed is None or self.computed_percent is None:
            return False
        # The document truncates: 20/30 is printed 66.66.
        num, _, pct = self.printed
        return self.occupied == num and abs(self.computed_percent - pct) < 0.01


@dataclass
class LabTimetable:
    source: str
    tables: list[LabTable] = field(default_factory=list)
    entries: list[LabEntry] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_ROOM_NO = re.compile(r"ROOM\s*NO\s*:\s*(.+?)\s*$", re.IGNORECASE)
_UTIL = re.compile(
    r"Utili[sz]ation\s*in\s*%\s*=\s*(\d+)\s*/\s*(\d+)\s*=\s*([\d.]+)\s*%", re.IGNORECASE
)
#: A bracketed room inside a cell: '(601)', '(403 B)', '(509 new CSE)'. Not '(CC)'.
_OVERRIDE = re.compile(r"\((\d{3}[^)]*)\)")
_INITIALS = re.compile(r"[A-Z][A-Za-z]{1,3}")
_EXAM = re.compile(r"\bEXAM\b", re.IGNORECASE)
_MDM = re.compile(r"\bMDM\b", re.IGNORECASE)
#: Audience lines naming no division, in match order ('TE & BE' before 'BE').
_AUDIENCE = (
    (re.compile(r"M\.?\s*TECH", re.IGNORECASE), "M.Tech"),
    (re.compile(r"\bTE\s*&\s*BE\s*COMP", re.IGNORECASE), "TE&BE"),
    (re.compile(r"\bBE\s*COMP", re.IGNORECASE), "BE"),
    (re.compile(r"\bTE\s*COMP\b", re.IGNORECASE), "TE"),
)


def _read_cell(entry: LabEntry, lines: list[str]) -> None:
    """Fill subject, batch, initials, audience, override and kind from the lines."""
    joined = " | ".join(lines)
    if override := _OVERRIDE.search(joined):
        entry.room_override_raw = normalise_whitespace(override[1])
    entry.audience = division_key(joined) or next(
        (label for pattern, label in _AUDIENCE if pattern.search(joined)), None
    )
    session = next((line for line in lines if "/" in line), lines[0])
    fields = [f for f in (normalise_whitespace(p) for p in session.split("/")) if f]
    first = normalise_whitespace(lines[0].split("/")[0])
    entry.subject_raw = first or (fields[0] if fields else None)
    rest = fields[1:] if session is lines[0] else fields
    if rest and _BATCH.fullmatch(rest[0]):
        entry.batch = rest.pop(0)
    elif rest and _ELECTIVE_GROUP.fullmatch(rest[0]):
        entry.elective_group = rest.pop(0)
    entry.faculty_initials_raw = next((r for r in rest if _INITIALS.fullmatch(r)), None)
    if entry.faculty_initials_raw is None:
        # 'M.tech DFIR ESE /SB' or 'SE COMP NR': the initials end the cell.
        tail = re.split(r"[/\s|]+", joined.strip(" |/"))[-1]
        if _INITIALS.fullmatch(tail) and not _BATCH.fullmatch(tail):
            entry.faculty_initials_raw = tail
    entry.scheme_code = SUBJECT_ALIASES.get(subject_key(entry.subject_raw or ""))

    if _EXAM.search(joined):
        entry.kind = "exam"
    elif _MDM.search(joined):
        entry.kind = "mdm"
    elif entry.audience in ("BE", "M.Tech"):
        entry.kind = "out_of_scope"
    elif entry.elective_group or entry.audience in ("TE", "TE&BE"):
        entry.kind = "elective"
    elif entry.division and entry.scheme_code and entry.batch:
        entry.kind = "practical"
    else:
        entry.kind = "unparsed"


def parse_lab_timetable(
    path: Path = LAB_FILE,
    class_tt: ClassTimetable | None = None,
    faculty: FacultyIndex | None = None,
    inventory: Inventory | None = None,
) -> LabTimetable:
    faculty = faculty_index() if faculty is None else faculty
    class_tt = parse_class_timetable(faculty=faculty) if class_tt is None else class_tt
    inventory = room_inventory() if inventory is None else inventory
    out = LabTimetable(path.name)
    room_label: str | None = None
    util: re.Match[str] | None = None
    index = 0
    for kind, element in walk_body(open_document(path)):
        if kind == "paragraph":
            text = normalise_whitespace(paragraph_text(element))
            if match := _ROOM_NO.search(text):
                room_label = match[1]
            if match := _UTIL.search(text):
                util = match
            continue
        _parse_table(out, index, element, room_label, util, inventory)
        index += 1
        room_label, util = None, None
    _resolve_faculty(out, class_tt, faculty)
    _report_rooms(out, inventory)
    return out


def _parse_table(
    out: LabTimetable,
    index: int,
    table: _Element,
    room_label: str | None,
    util: re.Match[str] | None,
    inventory: Inventory,
) -> None:
    def flag(category: str, location: str, message: str, resolution: str = NEEDS_HUMAN) -> None:
        out.findings.append(Finding(category, location, message, resolution))

    ref = normalise_room(room_label, inventory) if room_label else None
    record = LabTable(
        index, room_label, ref.room if ref else None, ref.sub_room if ref else None,
        util[0] if util else None,
        (int(util[1]), int(util[2]), float(util[3])) if util else None,
    )
    out.tables.append(record)
    label = room_label or f"t{index}"
    if room_label is None:
        flag("table_without_room", f"t{index}", "no 'ROOM NO:' line before this table")
    if util is None:
        flag("utilisation_missing", f"t{index} {label}", "no utilisation line before this table")

    cells, _, _ = logical_cells(table)
    days = {c.col: normalise_whitespace(c.text) for c in cells if c.row == 0 and c.col > 0}
    if [days[k] for k in sorted(days)] != list(DAYS):
        flag("grid_shape", f"t{index} {label}", f"day header reads {list(days.values())}")
    row_period, _, off_grid = time_rows(cells)
    for r, raw in off_grid:
        flag("time_off_grid", f"t{index} {label} r{r}", f"time {raw!r} fits no ROADMAP §5 period")

    occupied: set[tuple[str, int]] = set()
    for c in cells:
        if not c.row or not c.col or not c.text.strip():
            continue
        if re.fullmatch(r"(SHORT-?)?BREAK", "".join(c.text.split()).upper()):
            continue
        day = days.get(c.col, f"column {c.col}")
        periods = list(dict.fromkeys(
            row_period[r] for r in range(c.row, c.row + c.row_span) if r in row_period
        ))
        lines = [normalise_whitespace(line) for line in c.text.split("\n") if line.strip()]
        entry = LabEntry(index, c.row, c.col, label, day, periods, " | ".join(lines), "unparsed")
        if c.col_span > 1:
            flag("grid_shape", entry.where, f"cell spans {c.col_span} day columns: {entry.raw!r}")
        _read_cell(entry, lines)
        entry.room = ref.room if ref else None
        entry.sub_room = ref.sub_room if ref else None
        out.entries.append(entry)
        occupied.update((day, p) for p in entry.teaching_periods)

        override = normalise_room(entry.room_override_raw, inventory) \
            if entry.room_override_raw else None
        if entry.room_override_raw:
            flag("room_override", entry.where,
                 f"{entry.raw!r} is in the {label} table, whose utilisation line counts it, "
                 f"but names room '{entry.room_override_raw}' in brackets; the table's room "
                 "is kept")
        if entry.kind == "exam":
            flag("exam_block", entry.where, f"{entry.raw!r}: an exam block, not a weekly session")
        elif entry.kind == "out_of_scope":
            flag("out_of_scope_in_lab", entry.where,
                 f"{entry.raw!r} ({entry.audience}) occupies {label}; D2 puts it out of scope "
                 "and D24 freezes only D3 items, so it is not blocked")
        elif entry.kind == "mdm":
            flag("frozen_in_lab", entry.where,
                 f"{entry.raw!r}: MDM in {label}, frozen with its teacher and room", "D24")
        elif entry.kind == "unparsed":
            flag("unparsed_cell", entry.where, f"cannot read {entry.raw!r}")
        if override and override.room and inventory.rooms[override.room].room_type != "lab":
            flag("lab_in_classroom", entry.where,
                 f"{entry.raw!r} names classroom {override.room} for a lab: recorded, not used "
                 "for labs", "D29")
    record.occupied = len(occupied)
    if record.printed and not record.matches_printed:
        num, den, pct = record.printed
        flag("utilisation_mismatch", f"t{index} {label}",
             f"printed {num}/{den} = {pct} %, grid has {record.occupied} occupied periods "
             f"= {record.computed_percent:.2f} %")


def _resolve_faculty(out: LabTimetable, class_tt: ClassTimetable, faculty: FacultyIndex) -> None:
    scopes = legend_scopes(faculty)
    electives: dict[tuple, list[Entry]] = {}
    for e in class_tt.entries:
        if e.subject_raw and e.excluded:
            key = (e.day, tuple(e.periods), subject_key(e.subject_raw), e.elective_group,
                   e.faculty_initials_raw)
            electives.setdefault(key, []).append(e)
    unresolved: dict[tuple[str, str], list[str]] = {}
    for entry in out.entries:
        if entry.kind == "elective":
            key = (entry.day, tuple(entry.periods), subject_key(entry.subject_raw or ""),
                   canonical_group(entry.elective_group), entry.faculty_initials_raw)
            twins = [e for k, es in electives.items() if _same_elective(k, key) for e in es]
            if twins:
                entry.matched = True
                entry.faculty_status, entry.faculty_candidates = class_resolution(twins[0], faculty)
            else:
                entry.faculty_status = "no_division"
                out.findings.append(Finding(
                    "elective_not_in_class_tt", entry.where,
                    f"{entry.raw!r}: no matching elective line in the class timetable",
                    NEEDS_HUMAN,
                ))
        else:
            audience = entry.division or entry.audience
            entry.faculty_status, entry.faculty_candidates = resolve(
                entry.faculty_initials_raw, audience, faculty, scopes
            )
        if entry.faculty_status in ("not_in_division_legend", "no_division", "missing"):
            unresolved.setdefault(
                (entry.faculty_initials_raw or "<none>", entry.faculty_status), []
            ).append(entry.where)
    for (initials, status), wheres in unresolved.items():
        out.findings.append(Finding(
            "initials_unresolved", ", ".join(wheres),
            f"{initials} x{len(wheres)}: {status.replace('_', ' ')}. Not resolved.",
            NEEDS_HUMAN,
        ))


def canonical_group(group: str | None) -> str | None:
    return re.sub(r"\s", "", group).upper() if group else None


def _same_elective(class_key: tuple, lab_key: tuple) -> bool:
    day, periods, subject, group, initials = class_key
    return (day, periods, subject, canonical_group(group), initials) == lab_key


def _report_rooms(out: LabTimetable, inventory: Inventory) -> None:
    """One finding per room label that normalising changed or rejected."""
    seen: dict[str, list[str]] = {}
    for t in out.tables:
        if t.room_label:
            seen.setdefault(t.room_label, []).append(f"t{t.index} ROOM NO")
    for e in out.entries:
        if e.room_override_raw:
            seen.setdefault(e.room_override_raw, []).append(e.where)
    for raw, wheres in seen.items():
        note = normalise_room(raw, inventory).note
        if note:
            out.findings.append(Finding(note[0], ", ".join(wheres), note[1], note[2]))


# --------------------------------------------------------------------------- #
# Cross-check with the class timetable (task 3)
# --------------------------------------------------------------------------- #


def cross_check(class_tt: ClassTimetable, lab: LabTimetable) -> list[Finding]:
    """Every in-scope practical must be in both timetables, identically.

    Keyed by (division, batch, course): P = 2 is one block per batch per week.
    Day, periods and initials must agree; a room disagreement is reported too.
    Marks matched lab entries.
    """
    class_side: dict[tuple, list[Entry]] = {}
    for e in class_tt.entries:
        if e.session_type == "practical" and not e.excluded:
            class_side.setdefault((division_key(e.division), e.batch, e.scheme_code), []).append(e)
    lab_side: dict[tuple, list[LabEntry]] = {}
    for le in lab.entries:
        if le.kind == "practical":
            lab_side.setdefault((le.division, le.batch, le.scheme_code), []).append(le)

    findings: list[Finding] = []

    def flag(category: str, where: str, message: str) -> None:
        findings.append(Finding(category, where, message, NEEDS_HUMAN))

    for key in sorted(set(class_side) | set(lab_side), key=lambda k: tuple(map(str, k))):
        div, batch, code = key
        cs, ls = class_side.get(key, []), lab_side.get(key, [])
        label = f"{div} batch {batch} {code}"
        if len(cs) > 1 or len(ls) > 1:
            flag("practical_duplicated", label,
                 f"{len(cs)} class-timetable and {len(ls)} lab-timetable lines; expected one each")
        if not ls:
            for c in cs:
                flag("practical_missing_in_lab_tt", f"{c.division} {c.where}",
                     f"{c.raw!r} has no line in the lab timetable")
            continue
        if not cs:
            for le in ls:
                flag("practical_missing_in_class_tt", le.where,
                     f"{le.raw!r} ({label}) has no line in the class timetable")
            continue
        c, le = cs[0], ls[0]
        le.matched = True
        diffs = [
            f"{name}: class {a!r} vs lab {b!r}"
            for name, a, b in (
                ("day", c.day, le.day),
                ("periods", _span(c.periods), _span(le.periods)),
                ("teacher", c.faculty_initials_raw, le.faculty_initials_raw),
            )
            if a != b
        ]
        if diffs:
            flag("practical_mismatch", f"{c.division} {c.where} / {le.where}",
                 f"{label}: " + "; ".join(diffs))
        lab_rooms = [r for r in (le.room_label, le.room_override_raw) if r]
        if c.room_raw and label_key(c.room_raw) not in map(label_key, lab_rooms):
            flag("practical_room_mismatch", f"{c.division} {c.where} / {le.where}",
                 f"{label}: class timetable room {c.room_raw!r}, lab timetable "
                 + " or ".join(map(repr, lab_rooms)))
    return findings
