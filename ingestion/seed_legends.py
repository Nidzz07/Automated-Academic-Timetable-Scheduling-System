"""Seed faculty initials from the class-timetable legends, scoped per division.

Runs after :func:`ingestion.seed_reference.seed_reference_data`. It writes:

1. the Programme / Semester / Division rows that own a legend - just enough
   hierarchy for a ``faculty_initials`` row to name its scope, read from the
   owning grid's header ("Academic Year: 2025-2026 Term: II Semester - IV
   SE-Comp A"). Batches, sessions and everything else stay with Phase 2;
2. a Faculty row, ``source=legend`` and with **no qualifications**, for each
   person a legend names who is in neither spreadsheet (:data:`LEGEND_ONLY_FACULTY`);
3. a ``faculty_alias`` row for every legend spelling of an existing person
   that differs from their ``full_name`` beyond titles and punctuation;
4. one ``faculty_initials`` row per (faculty, initials, semester, division).
   Where one scope gives the same initials to two people (ODD BE's ``SK``),
   **both** rows are written with ``is_ambiguous=True``. Nothing picks one.

Resolution is deliberately explicit. A legend name resolves to a Faculty row
only by (a) matching its full name once titles, dots, commas and case are set
aside (:func:`ingestion.initials_legend.name_key`), or (b) an entry in one of
the two hand-reviewed tables below. Anything else stops the seed with
:class:`SeedBlocked` - no fuzzy matching, no surname guessing, because a wrong
match silently hands one person's teaching load to another.

As in :mod:`ingestion.seed_reference`, the ``resolve_*`` / ``legend_*``
functions are pure and need no database.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    Department,
    Division,
    Faculty,
    FacultyAlias,
    FacultyInitials,
    FacultySource,
    MappingSource,
    Programme,
    Semester,
    TermCode,
)
from ingestion.initials_legend import CLASS_FILES, Legend, extract_legends, name_key
from ingestion.seed_reference import SeedBlocked, seed_institute_and_department
from ingestion.survey import REAL_DIR

# ---------------------------------------------------------------------------
# hand-reviewed resolution tables
# ---------------------------------------------------------------------------

#: A legend spells an existing person's name differently from the spreadsheet.
#: ``name_key(legend spelling) -> name_key(existing full_name)``. Each pair was
#: checked against initials_legend_report.txt: same initials, same surname
#: stem, and the spreadsheet has no other candidate.
SPELLING_VARIANTS: dict[str, str] = {
    "c r gajbhiye": "c r gajbiye",  # CRG, EVEN SE
    "vandana wekhende": "vandana wekhande",  # VW, EVEN BE
    "vaishnavi rathod": "vaishnavee rathod",  # VR, EVEN TE / ODD TE, BE
    "jotsna bhagat": "jostna bhagat",  # JB, ODD SE (EVEN legends spell it Jostna)
    "sanjukta jena": "sanjyuktarani jena",  # SJ, ODD SE (EVEN legends: Sanjyuktarani)
}

#: A legend abbreviates a name that is written in full elsewhere. Same rule:
#: same initials, same surname (or its initial), exactly one candidate.
ABBREVIATIONS: dict[str, str] = {
    "a a godbole": "anand godbole",  # AAG, EVEN TE
    "amey nile": "amey ganesh nile",  # AGN, EVEN SE / TE
    "d d ambawade": "dayanand ambawade",  # DDA, EVEN M.Tech
    "p b bhavathankar": "prasenjit bhavathankar",  # PBB, EVEN SE
    # SD, EVEN SE-Comp C only. The SE-Comp B and D legends of the same term
    # give SD as Sonali Dudhihalli in full; Surekha Dholay, the other SD, is
    # only ever named in TE legends.
    "sonali d": "sonali dudhihalli",
}

#: People named in a legend but in neither spreadsheet. Each becomes a Faculty
#: row with ``source=legend``. Deepak Nair is *not* here: he already exists,
#: as a manual row. Any other unresolved legend name stops the seed.
LEGEND_ONLY_FACULTY: frozenset[str] = frozenset(
    {
        "asma tambe",  # AsT
        "aman yadav",  # AY
        "govind gaundalkar",  # GG
        "shaily goyal",  # SG
        "vipul kushwah",  # VK
        "suman m",  # SM (EVEN SE-Comp B; not Sudeep Mali, the TE SM)
        "suhas kakade",  # SK (ODD BE, alongside Swapnali Kurhade)
        "sonali dudhihalli",  # SD (EVEN SE)
    }
)

# ---------------------------------------------------------------------------
# legend scope
# ---------------------------------------------------------------------------

_HEADER = re.compile(
    r"Academic Year:\s*(?P<year>\S+)\s+Term:\s*(?P<term>[IVX]+)\s+"
    r"Semester\s*-\s*(?P<semester>[IVX]+)\s+(?P<division>.+)$"
)
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
#: "Term: I" is the ODD term and "Term: II" the EVEN one; cross-checked
#: against the file name so a mislabelled header stops the seed.
_TERM = {"I": TermCode.ODD, "II": TermCode.EVEN}
#: Division-label prefix -> programme. Codes only; no expansion is invented.
_PROGRAMME = {"SE": "B.Tech", "TE": "B.Tech", "BE": "B.Tech", "M.Tech": "M.Tech"}


@dataclass(frozen=True)
class LegendScope:
    """The (semester, division) a legend belongs to, as its grid header says."""

    academic_year: str
    term: TermCode
    semester_number: int
    programme: str
    #: Exactly as printed - 'TE Comp- B', 'BE Comp- A & B'.
    division: str


def legend_scope(legend: Legend) -> LegendScope:
    """Parse the owning grid's header. Raises rather than guessing."""
    match = _HEADER.search(legend.grid_header or "")
    if match is None:
        raise SeedBlocked(
            f"{legend.source} t{legend.table_index}: cannot read a scope from the "
            f"owning grid header {legend.grid_header!r}"
        )
    term = _TERM[match["term"]]
    if term.value not in legend.source:
        raise SeedBlocked(
            f"{legend.source} t{legend.table_index}: header says Term {match['term']} "
            f"({term.value}) but the file is not the {term.value} timetable"
        )
    division = match["division"].strip()
    programme = next(
        (prog for prefix, prog in _PROGRAMME.items() if division.startswith(prefix)), None
    )
    if programme is None:
        raise SeedBlocked(f"no programme known for division label {division!r}")
    return LegendScope(
        academic_year=match["year"],
        term=term,
        semester_number=_ROMAN[match["semester"]],
        programme=programme,
        division=division,
    )


def real_legends() -> list[Legend]:
    return [lg for name in CLASS_FILES for lg in extract_legends(REAL_DIR / name)]


# ---------------------------------------------------------------------------
# name resolution - pure
# ---------------------------------------------------------------------------


@dataclass
class Resolution:
    """How every distinct legend spelling resolves, and why."""

    #: legend spelling -> name_key of the person it denotes
    target: dict[str, str] = field(default_factory=dict)
    #: legend spelling -> existing full_name, matched once titles are set aside
    exact: dict[str, str] = field(default_factory=dict)
    #: legend spelling -> full_name, via SPELLING_VARIANTS
    spelling_variants: dict[str, str] = field(default_factory=dict)
    #: legend spelling -> full_name, via ABBREVIATIONS
    abbreviations: dict[str, str] = field(default_factory=dict)
    #: name_key -> full_name chosen for a new, legend-only Faculty row
    new_faculty: dict[str, str] = field(default_factory=dict)
    #: legend spellings that resolve nowhere - must be empty to seed
    unresolved: list[str] = field(default_factory=list)
    #: name_key -> full_name, for every person some legend spelling denotes
    canonical: dict[str, str] = field(default_factory=dict)


def _preferred_spelling(spellings: list[str]) -> str:
    """Most frequent spelling; ties go to the one written first."""
    counts = Counter(spellings)
    return max(dict.fromkeys(spellings), key=lambda s: counts[s])


def resolve_legend_names(legends: list[Legend], existing_names: list[str]) -> Resolution:
    """Resolve every legend spelling against existing Faculty full names.

    ``existing_names`` is the full_name of every Faculty row already seeded.
    A new person's full_name is their most frequent legend spelling, titles
    kept as written; every other spelling of them becomes an alias.
    """
    by_key: dict[str, str] = {}
    for name in existing_names:
        if name_key(name) in by_key:
            raise SeedBlocked(f"two Faculty rows share the name key {name_key(name)!r}")
        by_key[name_key(name)] = name

    written = [e.name for lg in legends for e in lg.entries]
    new_spellings: dict[str, list[str]] = {}
    out = Resolution()
    for spelling in dict.fromkeys(written):
        key = name_key(spelling)
        if key in by_key:
            out.target[spelling] = key
            out.exact[spelling] = by_key[key]
        elif key in SPELLING_VARIANTS or key in ABBREVIATIONS:
            target = SPELLING_VARIANTS.get(key) or ABBREVIATIONS[key]
            out.target[spelling] = target
            bucket = out.spelling_variants if key in SPELLING_VARIANTS else out.abbreviations
            bucket[spelling] = target  # a key for now; named below
        elif key in LEGEND_ONLY_FACULTY:
            out.target[spelling] = key
        else:
            out.unresolved.append(spelling)

    # Full spellings of each new person, in document order, repeats counted.
    # An abbreviation ("Prof. Sonali D.") is never a candidate full_name.
    for spelling in written:
        key = name_key(spelling)
        if key in LEGEND_ONLY_FACULTY and key not in by_key:
            new_spellings.setdefault(key, []).append(spelling)
    out.new_faculty = {
        key: _preferred_spelling(spellings) for key, spellings in new_spellings.items()
    }

    names = {**by_key, **out.new_faculty}
    out.canonical = {t: names[t] for t in out.target.values() if t in names}
    for bucket in (out.spelling_variants, out.abbreviations):
        for spelling, target in bucket.items():
            if target not in names:
                out.unresolved.append(spelling)
            else:
                bucket[spelling] = names[target]
    return out


def aliases(resolution: Resolution) -> dict[str, str]:
    """Legend spelling -> canonical full_name, for spellings that differ.

    A spelling that differs only in titles, dots, commas or case ("Dr, Anant
    Nimkar" for "Anant Nimkar") is the same spelling and gets no alias.
    """
    return {
        spelling: resolution.canonical[key]
        for spelling, key in resolution.target.items()
        if name_key(spelling) != key
    }


def initials_by_scope(
    legends: list[Legend], resolution: Resolution
) -> dict[LegendScope, dict[str, set[str]]]:
    """``scope -> initials -> {name_key of each person}``.

    Two legend tables for one division (EVEN TE Comp - D, ODD SE-Comp B) merge
    into one scope. A set with more than one member is an ambiguous initial.
    """
    scoped: dict[LegendScope, dict[str, set[str]]] = {}
    for lg in legends:
        bucket = scoped.setdefault(legend_scope(lg), {})
        for e in lg.entries:
            bucket.setdefault(e.initials, set()).add(resolution.target[e.name])
    return scoped


def ambiguous_initials(
    scoped: dict[LegendScope, dict[str, set[str]]],
) -> dict[LegendScope, dict[str, set[str]]]:
    return {
        scope: amb
        for scope, by_initials in scoped.items()
        if (amb := {k: v for k, v in by_initials.items() if len(v) > 1})
    }


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------


def seed_division(session: Session, department: Department, scope: LegendScope) -> Division:
    """Programme, Semester and Division for one legend scope, reused if present."""
    programme = session.scalar(
        select(Programme).where(
            Programme.department_id == department.id, Programme.code == scope.programme
        )
    )
    if programme is None:
        programme = Programme(
            department_id=department.id, code=scope.programme, name=scope.programme
        )
        session.add(programme)
        session.flush()

    semester = session.scalar(
        select(Semester).where(
            Semester.programme_id == programme.id,
            Semester.number == scope.semester_number,
            Semester.academic_year == scope.academic_year,
        )
    )
    if semester is None:
        semester = Semester(
            department_id=department.id,
            programme_id=programme.id,
            number=scope.semester_number,
            term_code=scope.term,
            academic_year=scope.academic_year,
        )
        session.add(semester)
        session.flush()
    elif semester.term_code is not scope.term:
        raise SeedBlocked(
            f"semester {scope.semester_number} of {scope.academic_year} is stored as "
            f"{semester.term_code.value} but a legend header says {scope.term.value}"
        )

    division = session.scalar(
        select(Division).where(
            Division.semester_id == semester.id, Division.label == scope.division
        )
    )
    if division is None:
        division = Division(
            department_id=department.id, label=scope.division, semester_id=semester.id
        )
        session.add(division)
        session.flush()
    return division


def seed_legend_data(session: Session, legends: list[Legend] | None = None) -> dict[str, object]:
    """Seed divisions, legend-only faculty, aliases and scoped initials.

    Requires the spreadsheet faculty to be seeded already: an existing person
    the legends name but the database lacks stops the seed.
    """
    legends = real_legends() if legends is None else legends
    _institute, department = seed_institute_and_department(session)

    faculty = list(session.scalars(select(Faculty).where(Faculty.department_id == department.id)))
    resolution = resolve_legend_names(legends, [f.full_name for f in faculty])
    if resolution.unresolved:
        raise SeedBlocked(
            f"{len(resolution.unresolved)} legend name(s) match no Faculty row and are "
            f"not listed as legend-only: {resolution.unresolved}. Review them and add "
            "each to SPELLING_VARIANTS, ABBREVIATIONS or LEGEND_ONLY_FACULTY."
        )
    by_key = {name_key(f.full_name): f for f in faculty}
    missing = {
        t for t in resolution.target.values() if t not in by_key and t not in resolution.new_faculty
    }
    if missing:
        raise SeedBlocked(
            f"legends name existing faculty the database lacks: {sorted(missing)}. "
            "Run seed_reference_data first."
        )

    # Legend-only people. No qualifications: unknown until grids are parsed.
    created: list[str] = []
    for key, full_name in resolution.new_faculty.items():
        if key not in by_key:
            row = Faculty(
                department_id=department.id, full_name=full_name, source=FacultySource.LEGEND
            )
            session.add(row)
            session.flush()
            by_key[key] = row
            created.append(full_name)

    alias_rows = 0
    for spelling, canonical in aliases(resolution).items():
        person = by_key[name_key(canonical)]
        exists = session.scalar(
            select(FacultyAlias).where(
                FacultyAlias.faculty_id == person.id, FacultyAlias.alias == spelling
            )
        )
        if exists is None:
            session.add(
                FacultyAlias(faculty_id=person.id, alias=spelling, source=MappingSource.LEGEND)
            )
            alias_rows += 1

    scoped = initials_by_scope(legends, resolution)
    initials_rows = 0
    for scope, by_initials in scoped.items():
        division = seed_division(session, department, scope)
        for initials, keys in by_initials.items():
            for key in sorted(keys):
                person = by_key[key]
                row = session.scalar(
                    select(FacultyInitials).where(
                        FacultyInitials.faculty_id == person.id,
                        FacultyInitials.initials == initials,
                        FacultyInitials.semester_id == division.semester_id,
                        FacultyInitials.division_id == division.id,
                    )
                )
                if row is None:
                    row = FacultyInitials(
                        faculty_id=person.id,
                        initials=initials,
                        semester_id=division.semester_id,
                        division_id=division.id,
                        source=MappingSource.LEGEND,
                    )
                    session.add(row)
                    initials_rows += 1
                row.is_ambiguous = len(keys) > 1
    session.flush()

    return {
        "resolution": resolution,
        "faculty_created": created,
        "alias_rows": alias_rows,
        "initials_rows": initials_rows,
        "scopes": len(scoped),
        "ambiguous": ambiguous_initials(scoped),
    }
