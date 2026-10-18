"""Parse the EVEN faculty individual timetable and check every load line (ROADMAP S7).

Pure parsing: reads ``data/real/Faculty Individual timetable Even 2025-26.docx``.
Each page is one faculty member: a header paragraph ending in the name
("... Term: II  Prasenjit Bhavathankar"), one grid, then the printed load line
("6T+ 8P =14"). Cells read ``SUBJECT / [BATCH /] DIVISION / ROOM`` and print no
initials, because the member is the page. The page name is matched to the
41-member list (D11) by spelling only (``initials_legend.name_key``).

The printed line is compared with a load computed from the class and lab
timetables, never from the page itself:

- a lecture counts its periods once per division it is printed for (the
  department's own convention: three SE A & B lectures print as 6T);
- a tutorial counts 1 h per division (D23);
- a practical counts 2 h per batch taught (D11);
- frozen items (D24, D26) seen in several division grids count once per slot;
- a lab-timetable cell with no class-timetable line (BE, M.Tech, MDM) counts
  its periods as practical hours; an exam block counts nothing.

Initials are attributed only where they resolve (division legend, or D25 for
SRD), so an unresolved initial leaves its hours unattributed and the member's
line mismatches. That is reported, never patched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml.etree import _Element

from ingestion.class_tt import (
    DAYS,
    SUBJECT_ALIASES,
    ClassTimetable,
    FacultyIndex,
    subject_key,
    time_rows,
)
from ingestion.docx_reader import logical_cells, open_document, paragraph_text, walk_body
from ingestion.initials_legend import name_key, normalise_whitespace
from ingestion.lab_tt import (
    NEEDS_HUMAN,
    Finding,
    LabTimetable,
    attributed,
    class_resolution,
)
from ingestion.survey import REAL_DIR

FACULTY_FILE = REAL_DIR / "Faculty Individual timetable Even 2025-26.docx"
#: D11: average 16 h/week, a soft target; above it is flagged.
LOAD_TARGET = 16

_NAME = re.compile(r"Academic Year:.*Term:\s*II\b\s*(?P<name>.*)$")
_LOAD = re.compile(r"(?:(?P<T>\d+)\s*T)?\s*\+?\s*(?:(?P<P>\d+)\s*P)?\s*(?:=\s*(?P<total>\d+))?")
_DAY_OFF = re.compile(r"PHD\s*DAY\s*OFF", re.IGNORECASE)


@dataclass
class FacultySession:
    table: int
    row: int
    col: int
    day: str
    periods: list[int]
    #: Cell text, non-empty lines joined with ' '.
    raw: str
    subject_raw: str


@dataclass
class FacultyPage:
    table: int
    name_raw: str
    #: The 41-list spelling of the name, or None if no spelling matches.
    member: str | None
    load_raw: str | None = None
    theory: int | None = None
    practical: int | None = None
    total: int | None = None
    sessions: list[FacultySession] = field(default_factory=list)
    days_off: list[str] = field(default_factory=list)

    @property
    def printed_total(self) -> int | None:
        if self.total is not None:
            return self.total
        if self.theory is None and self.practical is None:
            return None
        return (self.theory or 0) + (self.practical or 0)


@dataclass
class Load:
    """Hours per week computed from the class and lab timetables."""

    lecture: int = 0
    tutorial: int = 0
    practical: int = 0
    frozen_theory: int = 0
    frozen_practical: int = 0
    #: Lab-timetable cells with no class-timetable line (BE, M.Tech, MDM).
    lab_only: int = 0

    @property
    def theory(self) -> int:
        return self.lecture + self.tutorial + self.frozen_theory

    @property
    def practical_total(self) -> int:
        return self.practical + self.frozen_practical + self.lab_only

    @property
    def total(self) -> int:
        return self.theory + self.practical_total

    def describe(self) -> str:
        return (
            f"{self.theory}T+{self.practical_total}P={self.total} (lecture {self.lecture}, "
            f"tutorial {self.tutorial}, practical {self.practical}, frozen {self.frozen_theory}T"
            f"+{self.frozen_practical}P, lab-timetable only {self.lab_only}P)"
        )


@dataclass
class FacultyTimetable:
    source: str
    pages: list[FacultyPage] = field(default_factory=list)
    loads: dict[str, Load] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def parse_load_line(text: str) -> tuple[int | None, int | None, int | None] | None:
    """``(T, P, total)`` from '6T+ 8P =14', '18P = 18', '2T'; None if not a load line."""
    match = _LOAD.fullmatch(normalise_whitespace(text))
    if match is None or (match["T"] is None and match["P"] is None):
        return None
    values = (match["T"], match["P"], match["total"])
    return tuple(int(v) if v is not None else None for v in values)


def parse_faculty_pages(
    path: Path, faculty: FacultyIndex
) -> tuple[list[FacultyPage], list[Finding]]:
    members = {name_key(n): n for n in faculty.ce_faculty}
    pages: list[FacultyPage] = []
    findings: list[Finding] = []
    name: str | None = None
    index = 0
    for kind, element in walk_body(open_document(path)):
        if kind == "table":
            if name is None:
                findings.append(Finding("page_without_name", f"t{index}",
                                        "no 'Academic Year ... Term: II <name>' line", NEEDS_HUMAN))
            page = FacultyPage(index, name or f"<t{index}>", members.get(name_key(name or "")))
            _parse_grid(page, element, findings)
            pages.append(page)
            index += 1
            name = None
            continue
        # Line by line: one paragraph holds "18P=18" and the next page's first line.
        for line in paragraph_text(element).split("\n"):
            text = normalise_whitespace(line)
            if match := _NAME.search(text):
                name = match["name"].strip()
            elif (load := parse_load_line(text)) and pages and pages[-1].load_raw is None:
                pages[-1].load_raw = text
                pages[-1].theory, pages[-1].practical, pages[-1].total = load
    return pages, findings


def _parse_grid(page: FacultyPage, table: _Element, findings: list[Finding]) -> None:
    where = f"t{page.table} {page.name_raw}"
    cells, _, _ = logical_cells(table)
    days = {c.col: normalise_whitespace(c.text) for c in cells if c.row == 0 and c.col > 0}
    if [days[k] for k in sorted(days)] != list(DAYS):
        findings.append(Finding("grid_shape", where, f"day header reads {list(days.values())}",
                                NEEDS_HUMAN))
    row_period, _, off_grid = time_rows(cells)
    used_rows: dict[int, list[str]] = {}
    for c in cells:
        if not c.row or not c.col or not c.text.strip():
            continue
        lines = [normalise_whitespace(line) for line in c.text.split("\n") if line.strip()]
        text = " ".join(lines)
        letters = "".join(text.split()).upper()
        if re.fullmatch(r"(SHORT-?)?BREAK", letters):
            continue
        day = days.get(c.col, f"column {c.col}")
        rows = range(c.row, c.row + c.row_span)
        if _DAY_OFF.search(text):
            if day not in page.days_off:
                page.days_off.append(day)
            continue
        periods = list(dict.fromkeys(row_period[r] for r in rows if r in row_period))
        page.sessions.append(FacultySession(
            page.table, c.row, c.col, day, periods, text, normalise_whitespace(text.split("/")[0])
        ))
        for r in rows:
            if r not in row_period:
                used_rows.setdefault(r, []).append(f"{day[:3]} {text!r}")
    for r, raw in off_grid:
        if r in used_rows:
            findings.append(Finding(
                "time_off_grid", f"{where} r{r}",
                f"time {raw!r} fits no ROADMAP §5 period; cells on it: {'; '.join(used_rows[r])}",
                NEEDS_HUMAN,
            ))
    if page.days_off:
        findings.append(Finding(
            "faculty_day_off", where,
            f"{page.name_raw} is marked 'PHD Day OFF' on {', '.join(page.days_off)}: every "
            "period of that day is unavailable",
            "D36",
        ))


# --------------------------------------------------------------------------- #
# Loads (D11, D23)
# --------------------------------------------------------------------------- #


def compute_loads(
    class_tt: ClassTimetable, lab: LabTimetable, faculty: FacultyIndex
) -> dict[str, Load]:
    """Weekly hours per member from the class and lab timetables (see module docstring)."""
    loads: dict[str, Load] = {}
    frozen_seen: set[tuple] = set()
    for e in class_tt.entries:
        if e.subject_raw is None:
            continue  # a label-only block (MDM, HSS, ...) names no teacher
        member = attributed(*class_resolution(e, faculty))
        if member is None:
            continue
        load = loads.setdefault(member, Load())
        if not e.excluded:
            if e.session_type == "lecture":
                load.lecture += e.duration
            elif e.session_type == "tutorial":
                load.tutorial += 1  # D23: once per division
            elif e.session_type == "practical":
                load.practical += 2  # D11: 2 h per batch
            continue
        key = (e.day, tuple(e.periods), subject_key(e.subject_raw), e.elective_group,
               e.faculty_initials_raw)
        if key in frozen_seen:
            continue
        frozen_seen.add(key)
        if e.elective_group:
            load.frozen_practical += 2  # D11
        else:
            load.frozen_theory += e.duration
    for le in lab.entries:
        if le.matched or le.kind == "exam":
            continue
        member = attributed(le.faculty_status, le.faculty_candidates)
        if member is not None:
            loads.setdefault(member, Load()).lab_only += len(le.teaching_periods)
    return loads


def _page_extras(page: FacultyPage, known: set[str]) -> list[str]:
    """Subjects on the page that neither SE/TE timetable carries (FE, BE, M.Tech ...)."""
    return list(dict.fromkeys(
        s.subject_raw for s in page.sessions if subject_key(s.subject_raw) not in known
    ))


def parse_faculty_timetable(
    class_tt: ClassTimetable,
    lab: LabTimetable,
    faculty: FacultyIndex,
    path: Path = FACULTY_FILE,
) -> FacultyTimetable:
    out = FacultyTimetable(path.name)
    out.pages, out.findings = parse_faculty_pages(path, faculty)
    out.loads = compute_loads(class_tt, lab, faculty)
    known = set(SUBJECT_ALIASES) | {
        subject_key(e.subject_raw) for e in class_tt.entries if e.subject_raw
    } | {subject_key(le.subject_raw) for le in lab.entries if le.subject_raw}

    def flag(category: str, where: str, message: str, resolution: str = NEEDS_HUMAN) -> None:
        out.findings.append(Finding(category, where, message, resolution))

    paged: set[str] = set()
    for page in out.pages:
        where = f"t{page.table} {page.name_raw}"
        if page.member is None:
            flag("page_name_unmatched", where,
                 f"{page.name_raw!r} matches no spelling in the 41-member faculty list")
            continue
        paged.add(page.member)
        load = out.loads.get(page.member, Load())
        if page.load_raw is None:
            flag("missing_workload", where, f"{page.name_raw}: no load line on the page")
        else:
            arithmetic = (page.theory or 0) + (page.practical or 0)
            if page.total is not None and page.total != arithmetic:
                flag("load_line_arithmetic", where,
                     f"{page.load_raw!r}: {page.theory}T + {page.practical}P is {arithmetic}, "
                     f"printed {page.total}")
            if ((page.theory or 0), (page.practical or 0)) != (load.theory, load.practical_total):
                extras = _page_extras(page, known)
                also = f"; the page also lists {', '.join(extras)}" if extras else ""
                flag("load_mismatch", where,
                     f"printed {page.load_raw!r}, computed {load.describe()}{also}")
        printed = page.printed_total
        if (printed or 0) > LOAD_TARGET or load.total > LOAD_TARGET:
            flag("load_above_16", where,
                 f"{page.member}: printed {printed}, computed {load.total} h/week; above the "
                 f"{LOAD_TARGET} h soft target", "D11")
    for member, load in sorted(out.loads.items()):
        if member in paged:
            continue
        flag("no_faculty_page", member,
             f"{member} teaches {load.describe()} in the class/lab timetables but has no page")
        if load.total > LOAD_TARGET:
            flag("load_above_16", member,
                 f"{member}: computed {load.total} h/week; above the {LOAD_TARGET} h soft target",
                 "D11")
    return out
