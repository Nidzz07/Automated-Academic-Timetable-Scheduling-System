"""Extract the "Initials / Name of the Faculty" legends from the class timetables.

Each division grid in the class timetable files is followed by one or more
legend tables mapping the initials used in its cells to faculty names. This
module reads every legend, keeps every occurrence, and *reports* where
legends disagree. It never picks a winner: resolving an initial to a Faculty
row is a later, human-confirmed step (CONTEXT.md section 3.5).

Legend shape
------------
A legend is recognised by its header row, not by its width. Most are two
columns (one pair per row), but the ODD BE legend is six columns holding three
initials/name pairs side by side. The pair-width is taken from each legend's
own column count and every row is read in groups of two columns.

Why every occurrence is kept
----------------------------
Initials are not globally unique in this department. The same initials name
different people in different legends (``SD`` is Sonali Dudhihalli in the SE
legends and Surekha Dholay in the TE ones), and one legend can even list the
same initials twice. A flat ``initials -> name`` dict would silently keep
whichever legend was read last. The unit of truth is therefore the pair
``(legend, initials)``, and :func:`group_by_initials` exposes every name each
initials string was given, with its sources.

Run from the repo root::

    python -m ingestion.initials_legend            # writes the report
    python -m ingestion.initials_legend --stdout   # print instead
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ingestion.docx_reader import logical_grid, open_document, walk_body
from ingestion.seed_reference import FACULTY_INITIALS, parse_faculty_subjects
from ingestion.survey import REAL_DIR, survey_file

CLASS_FILES = (
    "CE_Class_Time_Table-EVEN_sem_25-26.docx",
    "CE_Class_Time_Table-ODD_sem_25-26.docx",
)
DEFAULT_REPORT = Path(__file__).resolve().parent / "initials_legend_report.txt"

#: Initials whose resolution the Phase 2 brief asked about by name.
QUERIED_INITIALS = ("AVN", "SND", "AVS", "SK", "SD", "TP", "AT", "AsT")

Status = Literal["AGREE", "VARIANT", "CONFLICT"]


# --------------------------------------------------------------------------- #
# Reading one legend
# --------------------------------------------------------------------------- #


def normalise_whitespace(text: str) -> str:
    """Collapse every internal run of whitespace to one space, and trim.

    A soft line break typed inside a Word cell reaches us as a newline in the
    middle of a name ("Kail\\nas Devadkar"); a padded cell reaches us as
    leading spaces. Both become single spaces here. The raw cell text is kept
    separately on :class:`LegendEntry`, so nothing is lost by normalising.
    """
    return " ".join(text.split())


_clean = normalise_whitespace


def legend_pairs(grid: list[list[str]]) -> int | None:
    """Pairs per row if ``grid`` is a legend, else ``None``.

    A legend's header row alternates ``Initials`` / ``Name of ...`` across its
    full width, so the width must be even and every pair must match.
    """
    if not grid or not grid[0] or len(grid[0]) % 2:
        return None
    header = [_clean(cell).casefold() for cell in grid[0]]
    for i in range(0, len(header), 2):
        if header[i] != "initials" or not header[i + 1].startswith("name of"):
            return None
    return len(header) // 2


@dataclass(frozen=True)
class LegendEntry:
    initials: str
    #: The name as written, honorific included, whitespace normalised.
    name: str
    row: int
    pair: int
    #: The name cell verbatim - padding, line breaks and all. Provenance only;
    #: every comparison uses ``name``.
    raw_name: str


def read_legend(grid: list[list[str]]) -> tuple[list[LegendEntry], list[str]]:
    """Read a legend row by row, pair by pair (row-major).

    Returns ``(entries, problems)``. A pair with both cells blank is padding
    and skipped; a pair with only one cell filled is reported as a problem,
    not guessed at.
    """
    pairs = legend_pairs(grid)
    if pairs is None:
        raise ValueError("not a legend table")
    entries: list[LegendEntry] = []
    problems: list[str] = []
    for r, row in enumerate(grid[1:], start=1):
        for p in range(pairs):
            initials, name = _clean(row[2 * p]), _clean(row[2 * p + 1])
            if not initials and not name:
                continue
            if not initials or not name:
                problems.append(f"row {r} pair {p}: half-filled pair {initials!r} / {name!r}")
                continue
            entries.append(LegendEntry(initials, name, r, p, row[2 * p + 1]))
    return entries, problems


# --------------------------------------------------------------------------- #
# Reading every legend in a file
# --------------------------------------------------------------------------- #

_DIVISION = re.compile(r"Semester\s*-\s*[IVX]+\s+(?P<division>.+)$")


def _division(header: str | None) -> str:
    """The division part of a grid header, or the whole header if unmatched."""
    if header is None:
        return "<no header>"
    match = _DIVISION.search(header)
    return match["division"] if match else header


@dataclass(frozen=True)
class Legend:
    source: str
    table_index: int
    #: Division of the nearest preceding *grid*. Not the nearest paragraph:
    #: EVEN table 1's nearest paragraph is a "Note 1: Law-II ..." line.
    division: str
    pairs: int
    entries: list[LegendEntry]
    problems: list[str]
    #: Full header of that same grid ("Academic Year: 2025-2026 Term: II
    #: Semester - IV SE-Comp A"), from which the legend's scope is derived.
    grid_header: str | None = None


def extract_legends(path: Path) -> list[Legend]:
    """Every legend table in one class timetable file, in document order."""
    headers = [t.header for t in survey_file(path).tables]
    tables = [el for kind, el in walk_body(open_document(path)) if kind == "table"]
    legends: list[Legend] = []
    owner = "<before first grid>"
    owner_header: str | None = None
    for index, table in enumerate(tables):
        grid = logical_grid(table)
        pairs = legend_pairs(grid)
        if pairs is None:
            owner, owner_header = _division(headers[index]), headers[index]
            continue
        entries, problems = read_legend(grid)
        legends.append(Legend(path.name, index, owner, pairs, entries, problems, owner_header))
    return legends


# --------------------------------------------------------------------------- #
# Comparing names
# --------------------------------------------------------------------------- #

# The title must end in "." / "," or a space, so "Drishti" keeps its "Dr".
# "Dr," is a real spelling in the source ("Dr, Anant Nimkar").
_TITLE = re.compile(r"^(?:dr|prof|mrs|mr|ms)(?:[.,]\s*|\s+)", re.IGNORECASE)


def strip_title(name: str) -> str:
    """``name`` without its leading titles (Mr. Ms. Mrs. Prof. Dr. Dr,).

    **For matching only.** Stored names keep their titles as written; this
    exists so "Prof. Asma Tambe" and "Asma Tambe" can be recognised as the
    same spelling. Repeated titles are all removed ("Prof. Dr. X" -> "X").
    """
    key = normalise_whitespace(name)
    while True:
        stripped = _TITLE.sub("", key)
        if stripped == key:
            return key
        key = stripped


def name_key(name: str) -> str:
    """Comparison form: titles, dots and commas dropped, casefolded.

    Used only to decide whether two spellings are *textually* the same. It
    does not decide that two different keys are the same person.
    """
    return " ".join(strip_title(name).replace(".", " ").replace(",", " ").split()).casefold()


def surname(name: str) -> str:
    return name_key(name).split(" ")[-1] if name_key(name) else ""


def classify(names: list[str]) -> Status:
    """AGREE - one spelling; VARIANT - several, one surname; CONFLICT - else.

    VARIANT is a flag, not a verdict: "Jostna" vs "Jotsna Bhagat" is almost
    certainly a typo, but a human still confirms it.
    """
    keys = {name_key(n) for n in names}
    if len(keys) == 1:
        return "AGREE"
    if len({k.split(" ")[-1] for k in keys}) == 1:
        return "VARIANT"
    return "CONFLICT"


@dataclass(frozen=True)
class Occurrence:
    name: str
    source: str
    table_index: int
    division: str


def group_by_initials(legends: list[Legend]) -> dict[str, list[Occurrence]]:
    """``initials -> every occurrence``, initials compared case-sensitively.

    ``AsT`` (Asma Tambe) and ``AT`` (Anuj Tawari) are different people, so
    case is significant.
    """
    grouped: dict[str, list[Occurrence]] = {}
    for legend in legends:
        for e in legend.entries:
            grouped.setdefault(e.initials, []).append(
                Occurrence(e.name, legend.source, legend.table_index, legend.division)
            )
    return grouped


def duplicates_within_legend(legend: Legend) -> dict[str, list[str]]:
    """Initials listed more than once in a single legend, with their names."""
    seen: dict[str, list[str]] = {}
    for e in legend.entries:
        seen.setdefault(e.initials, []).append(e.name)
    return {k: v for k, v in seen.items() if len(v) > 1}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def _short(source: str) -> str:
    return "EVEN" if "EVEN" in source else "ODD" if "ODD" in source else source


def _where(o: Occurrence) -> str:
    return f"{_short(o.source)} t{o.table_index} {o.division}"


def _distinct_names(occurrences: list[Occurrence]) -> dict[str, list[Occurrence]]:
    """Group occurrences by exact written name, first appearance first."""
    by_name: dict[str, list[Occurrence]] = {}
    for o in occurrences:
        by_name.setdefault(o.name, []).append(o)
    return by_name


def _sheet_matches(name: str, sheet_names: list[str]) -> str:
    key = name_key(name)
    exact = [n for n in sheet_names if name_key(n) == key]
    if exact:
        return f"in faculty sheet as {exact[0]!r}"
    same_surname = [n for n in sheet_names if surname(n) == surname(name)]
    if same_surname:
        return f"faculty sheet has same surname only: {', '.join(map(repr, same_surname))}"
    return "NOT in Faculty___Subjects.xlsx"


def format_report(legends: list[Legend], sheet_names: list[str]) -> str:
    grouped = group_by_initials(legends)
    order = sorted(grouped, key=lambda k: (k.casefold(), k))
    status = {k: classify([o.name for o in grouped[k]]) for k in grouped}

    out = [
        "Chronos - faculty initials legends (generated by `python -m ingestion.initials_legend`)",
        "",
        "Source: every 'Initials / Name of the Faculty' table in the two class timetable",
        "files. Names are as written, whitespace normalised (the raw cell text is kept",
        "separately). Nothing here is resolved to a Faculty row; disagreements are",
        "listed, not settled.",
        "",
        "Status: AGREE    = one spelling everywhere",
        "        VARIANT  = several spellings, same surname (likely typo/abbreviation - confirm)",
        "        CONFLICT = different surnames: the same initials name different people",
        "",
        "=" * 78,
        "1. Legend tables",
        "=" * 78,
    ]
    for source in dict.fromkeys(lg.source for lg in legends):
        in_file = [lg for lg in legends if lg.source == source]
        out.append(f"{source}: {len(in_file)} legend tables")
        for lg in in_file:
            out.append(
                f"  t{lg.table_index:<2} {lg.division:<18} pairs/row {lg.pairs}  "
                f"entries {len(lg.entries)}"
            )
            out.extend(f"      problem: {p}" for p in lg.problems)
    total = sum(len(lg.entries) for lg in legends)
    out.append(f"Total entries: {total}; distinct initials: {len(grouped)}")
    rebroken = [(lg, e) for lg in legends for e in lg.entries if e.raw_name.strip() != e.name]
    out.append(
        "Names whose internal whitespace was normalised (raw != name beyond trimming): "
        f"{len(rebroken) or 'none'}"
    )
    out.extend(
        f"  {_short(lg.source)} t{lg.table_index} {e.initials}: {e.raw_name!r} -> {e.name!r}"
        for lg, e in rebroken
    )
    out.append("")

    out += ["=" * 78, "2. Full mapping (initials -> every name given, with sources)", "=" * 78]
    for k in order:
        out.append(f"{k:<4} {status[k]}")
        for name, occ in _distinct_names(grouped[k]).items():
            out.append(f"       {name!r}")
            out.append(f"           {'; '.join(_where(o) for o in occ)}")
    out.append("")

    out += ["=" * 78, "3. Flags", "=" * 78]
    for label in ("CONFLICT", "VARIANT"):
        flagged = [k for k in order if status[k] == label]
        out.append(f"{label} ({len(flagged)}): {', '.join(flagged) or 'none'}")
    out.append("Initials listed twice in one legend:")
    dupes = [(lg, d) for lg in legends if (d := duplicates_within_legend(lg))]
    for lg, d in dupes:
        for k, names in d.items():
            out.append(f"  {_short(lg.source)} t{lg.table_index} {lg.division}: {k} -> {names}")
    if not dupes:
        out.append("  none")
    out.append("")

    out += ["=" * 78, "4. Cross-check against the 8 seeded initials (seed_reference.py)", "=" * 78]
    for k, seeded in FACULTY_INITIALS.items():
        names = [o.name for o in grouped.get(k, [])]
        if not names:
            out.append(f"{k:<4} seeded {seeded!r}: NOT FOUND in any legend")
            continue
        verdict = classify([seeded, *names])
        written = ", ".join(repr(n) for n in _distinct_names(grouped[k]))
        out.append(f"{k:<4} seeded {seeded!r} vs legend {written}: {verdict}")
    out.append("")

    out += ["=" * 78, "5. Queried initials", "=" * 78]
    for k in QUERIED_INITIALS:
        if k not in grouped:
            out.append(f"{k:<4} NOT FOUND in any legend")
            continue
        out.append(f"{k:<4} {status[k]}")
        for name, occ in _distinct_names(grouped[k]).items():
            divisions = sorted({f"{_short(o.source)} {o.division}" for o in occ})
            out.append(f"       {name!r} - {_sheet_matches(name, sheet_names)}")
            out.append(f"           legends: {', '.join(divisions)}")
    out.append("")

    out += [
        "=" * 78,
        "6. Legend names without an exact match in Faculty___Subjects.xlsx",
        "=" * 78,
    ]
    for k in order:
        for name in _distinct_names(grouped[k]):
            match = _sheet_matches(name, sheet_names)
            if not match.startswith("in faculty sheet"):
                out.append(f"{k:<4} {name!r}: {match}")
    out.append("")
    return "\n".join(out)


def build_report() -> str:
    legends = [lg for name in CLASS_FILES for lg in extract_legends(REAL_DIR / name)]
    sheet_names = [f.full_name for f in parse_faculty_subjects()]
    return format_report(legends, sheet_names)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="report path")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args(argv)
    report = build_report()
    if args.stdout:
        print(report)
    else:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
