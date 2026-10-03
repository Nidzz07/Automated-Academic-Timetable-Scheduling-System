"""Tests for the legend-scoped initials seed.

The pure tests pin every resolution the seed makes against the real legends -
which spellings were matched by hand-reviewed table, which people are new, and
which initial is ambiguous - so a change to the source files or the tables
fails here first. The database tests use the local Docker Postgres under the
same rules as ``db/tests``, and skip without it.
"""

from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession

from db.models import (
    Base,
    Division,
    Faculty,
    FacultyAlias,
    FacultyInitials,
    FacultySource,
    MappingSource,
    TermCode,
    qualification,
)
from ingestion.initials_legend import Legend, LegendEntry, name_key
from ingestion.seed_legends import (
    ABBREVIATIONS,
    LEGEND_ONLY_FACULTY,
    SPELLING_VARIANTS,
    LegendScope,
    aliases,
    ambiguous_initials,
    initials_by_scope,
    legend_scope,
    real_legends,
    resolve_legend_names,
    seed_legend_data,
)
from ingestion.seed_reference import (
    EXTRA_FACULTY_NAME,
    SeedBlocked,
    parse_faculty_subjects,
    seed_reference_data,
)

SHEET_NAMES = [f.full_name for f in parse_faculty_subjects()]
EXISTING = [*SHEET_NAMES, EXTRA_FACULTY_NAME]

ODD_BE = LegendScope("2025-2026", TermCode.ODD, 7, "B.Tech", "BE Comp- A & B")


@pytest.fixture(scope="module")
def legends() -> list[Legend]:
    return real_legends()


@pytest.fixture(scope="module")
def resolution(legends):
    return resolve_legend_names(legends, EXISTING)


# ---------------------------------------------------------------------------
# pure: resolution against the real legends
# ---------------------------------------------------------------------------


def test_every_legend_name_resolves(resolution):
    assert resolution.unresolved == []


def test_the_eight_legend_only_people(resolution):
    assert resolution.new_faculty == {
        "asma tambe": "Prof. Asma Tambe",
        "aman yadav": "Prof. Aman Yadav",
        "govind gaundalkar": "Prof. Govind Gaundalkar",
        # Written 'Prof.Shaily Goyal' twice and 'Prof. Shaily Goyal' once; the
        # most frequent spelling is kept as written.
        "shaily goyal": "Prof.Shaily Goyal",
        "vipul kushwah": "Vipul Kushwah",
        "suman m": "Prof. Suman M.",
        "suhas kakade": "Prof. Suhas Kakade",
        "sonali dudhihalli": "Prof. Sonali Dudhihalli",
    }
    assert set(resolution.new_faculty) == LEGEND_ONLY_FACULTY


def test_no_new_person_duplicates_an_existing_one(resolution):
    existing_keys = {name_key(n) for n in EXISTING}
    assert not set(resolution.new_faculty) & existing_keys
    # Surname collisions are the risk: none of the new people shares a surname
    # with anyone already seeded.
    existing_surnames = {k.split()[-1] for k in existing_keys}
    assert not {k.split()[-1] for k in resolution.new_faculty} & existing_surnames


def test_deepak_nair_matches_his_existing_row(resolution):
    assert resolution.exact["Dr. Deepak Nair"] == EXTRA_FACULTY_NAME
    assert "deepak nair" not in resolution.new_faculty


def test_spelling_variants_match_existing_spreadsheet_rows(resolution):
    assert resolution.spelling_variants == {
        "Prof. C. R. Gajbhiye": "C R Gajbiye",
        "Prof. Vandana Wekhende": "Vandana Wekhande",
        "Prof. Vaishnavi Rathod": "Vaishnavee Rathod",
        "Prof. Jotsna Bhagat": "Jostna Bhagat",
        "Dr. Sanjukta Jena": "Sanjyuktarani Jena",
    }
    assert set(resolution.spelling_variants.values()) <= set(SHEET_NAMES)


def test_abbreviations_match_existing_rows(resolution):
    assert resolution.abbreviations == {
        "Prof. A. A. Godbole": "Anand Godbole",
        "Mr. Amey Nile": "Amey Ganesh Nile",
        "Dr. D. D. Ambawade": "Dayanand Ambawade",
        "Dr. P. B. Bhavathankar": "Prasenjit Bhavathankar",
        "Prof. Sonali D.": "Prof. Sonali Dudhihalli",
    }


def test_resolution_tables_hold_no_stale_entries(legends):
    """Every hand-reviewed entry is used by at least one real legend spelling."""
    keys = {name_key(e.name) for lg in legends for e in lg.entries}
    assert set(SPELLING_VARIANTS) <= keys
    assert set(ABBREVIATIONS) <= keys
    assert set(LEGEND_ONLY_FACULTY) <= keys


def test_aliases_are_the_differing_spellings_only(resolution):
    found = aliases(resolution)
    assert found == {**resolution.spelling_variants, **resolution.abbreviations}
    # A title- or punctuation-only difference is the same spelling, not an alias.
    assert "Dr, Anant Nimkar" not in found
    assert "Prof. Shaily Goyal" not in found


def test_legends_cover_nineteen_division_scopes(legends, resolution):
    scoped = initials_by_scope(legends, resolution)
    assert len(scoped) == 19
    assert sum(1 for s in scoped if s.term is TermCode.EVEN) == 10
    assert sum(1 for s in scoped if s.term is TermCode.ODD) == 9
    assert ODD_BE in scoped


def test_only_odd_be_sk_is_ambiguous(legends, resolution):
    ambiguous = ambiguous_initials(initials_by_scope(legends, resolution))
    assert ambiguous == {ODD_BE: {"SK": {"swapnali kurhade", "suhas kakade"}}}


def test_conflicting_initials_are_unambiguous_once_scoped(legends, resolution):
    """SD / SM name different people in different divisions - not ambiguity."""
    scoped = initials_by_scope(legends, resolution)
    sd = {s.division: v["SD"] for s, v in scoped.items() if "SD" in v and s.term is TermCode.EVEN}
    assert sd["SE-Comp C"] == {"sonali dudhihalli"}
    assert sd["TE-Comp A"] == {"surekha dholay"}
    sm = {s.division: v["SM"] for s, v in scoped.items() if "SM" in v and s.term is TermCode.EVEN}
    assert sm["SE-Comp B"] == {"suman m"}
    assert sm["TE Comp - C"] == {"sudeep mali"}


# ---------------------------------------------------------------------------
# pure: synthetic legends
# ---------------------------------------------------------------------------


def _synthetic(names: list[tuple[str, str]], header: str, source: str) -> Legend:
    entries = [LegendEntry(i, n, r, 0, n) for r, (i, n) in enumerate(names, start=1)]
    return Legend(source, 1, "X", 1, entries, [], header)


EVEN_FILE = "CE_Class_Time_Table-EVEN_sem_25-26.docx"
HEADER = "Academic Year: 2025-2026 Term: II Semester - IV SE-Comp A"


def test_legend_scope_reads_the_grid_header():
    scope = legend_scope(_synthetic([], HEADER, EVEN_FILE))
    assert scope == LegendScope("2025-2026", TermCode.EVEN, 4, "B.Tech", "SE-Comp A")


def test_legend_scope_refuses_a_term_that_contradicts_the_file():
    header = HEADER.replace("Term: II", "Term: I")
    with pytest.raises(SeedBlocked, match="not the ODD timetable"):
        legend_scope(_synthetic([], header, EVEN_FILE))


def test_legend_scope_refuses_an_unreadable_header():
    with pytest.raises(SeedBlocked, match="cannot read a scope"):
        legend_scope(_synthetic([], "Note 1: Law-II online", EVEN_FILE))


def test_an_unknown_name_is_reported_not_guessed():
    legend = _synthetic([("XY", "Prof. Xavier Yeo")], HEADER, EVEN_FILE)
    assert resolve_legend_names([legend], EXISTING).unresolved == ["Prof. Xavier Yeo"]


def test_a_surname_match_alone_is_not_a_match():
    """'Sudeep Mali' exists; 'Prof. Suman M.' must not resolve to him by surname."""
    legend = _synthetic([("SM", "Prof. Sunita Mali")], HEADER, EVEN_FILE)
    assert resolve_legend_names([legend], EXISTING).unresolved == ["Prof. Sunita Mali"]


# ---------------------------------------------------------------------------
# database-backed seeding
# ---------------------------------------------------------------------------

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})
SEED_DB_NAME = "chronos_legend_seed_test"


def _base_url() -> str:
    override = os.environ.get("CHRONOS_TEST_DATABASE_URL")
    if override:
        return override
    port = os.environ.get("CHRONOS_DB_PORT", "5432")
    return f"postgresql+psycopg2://chronos:chronos@127.0.0.1:{port}/chronos"


def _host_of(url: str) -> str:
    match = re.search(r"@([^/:?]+)", url)
    return match.group(1) if match else ""


def _with_database(url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?|$)", f"/{name}\\1", url)


BASE_URL = _base_url()


def _admin_engine():
    return create_engine(_with_database(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")


def _database_available() -> str | None:
    """Why the DB tests cannot run, or None if they can."""
    if _host_of(BASE_URL) not in LOCAL_HOSTS:
        return f"refusing to seed against non-local host {_host_of(BASE_URL)!r}"
    try:
        with _admin_engine().connect() as probe:
            probe.execute(text("SELECT 1"))
    except OperationalError as exc:  # pragma: no cover - environment dependent
        return (
            "local Postgres not reachable - start it with `docker compose up db -d` "
            f"({exc.__class__.__name__})"
        )
    return None


_UNAVAILABLE = _database_available()
needs_db = pytest.mark.skipif(_UNAVAILABLE is not None, reason=_UNAVAILABLE or "")


@pytest.fixture(scope="module")
def engine():
    with _admin_engine().connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SEED_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{SEED_DB_NAME}"'))
    eng = create_engine(_with_database(BASE_URL, SEED_DB_NAME))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    with _admin_engine().connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SEED_DB_NAME}"'))


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    orm_session = OrmSession(bind=connection)
    yield orm_session
    orm_session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def seeded(session):
    seed_reference_data(session)
    return seed_legend_data(session)


def _scoped_rows(session, initials: str, term: TermCode, division: str) -> list[FacultyInitials]:
    return [
        row
        for row in session.scalars(
            select(FacultyInitials)
            .join(Division, FacultyInitials.division_id == Division.id)
            .where(FacultyInitials.initials == initials, Division.label == division)
        )
        if row.semester.term_code is term
    ]


@needs_db
def test_faculty_count_after_the_legend_seed(session, seeded):
    """32 spreadsheet + Deepak Nair + 8 legend-only people."""
    assert session.query(Faculty).count() == 41
    assert len(seeded["faculty_created"]) == 8


@needs_db
def test_legend_only_faculty_are_marked_and_unqualified(session, seeded):
    rows = session.query(Faculty).filter(Faculty.source == FacultySource.LEGEND).all()
    assert {r.full_name for r in rows} == set(seeded["resolution"].new_faculty.values())
    ids = [r.id for r in rows]
    held = session.execute(select(qualification).where(qualification.c.faculty_id.in_(ids))).all()
    assert held == []


@needs_db
def test_odd_be_sk_yields_two_rows_both_flagged(session, seeded):
    rows = _scoped_rows(session, "SK", TermCode.ODD, "BE Comp- A & B")
    assert len(rows) == 2
    assert {r.faculty.full_name for r in rows} == {"Swapnali Kurhade", "Prof. Suhas Kakade"}
    assert all(r.is_ambiguous for r in rows)
    assert all(r.source is MappingSource.LEGEND for r in rows)


@needs_db
def test_no_other_row_is_flagged_ambiguous(session, seeded):
    flagged = session.query(FacultyInitials).filter(FacultyInitials.is_ambiguous).all()
    assert len(flagged) == 2
    assert {r.initials for r in flagged} == {"SK"}


@needs_db
def test_sk_elsewhere_is_unambiguous(session, seeded):
    rows = _scoped_rows(session, "SK", TermCode.EVEN, "SE-Comp B")
    assert [(r.faculty.full_name, r.is_ambiguous) for r in rows] == [("Swapnali Kurhade", False)]


@needs_db
def test_sd_resolves_per_division(session, seeded):
    se = _scoped_rows(session, "SD", TermCode.EVEN, "SE-Comp C")
    te = _scoped_rows(session, "SD", TermCode.EVEN, "TE-Comp A")
    assert [r.faculty.full_name for r in se] == ["Prof. Sonali Dudhihalli"]
    assert [r.faculty.full_name for r in te] == ["Surekha Dholay"]


@needs_db
def test_seeded_initials_are_case_sensitive(session, seeded):
    at = session.query(FacultyInitials).filter(FacultyInitials.initials == "AT").all()
    ast = session.query(FacultyInitials).filter(FacultyInitials.initials == "AsT").all()
    assert {r.faculty.full_name for r in at} == {"Anuj Tawari"}
    assert {r.faculty.full_name for r in ast} == {"Prof. Asma Tambe"}


@needs_db
def test_spelling_variants_attach_to_existing_rows_as_aliases(session, seeded):
    names = {f.full_name for f in session.query(Faculty).all()}
    for legend_spelling, sheet_name in seeded["resolution"].spelling_variants.items():
        assert legend_spelling not in names
        alias = session.query(FacultyAlias).filter(FacultyAlias.alias == legend_spelling).one()
        assert alias.faculty.full_name == sheet_name
        assert alias.source is MappingSource.LEGEND
    assert session.query(FacultyAlias).count() == 10


@needs_db
def test_legend_rows_are_scoped_consistently(session, seeded):
    rows = (
        session.query(FacultyInitials).filter(FacultyInitials.source == MappingSource.LEGEND).all()
    )
    assert rows
    for row in rows:
        assert row.division is not None
        assert row.semester_id == row.division.semester_id


@needs_db
def test_initials_row_counts(session, seeded):
    manual = (
        session.query(FacultyInitials)
        .filter(FacultyInitials.source == MappingSource.MANUAL)
        .count()
    )
    legend = (
        session.query(FacultyInitials)
        .filter(FacultyInitials.source == MappingSource.LEGEND)
        .count()
    )
    assert manual == 8
    assert legend == seeded["initials_rows"] == 207
    assert session.query(Division).count() == 19


@needs_db
def test_legend_seed_is_idempotent(session, seeded):
    again = seed_legend_data(session)
    assert again["faculty_created"] == []
    assert again["alias_rows"] == 0
    assert again["initials_rows"] == 0
    assert session.query(Faculty).count() == 41
    assert session.query(FacultyInitials).count() == 215
    assert session.query(Division).count() == 19


@needs_db
def test_legend_seed_before_reference_seed_is_refused(session):
    with pytest.raises(SeedBlocked):
        seed_legend_data(session)
