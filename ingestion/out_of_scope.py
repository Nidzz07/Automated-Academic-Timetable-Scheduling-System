"""Printed occupancy outside the SE/TE grids that still blocks CE rooms and teachers.

D35: sessions of out-of-scope programmes (BE, M.Tech, FE) printed in the EVEN
timetables that use a D8 lab, a D10 classroom or a CE faculty member are frozen:
they block that room and that teacher at their periods. "CE faculty" is
Faculty___Subjects.xlsx (D44). Three files print such sessions:

- the BE and M.Tech grids of the class timetable (t17, t19). Their lines are
  ``SUBJECT / [BATCH /] ROOM / INITIALS`` in no fixed order, so each field is
  read by its shape; initials resolve through that grid's own legend only;
- the BE and M.Tech cells of the lab timetable (lab_tt kind ``out_of_scope``);
- the faculty timetable. Its cells that name no SE/TE division and are not an
  SE/TE subject are teaching outside these grids; the teacher is the page's
  owner. FE teaching appears only here (PSOOP, batches A1..G4, room 003; the
  file prints no programme for it).

The faculty timetable also prints MDM theory and labs with a teacher and room
where the class grids show a label-only MDM block; those block that teacher
and room (D24). Exam blocks of the lab timetable are frozen room occupancy at
their slot (D37), with no teacher or cohort.

One event can be printed in all three files: lines with the same day,
overlapping periods and the same teacher (or, teacher unknown, the same room
and subject) are one block, read in the order above; a disagreement on periods
or room is reported. A line that is the same class as a frozen SE/TE session
(a combined TE+BE elective) adds nothing. A line with no CE teacher and no
generation room blocks nothing and is reported. Nothing is invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.class_tt import (
    _ELECTIVE_GROUP,
    COFFEE_PERIOD,
    EVEN_CLASS_FILE,
    LABELS,
    SUBJECT_ALIASES,
    ClassTimetable,
    FacultyIndex,
    _span,
    subject_key,
    time_rows,
)
from ingestion.docx_reader import logical_cells, open_document, walk_body
from ingestion.faculty import FacultyTimetable
from ingestion.initials_legend import extract_legends, normalise_whitespace
from ingestion.lab_tt import (
    NEEDS_HUMAN,
    Finding,
    Inventory,
    LabTimetable,
    RoomRef,
    attributed,
    normalise_room,
)
from ingestion.seed_legends import legend_scope
from ingestion.survey import survey_file

_ROOM_FIELD = re.compile(r"\d{3}(\s*-?\s*[A-Z0-9])?(\s+new(\s+CSE)?)?|online", re.IGNORECASE)
_ROOM_TOKEN = re.compile(r"\b\d{3}(?:\s*-\s*[A-Z0-9]\b)?")
_BATCH_FIELD = re.compile(r"[A-E]")
_INITIALS_FIELD = re.compile(r"[A-Z][A-Za-z]{1,3}")
_SE_TE_DIVISION = re.compile(r"\b(SE|TE)\s*-\s*[A-D]\b", re.IGNORECASE)
_TE_AUDIENCE = re.compile(r"/\s*TE\s*(,|/|$)")
_MDM = re.compile(r"\bMDM\b", re.IGNORECASE)


@dataclass
class Line:
    """One printed line of occupancy outside the SE/TE grids."""

    id: str
    source: str
    where: str
    kind: str  # out_of_scope | mdm | exam
    day: str
    #: Teaching periods covered (the coffee break skipped), wall-clock.
    periods: list[int]
    raw: str
    subject: str
    initials: str | None
    #: The CE faculty member (D44) teaching it, or None.
    teacher: str | None
    #: The generation room (D8/D10) it uses, or None.
    room: RoomRef | None
    room_raw: str | None
    programme: str
    #: Set when the line's initials name nobody (or several) in its legend.
    initials_problem: str | None = None


@dataclass
class Block:
    lines: list[Line]
    periods: list[int]
    notes: list[str] = field(default_factory=list)

    @property
    def first(self) -> Line:
        return self.lines[0]

    @property
    def resolution(self) -> str:
        return {"out_of_scope": "D35", "mdm": "D24", "exam": "D37"}[self.first.kind]

    @property
    def teacher(self) -> str | None:
        return next((ln.teacher for ln in self.lines if ln.teacher), None)

    @property
    def room(self) -> RoomRef | None:
        return next((ln.room for ln in self.lines if ln.room), None)


@dataclass(frozen=True)
class Frozen:
    """A frozen SE/TE session, as far as matching needs it."""

    teacher: str | None
    initials: str | None
    day: str
    periods: frozenset[int]
    subject: str
    room: RoomRef | None


def _teaching(periods: list[int]) -> list[int]:
    return [p for p in periods if p != COFFEE_PERIOD]


def _room(raw: str | None, inv: Inventory) -> RoomRef | None:
    """The generation room a printed label names, or None ('507 new' = lab 507)."""
    if not raw or raw.lower() == "online":
        return None
    ref = normalise_room(re.sub(r"\s+new$", "", raw, flags=re.IGNORECASE), inv)
    return ref if ref.room else None


def _ce(name: str | None, ce_faculty: frozenset[str]) -> str | None:
    return name if name in ce_faculty else None


# --------------------------------------------------------------------------- #
# The three sources
# --------------------------------------------------------------------------- #


def class_grid_lines(
    faculty: FacultyIndex, inv: Inventory, ce_faculty: frozenset[str],
) -> list[Line]:
    """Lines of the class timetable's out-of-scope grids (BE, M.Tech)."""
    legends = extract_legends(EVEN_CLASS_FILE)
    legend_tables = {lg.table_index for lg in legends}
    scope_of = {lg.grid_header: legend_scope(lg) for lg in legends}
    headers = [t.header for t in survey_file(EVEN_CLASS_FILE).tables]
    tables = [el for kind, el in walk_body(open_document(EVEN_CLASS_FILE)) if kind == "table"]
    out: list[Line] = []
    for index, table in enumerate(tables):
        scope = scope_of.get(headers[index])
        if index in legend_tables or scope is None or scope.semester_number in (4, 6):
            continue
        programme = "M.Tech" if scope.programme == "M.Tech" else "BE"
        by_init = faculty.by_scope.get(scope, {})
        cells, _, _ = logical_cells(table)
        days = {c.col: normalise_whitespace(c.text) for c in cells if c.row == 0 and c.col > 0}
        row_period, _, _ = time_rows(cells)
        for c in cells:
            if not c.row or not c.col or not c.text.strip():
                continue
            if re.fullmatch(r"(SHORT-?)?BREAK", "".join(c.text.split()).upper()):
                continue
            periods = _teaching(list(dict.fromkeys(
                row_period[r] for r in range(c.row, c.row + c.row_span) if r in row_period)))
            lines = [normalise_whitespace(t) for t in c.text.split("\n") if t.strip()]
            for n, text in enumerate(lines):
                if "/" not in text or any(p.search(text) for p, _ in LABELS):
                    continue  # a note, or a label-only block naming no teacher or room
                fields = [normalise_whitespace(re.sub(r"\(.*?\)", "", f))
                          for f in text.split("/")]
                fields = [f for f in fields if f]
                room_raw = next((f for f in fields[1:] if _ROOM_FIELD.fullmatch(f)), None)
                initials = next((f for f in fields[1:] if f != room_raw
                                 and not _BATCH_FIELD.fullmatch(f)
                                 and _INITIALS_FIELD.fullmatch(f)), None)
                names = by_init.get(initials or "", [])
                where = f"t{index} r{c.row} c{c.col} {days[c.col][:3]} {_span(periods)}"
                problem = (f"'{initials}' names {names or 'nobody'} in the {scope.division} "
                           "legend") if initials and len(names) != 1 else None
                out.append(Line(
                    f"oos-t{index}-r{c.row}-c{c.col}-l{n}", EVEN_CLASS_FILE.name,
                    f"{scope.division} {where}", "out_of_scope", days[c.col], periods, text,
                    fields[0], initials, _ce(names[0] if len(names) == 1 else None, ce_faculty),
                    _room(room_raw, inv), room_raw, programme, problem))
    return out


def lab_lines(lab: LabTimetable, ce_faculty: frozenset[str]) -> list[Line]:
    """The lab timetable's BE / M.Tech cells (D35) and exam blocks (D37)."""
    out: list[Line] = []
    for le in lab.entries:
        if le.kind not in ("out_of_scope", "exam"):
            continue
        exam = le.kind == "exam"
        ref = RoomRef(le.room_label, le.room, le.sub_room) if le.room else None
        teacher = None if exam else _ce(attributed(le.faculty_status, le.faculty_candidates),
                                        ce_faculty)
        out.append(Line(
            f"{'exam' if exam else 'oos'}-lab-t{le.table}-r{le.row}-c{le.col}", lab.source,
            le.where, le.kind, le.day, le.teaching_periods, le.raw, le.subject_raw or le.raw,
            le.faculty_initials_raw, teacher, ref, le.room_label, le.audience or "not printed"))
    return out


def faculty_page_lines(
    faculty_tt: FacultyTimetable, inv: Inventory, ce_faculty: frozenset[str],
) -> list[Line]:
    """Faculty-timetable cells outside the SE/TE grids, taught by the page's owner.

    Skipped: cells naming an SE/TE division (the class timetable is
    authoritative, D4) and SE/TE subjects or TE electives with no division
    (reported, never guessed into a block).
    """
    out: list[Line] = []
    for page in faculty_tt.pages:
        teacher = _ce(page.member, ce_faculty)
        for fs in page.sessions:
            if _SE_TE_DIVISION.search(fs.raw):
                continue
            mdm = bool(_MDM.search(fs.raw))
            where = f"t{fs.table} {page.name_raw} {fs.day[:3]} {_span(fs.periods)}"
            if not mdm and (subject_key(fs.subject_raw) in SUBJECT_ALIASES
                            or _ELECTIVE_GROUP.search(fs.raw) or _TE_AUDIENCE.search(fs.raw)):
                out.append(Line(f"fac-t{fs.table}-r{fs.row}-c{fs.col}", faculty_tt.source,
                                where, "se_te", fs.day, _teaching(fs.periods), fs.raw,
                                fs.subject_raw, None, teacher, None, None, "SE/TE"))
                continue
            rest = fs.raw.split("/", 1)[1] if "/" in fs.raw else ""
            token = _ROOM_TOKEN.search(rest)
            room_raw = normalise_whitespace(token[0]) if token else None
            programme = ("M.Tech" if re.search(r"M\.?\s*TECH", fs.raw, re.IGNORECASE)
                         else "BE" if re.search(r"\bB\.?\s*E\b", fs.raw) else "not printed")
            out.append(Line(
                f"oos-fac-t{fs.table}-r{fs.row}-c{fs.col}", faculty_tt.source, where,
                "mdm" if mdm else "out_of_scope", fs.day, _teaching(fs.periods), fs.raw,
                fs.subject_raw, None, teacher, _room(room_raw, inv), room_raw, programme))
    return out


# --------------------------------------------------------------------------- #
# Merging
# --------------------------------------------------------------------------- #


def _same_class(line: Line, f: Frozen) -> bool:
    if line.day != f.day or f.periods.isdisjoint(line.periods):
        return False
    if line.teacher and f.teacher:
        return line.teacher == f.teacher
    return subject_key(line.subject) == subject_key(f.subject) and line.initials == f.initials


def _same_event(line: Line, block: Block) -> bool:
    b = block.first
    if line.day != b.day or set(block.periods).isdisjoint(line.periods):
        return False
    if line.kind == "exam" or b.kind == "exam":
        return line.kind == b.kind and _place(line.room) == _place(b.room)
    if line.teacher and block.teacher:
        return line.teacher == block.teacher
    return (line.room is not None and _place(line.room) == _place(block.room)
            and subject_key(line.subject) == subject_key(b.subject))


def _place(ref: RoomRef | None) -> tuple[str | None, str | None] | None:
    return (ref.room, ref.sub_room) if ref else None


def _room_label(ref: RoomRef | None) -> str:
    return (ref.sub_room or ref.room or "?") if ref else "none"


def blocks(
    class_tt: ClassTimetable, lab: LabTimetable, faculty_tt: FacultyTimetable,
    faculty: FacultyIndex, inv: Inventory, ce_faculty: frozenset[str], frozen: list[Frozen],
    teaching: dict[tuple[str, str], set[int]],
) -> tuple[list[Block], list[Finding]]:
    """Every block, and a finding for each block and each line that adds none.

    ``teaching`` maps (teacher, day) to the periods the class and lab
    timetables already give that teacher in SE/TE; a faculty-page SE/TE line
    outside them is reported.
    """
    findings: list[Finding] = []
    lines = (class_grid_lines(faculty, inv, ce_faculty) + lab_lines(lab, ce_faculty)
             + faculty_page_lines(faculty_tt, inv, ce_faculty))
    out: list[Block] = []
    for line in lines:
        if line.kind == "se_te":
            if not line.teacher or teaching.get((line.teacher, line.day), set()).isdisjoint(
                    line.periods):
                findings.append(Finding(
                    "faculty_tt_line_not_in_grids", f"{line.source} {line.where}",
                    f"{line.raw!r}: an SE/TE subject or elective printed without a single "
                    f"SE/TE division, and the class and lab timetables give {line.teacher} "
                    "nothing at that slot; not blocked", NEEDS_HUMAN))
            continue
        twin = next((f for f in frozen if line.kind != "exam" and _same_class(line, f)), None)
        if twin is not None:
            if line.room and twin.room and _place(line.room) != _place(twin.room):
                findings.append(Finding(
                    "out_of_scope_room_disagreement", f"{line.source} {line.where}",
                    f"{line.raw!r} is the frozen SE/TE session in {_room_label(twin.room)} "
                    f"(same teacher and slot) but names {_room_label(line.room)}; the frozen "
                    "session's room is kept", NEEDS_HUMAN))
            continue
        if line.initials_problem:
            findings.append(Finding("out_of_scope_initials_unresolved",
                                    f"{line.source} {line.where}",
                                    f"{line.raw!r}: {line.initials_problem}", NEEDS_HUMAN))
        block = next((b for b in out if _same_event(line, b)), None)
        if block is None:
            out.append(Block([line], list(line.periods)))
            continue
        if line.room and block.room and _place(line.room) != _place(block.room):
            block.notes.append(f"{line.where} names {_room_label(line.room)}")
        if set(line.periods) != set(block.periods):
            block.notes.append(f"{line.where} covers {_span(line.periods)}")
        block.lines.append(line)
        block.periods = sorted(set(block.periods) | set(line.periods))

    kept: list[Block] = []
    for b in out:
        sources = " || ".join(f"{ln.source} {ln.where} {ln.raw!r}" for ln in b.lines)
        if b.teacher is None and b.room is None:
            unknown = any(ln.initials and not ln.teacher for ln in b.lines)
            findings.append(Finding(
                "out_of_scope_not_blocking", sources,
                f"{b.first.raw!r} ({b.first.programme}): no CE teacher and no D8/D10 room, "
                "so it blocks nothing" + ("; its initials are unresolved" if unknown else ""),
                NEEDS_HUMAN if unknown else b.resolution))
            continue
        kept.append(b)
        category = {"D35": "frozen_out_of_scope", "D24": "frozen_faculty_tt_mdm",
                    "D37": "frozen_exam"}[b.resolution]
        findings.append(Finding(
            category, sources,
            f"{b.first.raw!r} ({b.first.programme}) {b.first.day[:3]} {_span(b.periods)}: "
            f"blocks teacher {b.teacher or 'none'}, room {_room_label(b.room)}",
            b.resolution))
        if b.notes:
            findings.append(Finding(
                "frozen_sources_disagree", sources,
                f"{b.first.raw!r}: " + "; ".join(b.notes) + f"; blocked {_span(b.periods)} in "
                f"{_room_label(b.room)}", NEEDS_HUMAN))
    return kept, findings
