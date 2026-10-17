"""Parse the EVEN class timetable for the SE and TE divisions (ROADMAP S6).

Pure parsing: reads ``data/real/CE_Class_Time_Table-EVEN_sem_25-26.docx``
through :mod:`ingestion.docx_reader` (content controls included) and returns
plain dataclasses. Nothing is written to the database.

One :class:`Entry` per non-empty line of a grid cell: a lab cell listing four
parallel batch practicals yields four entries. Every entry keeps its raw text
and grid position, and every decision about it is recorded on it:

- **time**: the wall-clock rows the cell covers are mapped to periods P0-P9
  using ROADMAP section 5 (``data/reference/time_grid.yaml``); ``duration``
  counts only the year's teaching periods, so a block spanning the coffee
  break is still a 2-period block.
- **subject**: matched to a scheme code through :data:`SUBJECT_ALIASES`
  only, within the division's own semester. Anything else is *unmatched*.
- **faculty**: initials are resolved with the same division-scoped legend
  logic that fills the ``faculty_initials`` table (``seed_legends``,
  migration 0004). An ambiguous initial keeps all its candidates; an initial
  missing from its division's legend is flagged, never borrowed from another.
- **exclusion** (D3): minors, HSSM, LLC, projects, electives and non-courses
  are kept as excluded entries with a reason, never dropped.

Every disagreement with the scheme or the grid becomes an :class:`Anomaly`.

Run from the repo root::

    python -m ingestion.class_tt   # writes the report and data/generated/class_tt_even.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml
from lxml.etree import _Element

from ingestion.docx_reader import GridCell, logical_cells, open_document, walk_body
from ingestion.initials_legend import extract_legends, normalise_whitespace
from ingestion.scheme import Course, TeachingScheme, load_scheme
from ingestion.seed_legends import (
    LegendScope,
    initials_by_scope,
    legend_scope,
    real_legends,
    resolve_legend_names,
)
from ingestion.seed_reference import (
    EXTRA_FACULTY_NAME,
    REPO_ROOT,
    SeedBlocked,
    parse_faculty_subjects,
)
from ingestion.survey import REAL_DIR, survey_file

EVEN_CLASS_FILE = REAL_DIR / "CE_Class_Time_Table-EVEN_sem_25-26.docx"
DEFAULT_REPORT = Path(__file__).resolve().parent / "class_tt_report.txt"
DEFAULT_JSON = REPO_ROOT / "data" / "generated" / "class_tt_even.json"

# --------------------------------------------------------------------------- #
# Grid (ROADMAP section 5, D6)
# --------------------------------------------------------------------------- #

TIME_GRID_YAML = REPO_ROOT / "data" / "reference" / "time_grid.yaml"
with TIME_GRID_YAML.open(encoding="utf-8") as _handle:
    _GRID = yaml.safe_load(_handle)

DAYS: tuple[str, ...] = tuple(_GRID["days"])
#: Wall-clock period -> (start, end), 24-hour clock.
PERIOD_TIMES: dict[int, tuple[str, str]] = {
    p["period"]: (p["start"], p["end"]) for p in _GRID["periods"]
}
_PERIOD_BY_TIMES = {times: period for period, times in PERIOD_TIMES.items()}
COFFEE_PERIOD: int = _GRID["coffee_period"]
#: Lunch is per year (D6).
LUNCH_PERIOD: dict[str, int] = dict(_GRID["lunch_period"])

_TIME = re.compile(r"(\d{1,2})[.:](\d{2})\s*-\s*(\d{1,2})[.:](\d{2})")


def _clock(hour: str, minute: str) -> str:
    h = int(hour)
    # The document prints a 12-hour clock without am/pm ("1.15-2.15"). The day
    # runs 09:00-18:15 (section 5), so 1 to 8 o'clock can only be afternoon.
    return f"{h + 12 if 1 <= h <= 8 else h:02d}:{minute}"


def period_of(time_text: str) -> int | None:
    """Period for a printed time range, or ``None`` if it fits no grid period."""
    match = _TIME.search(time_text)
    if match is None:
        return None
    return _PERIOD_BY_TIMES.get((_clock(match[1], match[2]), _clock(match[3], match[4])))


def time_rows(
    cells: list[GridCell],
) -> tuple[dict[int, int], dict[int, str], list[tuple[int, str]]]:
    """Read a grid's time column: row -> period, row -> printed time, off-grid rows.

    Shared by the class, lab and faculty grids, which all put the time in column 0.
    """
    row_period: dict[int, int] = {}
    row_time: dict[int, str] = {}
    off_grid: list[tuple[int, str]] = []
    for c in cells:
        if c.col or not c.row:
            continue
        raw = normalise_whitespace(c.text)
        period = period_of(raw)
        if period is None:
            off_grid.append((c.row, raw))
        for r in range(c.row, c.row + c.row_span):
            row_time[r] = raw
            if period is not None:
                row_period[r] = period
    return row_period, row_time, off_grid


# --------------------------------------------------------------------------- #
# Cell vocabulary
# --------------------------------------------------------------------------- #

#: Timetable subject (uppercased, spaces and hyphens removed) -> scheme code.
#: Every entry but the DevOps ones is the initials of the scheme course name
#: with "and", "in" and "of" skipped (a test checks this). The DevOps spellings
#: are hand-reviewed: the acronym of "DevOps Lab" would be "DL", which the TE
#: grids use for the Deep Learning elective. "Deop" is a typo in the source.
SUBJECT_ALIASES: dict[str, str] = {
    "SMCS": "CE205",
    "PCS": "AS201",
    "OS": "CE206",
    "DAA": "CE207",
    "CCN": "CE208",
    "SPCC": "CE306",
    "ML": "CE307",
    "DEVOP": "CE308",
    "DEVOPS": "CE308",
    "DEOP": "CE308",
}
HAND_REVIEWED_ALIASES = frozenset({"DEVOP", "DEVOPS", "DEOP"})

#: Whole-line labels for blocks that are not schedulable courses (D3,
#: CONTEXT.md 3.4). A line may match several ("MDM Lab / Major Project").
LABELS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bMDM\b", re.IGNORECASE), "minor (MDM) - D3"),
    (re.compile(r"\bHSS", re.IGNORECASE), "HSSM - D3"),
    (re.compile(r"\bLLC\b", re.IGNORECASE), "LLC - D3"),
    (re.compile(r"major\s*-?\s*project", re.IGNORECASE), "project - D3"),
    (re.compile(r"student\s+activity", re.IGNORECASE), "not a course: student activity"),
)

#: D5: four batches per division.
_BATCH = re.compile(r"[A-D]")
#: Programme-elective group in the batch position: "PE-I-A", "PE II -C".
_ELECTIVE_GROUP = re.compile(r"PE\s*-?\s*I{1,3}\s*-?\s*[A-Z]")

ELECTIVE_REASON = "elective - D3"
SESSION_TYPES = ("lecture", "tutorial", "practical")


def subject_key(subject: str) -> str:
    return re.sub(r"[\s-]", "", subject).upper()


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass
class Entry:
    """One line of one grid cell, with every decision taken about it."""

    table: int
    row: int
    col: int
    line: int
    division: str
    year: str
    semester: int
    day: str
    time_raw: list[str]
    #: Every wall-clock period the cell covers, breaks included.
    periods: list[int]
    start_period: int | None
    #: Teaching periods covered (the coffee break and the year's lunch excluded).
    duration: int
    raw: str
    subject_raw: str | None = None
    scheme_code: str | None = None
    batch: str | None = None
    elective_group: str | None = None
    faculty_initials_raw: str | None = None
    #: resolved | ambiguous | not_in_division_legend | missing
    faculty_status: str | None = None
    faculty_candidates: list[str] = field(default_factory=list)
    room_raw: str | None = None
    #: lecture | tutorial | practical, for scheme-matched entries only.
    session_type: str | None = None
    excluded: bool = False
    exclude_reason: str | None = None

    @property
    def where(self) -> str:
        return f"t{self.table} r{self.row} c{self.col} {self.day[:3]} {_span(self.periods)}"


@dataclass(frozen=True)
class Anomaly:
    kind: str
    division: str
    where: str
    detail: str


@dataclass(frozen=True)
class TableRecord:
    index: int
    header: str | None
    division: str | None
    parsed: bool
    skip_reason: str | None


@dataclass
class ClassTimetable:
    source: str
    tables: list[TableRecord] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    #: division -> {"coffee": periods, "lunch": periods} as the grid marks them.
    breaks: dict[str, dict[str, list[int]]] = field(default_factory=dict)


Flag = Callable[[str, str, str], None]


def _span(periods: list[int]) -> str:
    if not periods:
        return "P?"
    return f"P{periods[0]}" if len(periods) == 1 else f"P{periods[0]}-P{periods[-1]}"


# --------------------------------------------------------------------------- #
# Faculty resolution (pure; same logic as seed_legends)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FacultyIndex:
    #: scope -> initials -> sorted candidate full names
    by_scope: dict[LegendScope, dict[str, list[str]]]
    #: The 41-member CE faculty list (D11): spreadsheet, Deepak Nair, legend-only.
    ce_faculty: frozenset[str]


def faculty_index() -> FacultyIndex:
    legends = real_legends()
    existing = [f.full_name for f in parse_faculty_subjects()] + [EXTRA_FACULTY_NAME]
    resolution = resolve_legend_names(legends, existing)
    if resolution.unresolved:
        raise SeedBlocked(f"legend names resolve to no faculty: {resolution.unresolved}")
    by_scope = {
        scope: {k: sorted(resolution.canonical[t] for t in keys) for k, keys in by_init.items()}
        for scope, by_init in initials_by_scope(legends, resolution).items()
    }
    return FacultyIndex(by_scope, frozenset(existing) | frozenset(resolution.new_faculty.values()))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _split_session(entry: Entry, text: str) -> str | None:
    """Fill subject/batch/initials/room from ``SUBJ / [BATCH /] INIT / ROOM``.

    Returns a problem description, or ``None`` if the line was well formed.
    """
    fields = [normalise_whitespace(part) for part in text.split("/")]
    entry.subject_raw = fields[0]
    rest = fields[1:]
    if rest and _BATCH.fullmatch(rest[0]):
        entry.batch = rest.pop(0)
    elif rest and _ELECTIVE_GROUP.fullmatch(rest[0]):
        entry.elective_group = rest.pop(0)
    if len(rest) == 2:
        entry.faculty_initials_raw, entry.room_raw = rest
        return None
    if len(rest) == 1 and len(rest[0].split()) == 2:
        entry.faculty_initials_raw, entry.room_raw = rest[0].split()
        return f"missing '/' between initials and room in {text!r}"
    return f"cannot read initials and room from {text!r}"


def _session_type(course: Course, entry: Entry) -> tuple[str | None, str | None]:
    """``(session type, problem)`` from the scheme hours and the batch marker."""
    if entry.batch is None:
        if course.L:
            return "lecture", None
        if course.T:
            return "tutorial", "division-wide tutorial; D9 says 1 h per batch"
        return None, "division-wide session for a course with no L or T hours"
    if course.P and entry.duration == 2:
        return "practical", None
    if course.T and entry.duration == 1:
        return "tutorial", None
    if course.P:
        return "practical", None  # the 2-period check reports it
    if course.T:
        return "tutorial", f"batch tutorial of {entry.duration} periods"
    return None, "batch session for a course with no T or P hours"


def parse_class_timetable(
    path: Path = EVEN_CLASS_FILE,
    scheme: TeachingScheme | None = None,
    faculty: FacultyIndex | None = None,
) -> ClassTimetable:
    scheme = load_scheme() if scheme is None else scheme
    faculty = faculty_index() if faculty is None else faculty
    years = {s.semester: s.year for s in scheme.semesters}
    file_legends = extract_legends(path)
    legend_at = {lg.table_index: lg for lg in file_legends}
    scope_of = {lg.grid_header: legend_scope(lg) for lg in file_legends}
    headers = [t.header for t in survey_file(path).tables]
    tables = [el for kind, el in walk_body(open_document(path)) if kind == "table"]

    out = ClassTimetable(path.name)
    for index, table in enumerate(tables):
        header = headers[index]
        if index in legend_at:
            reason = "initials legend (read by ingestion.initials_legend)"
            out.tables.append(TableRecord(index, header, legend_at[index].division, False, reason))
            continue
        scope = scope_of.get(header)
        if scope is None:
            out.tables.append(
                TableRecord(index, header, None, False, "grid with no legend-scoped header")
            )
        elif scope.semester_number not in years:
            reason = f"Semester {scope.semester_number}: out of v1 scope (D2: SE and TE only)"
            out.tables.append(TableRecord(index, header, scope.division, False, reason))
        else:
            out.tables.append(TableRecord(index, header, scope.division, True, None))
            _parse_grid(out, index, table, scope, years[scope.semester_number], scheme, faculty)
    return out


def _parse_grid(
    out: ClassTimetable,
    index: int,
    table: _Element,
    scope: LegendScope,
    year: str,
    scheme: TeachingScheme,
    faculty: FacultyIndex,
) -> None:
    division = scope.division

    def flag(kind: str, where: str, detail: str) -> None:
        out.anomalies.append(Anomaly(kind, division, where, detail))

    cells, _, _ = logical_cells(table)
    days = {c.col: normalise_whitespace(c.text) for c in cells if c.row == 0 and c.col > 0}
    if [days[k] for k in sorted(days)] != list(DAYS):
        flag("grid_shape", f"t{index}", f"day header reads {list(days.values())}")

    row_period, row_time, off_grid = time_rows(cells)
    for r, raw in off_grid:
        flag("time_off_grid", f"t{index} r{r}", f"time {raw!r} fits no ROADMAP §5 period")
    missing = sorted(set(PERIOD_TIMES) - set(row_period.values()))
    if missing:
        flag("time_off_grid", f"t{index}", f"no time row for {', '.join(f'P{p}' for p in missing)}")

    lunch = LUNCH_PERIOD[year]
    breaks: dict[str, set[int]] = {"coffee": set(), "lunch": set()}
    entries: list[Entry] = []
    for c in cells:
        if not c.row or not c.col or not c.text.strip():
            continue
        rows = range(c.row, c.row + c.row_span)
        periods = list(dict.fromkeys(row_period[r] for r in rows if r in row_period))
        time_raw = list(dict.fromkeys(row_time[r] for r in rows if r in row_time))
        cell_days = [days.get(k, f"column {k}") for k in range(c.col, c.col + c.col_span)]
        where = f"t{index} r{c.row} c{c.col} {cell_days[0][:3]} {_span(periods)}"

        letters = "".join(c.text.split()).upper()
        if re.fullmatch(r"(SHORT-?)?BREAK", letters):
            kind = "coffee" if letters.startswith("SHORT") else "lunch"
            breaks[kind].update(periods)
            if len(cell_days) < len(DAYS):
                flag(
                    "break_partial", where,
                    f"{kind} break marked only for {', '.join(cell_days)}",
                )
            continue
        if c.col_span > 1:
            flag("grid_shape", where, f"cell spans {cell_days}: {c.text!r} (not parsed)")
            continue
        if not periods:
            flag("time_off_grid", where, f"cell covers no time row: {c.text!r}")

        base = {
            "table": index,
            "row": c.row,
            "col": c.col,
            "division": division,
            "year": year,
            "semester": scope.semester_number,
            "day": cell_days[0],
            "time_raw": time_raw,
            "periods": periods,
            "start_period": periods[0] if periods else None,
            "duration": sum(p not in (COFFEE_PERIOD, lunch) for p in periods),
        }
        cell_entries: list[Entry] = []
        lines = [normalise_whitespace(line) for line in c.text.split("\n") if line.strip()]
        for n, text in enumerate(lines):
            reasons = [reason for pattern, reason in LABELS if pattern.search(text)]
            if reasons:
                reason = "; ".join(reasons)
                cell_entries.append(
                    Entry(**base, line=n, raw=text, excluded=True, exclude_reason=reason)
                )
            elif "/" in text:
                entry = Entry(**base, line=n, raw=text)
                problem = _split_session(entry, text)
                if problem:
                    flag("malformed_line", where, problem)
                cell_entries.append(entry)
            elif cell_entries and cell_entries[-1].subject_raw is None:
                # A note under a block label ("( Except SPJIMR)") belongs to it.
                cell_entries[-1].raw += "\n" + text
            else:
                cell_entries.append(
                    Entry(**base, line=n, raw=text, excluded=True,
                          exclude_reason="unrecognised cell text")
                )
                flag("unrecognised_text", where, repr(text))
        entries.extend(cell_entries)

    out.breaks[division] = {k: sorted(v) for k, v in breaks.items()}
    if breaks["coffee"] != {COFFEE_PERIOD}:
        flag("coffee_mismatch", f"t{index}",
             f"short break at {sorted(breaks['coffee'])}, expected P{COFFEE_PERIOD} (D6)")
    if breaks["lunch"] != {lunch}:
        flag("lunch_mismatch", f"t{index}",
             f"lunch break at {sorted(breaks['lunch'])}, expected P{lunch} for {year} (D6)")

    _classify(out, entries, scope, scheme, faculty, flag)
    out.entries.extend(entries)


def _classify(
    out: ClassTimetable,
    entries: list[Entry],
    scope: LegendScope,
    scheme: TeachingScheme,
    faculty: FacultyIndex,
    flag: Flag,
) -> None:
    courses = {c.code: c for c in scheme.semester(scope.semester_number).courses}
    initials = faculty.by_scope.get(scope, {})
    # Same-semester legends of other divisions: shown as hints, never used.
    hints: dict[str, set[str]] = {}
    for other, by_init in faculty.by_scope.items():
        if other != scope and other.semester_number == scope.semester_number:
            for k, names in by_init.items():
                hints.setdefault(k, set()).update(f"{n} ({other.division})" for n in names)
    electives = {subject_key(e.subject_raw) for e in entries if e.elective_group and e.subject_raw}

    unresolved: dict[str, list[str]] = {}
    unmatched: dict[str, list[str]] = {}
    for e in entries:
        if e.subject_raw is None:
            continue
        if e.faculty_initials_raw is None:
            e.faculty_status = "missing"
        elif candidates := initials.get(e.faculty_initials_raw):
            e.faculty_candidates = list(candidates)
            e.faculty_status = "resolved" if len(candidates) == 1 else "ambiguous"
            if len(candidates) > 1:
                flag("ambiguous_initials", e.where,
                     f"{e.faculty_initials_raw} -> {candidates} (kept, not picked)")
        else:
            e.faculty_status = "not_in_division_legend"
            unresolved.setdefault(e.faculty_initials_raw, []).append(e.where)

        key = subject_key(e.subject_raw)
        course = courses.get(SUBJECT_ALIASES.get(key, ""))
        if e.elective_group or key in electives:
            e.excluded, e.exclude_reason = True, ELECTIVE_REASON
            continue
        if course is None:
            e.excluded = True
            e.exclude_reason = (
                f"unmatched subject: not in the Semester {scope.semester_number} scheme"
            )
            unmatched.setdefault(e.subject_raw, []).append(e.where)
            continue
        e.scheme_code = course.code
        e.session_type, problem = _session_type(course, e)
        if problem:
            kind = "division_wide_tutorial" if "D9" in problem else "session_type"
            flag(kind, e.where, f"{e.raw!r}: {problem}")
        if e.session_type == "practical" and (
            e.duration != 2 or LUNCH_PERIOD[e.year] in e.periods
        ):
            flag("practical_block", e.where,
                 f"{e.raw!r}: practical covers {_span(e.periods)} ({e.duration} teaching "
                 "periods); D7 needs 2 consecutive teaching periods, never across lunch")
        ce_teacher = bool(e.faculty_candidates) and all(
            n in faculty.ce_faculty for n in e.faculty_candidates
        )
        if course.include is False:
            e.excluded, e.exclude_reason = True, course.exclude_reason or "scheme: include false"
        elif course.include == "if_ce_faculty" and not ce_teacher:
            e.excluded = True
            e.exclude_reason = "if_ce_faculty: teacher not resolved to the CE faculty list - D3"
        elif e.faculty_status == "resolved" and not ce_teacher:
            e.excluded, e.exclude_reason = True, "teacher not in the CE faculty list - D3"

    for k, wheres in unresolved.items():
        hint = "; ".join(sorted(hints.get(k, ()))) or "no other legend of this semester has it"
        flag("initials_not_in_division_legend", ", ".join(wheres),
             f"{k} x{len(wheres)} is not in this division's legend. Not resolved. "
             f"Other legends: {hint}")
    for subject, wheres in unmatched.items():
        flag("unmatched_subject", ", ".join(wheres), f"{subject!r} x{len(wheres)}")

    for e in entries:
        if set(e.periods) & {COFFEE_PERIOD, LUNCH_PERIOD[e.year]}:
            status = f"excluded: {e.exclude_reason}" if e.excluded else "in scope"
            raw = e.raw.replace("\n", " | ")
            flag("overlaps_break", e.where, f"{raw!r} ({status}) covers a break or lunch")

    cells: dict[tuple[int, int], list[Entry]] = {}
    for e in entries:
        cells.setdefault((e.row, e.col), []).append(e)
    for group in cells.values():
        whole = [e for e in group if e.subject_raw and not e.batch and not e.elective_group]
        if len(whole) > 1 and any(not e.excluded for e in whole):
            flag("parallel_division_sessions", group[0].where,
                 " || ".join(e.raw for e in whole))

    _cross_check(entries, courses, flag)


BATCHES = ("A", "B", "C", "D")


def hours_found(entries: list[Entry], code: str) -> dict[str, object]:
    """L hours, and T and P hours per batch, found for one course in one division.

    Counts every entry matched to the course, excluded or not. A division-wide
    tutorial counts once towards every batch.
    """
    mine = [e for e in entries if e.scheme_code == code]

    def total(kind: str, batch: str | None) -> int:
        return sum(e.duration for e in mine if e.session_type == kind and e.batch == batch)

    return {
        "L": total("lecture", None),
        "T": {b: total("tutorial", b) + total("tutorial", None) for b in BATCHES},
        "P": {b: total("practical", b) for b in BATCHES},
    }


def _cross_check(entries: list[Entry], courses: dict[str, Course], flag: Flag) -> None:
    for course in courses.values():
        if course.include is False:
            continue
        found = hours_found(entries, course.code)
        if found["L"] != course.L:
            flag("hours_mismatch", f"{course.code} L",
                 f"{course.code} {course.name}: L {found['L']} in timetable, {course.L} in scheme")
        for part in ("T", "P"):
            per_batch = found[part]
            expected = getattr(course, part)
            if any(v != expected for v in per_batch.values()):
                shown = " ".join(f"{b}={v}" for b, v in per_batch.items())
                flag("hours_mismatch", f"{course.code} {part}",
                     f"{course.code} {course.name}: {part} per batch {shown}, scheme {expected}")


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def to_json(tt: ClassTimetable) -> str:
    """Deterministic dump: document order, no timestamps."""
    data = {
        "source": tt.source,
        "generated_by": "python -m ingestion.class_tt",
        "period_times": {f"P{p}": list(t) for p, t in PERIOD_TIMES.items()},
        "lunch_period": LUNCH_PERIOD,
        "tables": [asdict(t) for t in tt.tables],
        "breaks": tt.breaks,
        "entries": [asdict(e) for e in tt.entries],
        "anomalies": [asdict(a) for a in tt.anomalies],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def format_report(tt: ClassTimetable, scheme: TeachingScheme) -> str:
    rule = "=" * 78
    divisions = [t.division for t in tt.tables if t.parsed]
    out = [
        "Chronos - EVEN class timetable, SE and TE (generated by `python -m ingestion.class_tt`)",
        "",
        f"Source: data/real/{tt.source}",
        "One entry per non-empty line of a grid cell. Periods per ROADMAP section 5;",
        "document times like '1.15' are read as 13:15 (12-hour clock, no am/pm).",
        "Faculty initials resolved per division legend only (seed_legends logic).",
        "Full detail: data/generated/class_tt_even.json (gitignored).",
        "",
        rule,
        "1. Tables",
        rule,
    ]
    for t in tt.tables:
        status = "PARSED " if t.parsed else "skipped"
        reason = f" - {t.skip_reason}" if t.skip_reason else ""
        out.append(f"  t{t.index:<2} {status} {t.division or '<no division>'}{reason}")
    out.append("")

    out += [rule, "2. Counts per division", rule]
    for div in divisions:
        mine = [e for e in tt.entries if e.division == div]
        kept = [e for e in mine if not e.excluded]
        types = {k: sum(e.session_type == k for e in kept) for k in SESSION_TYPES}
        out.append(
            f"  {div:<14} entries {len(mine):>3}  in scope {len(kept):>3} "
            f"(lecture {types['lecture']}, tutorial {types['tutorial']}, "
            f"practical {types['practical']})  excluded {len(mine) - len(kept)}"
        )
        reasons: dict[str, int] = {}
        for e in mine:
            if e.excluded:
                reasons[e.exclude_reason or "?"] = reasons.get(e.exclude_reason or "?", 0) + 1
        for reason, n in sorted(reasons.items()):
            out.append(f"      excluded {n:>3} x {reason}")
        out.append(f"      breaks marked: {tt.breaks.get(div)}")
    out.append("")

    out += [rule, "3. Hours: timetable vs teaching_scheme.yaml ('!!' = mismatch)", rule]
    for div in divisions:
        mine = [e for e in tt.entries if e.division == div]
        semester = mine[0].semester if mine else None
        out.append(f"  {div}")
        for course in scheme.semester(semester).courses if semester else ():
            if course.include is False:
                continue
            found = hours_found(mine, course.code)
            marks = {
                "L": found["L"] != course.L,
                "T": any(v != course.T for v in found["T"].values()),
                "P": any(v != course.P for v in found["P"].values()),
            }
            t_shown = "/".join(str(v) for v in found["T"].values())
            p_shown = "/".join(str(v) for v in found["P"].values())
            out.append(
                f"    {course.code:<6} L {found['L']}/{course.L}{' !!' if marks['L'] else '   '}"
                f"  T(A/B/C/D) {t_shown} vs {course.T}{' !!' if marks['T'] else '   '}"
                f"  P(A/B/C/D) {p_shown} vs {course.P}{' !!' if marks['P'] else ''}"
            )
    out.append("")

    out += [rule, "4. Unmatched subjects (not in the division's semester scheme)", rule]
    unmatched: dict[str, list[str]] = {}
    for e in tt.entries:
        if e.exclude_reason and e.exclude_reason.startswith("unmatched") and e.subject_raw:
            unmatched.setdefault(e.subject_raw, []).append(e.division)
    for subject, divs in unmatched.items():
        out.append(f"  {subject!r} x{len(divs)}: {', '.join(dict.fromkeys(divs))}")
    if not unmatched:
        out.append("  none")
    out.append("")

    out += [rule, "5. Faculty initials", rule]
    status_counts: dict[str, int] = {}
    for e in tt.entries:
        if e.faculty_status:
            status_counts[e.faculty_status] = status_counts.get(e.faculty_status, 0) + 1
    out.append(f"  entries by status: {status_counts}")
    for kind in ("ambiguous_initials", "initials_not_in_division_legend"):
        found = [a for a in tt.anomalies if a.kind == kind]
        out.append(f"  {kind} ({len(found)}):" + ("" if found else " none"))
        out.extend(f"    {a.division}: {a.detail}" for a in found)
    out.append("")

    out += [rule, "6. Exclusions (D3) - every excluded entry", rule]
    for e in tt.entries:
        if e.excluded:
            raw = e.raw.replace("\n", " | ")
            out.append(f"  {e.division:<14} {e.where:<26} {raw!r}")
            out.append(f"  {'':<14} -> {e.exclude_reason}")
    out.append("")

    out += [rule, "7. Anomalies", rule]
    kinds = list(dict.fromkeys(a.kind for a in tt.anomalies))
    out.append(f"  total {len(tt.anomalies)}: " + ", ".join(
        f"{k} {sum(a.kind == k for a in tt.anomalies)}" for k in kinds
    ))
    for kind in kinds:
        out.append(f"  [{kind}]")
        for a in tt.anomalies:
            if a.kind == kind:
                out.append(f"    {a.division:<14} {a.where}")
                out.append(f"    {'':<14} {a.detail}")
    out.append("")
    return "\n".join(out)


def build() -> tuple[ClassTimetable, str]:
    scheme = load_scheme()
    tt = parse_class_timetable(scheme=scheme)
    return tt, format_report(tt, scheme)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="report path")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="JSON dump path")
    args = parser.parse_args(argv)
    tt, report = build()
    args.out.write_text(report, encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(to_json(tt), encoding="utf-8")
    print(f"wrote {args.out}\nwrote {args.json}")


if __name__ == "__main__":
    main()
