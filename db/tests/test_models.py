"""Model and migration tests, run against the LOCAL Docker Postgres.

These tests create, drop and migrate whole databases, so they refuse to run
against anything that is not a local host. Never point them at Supabase.

Connection resolution, in order:

1. ``CHRONOS_TEST_DATABASE_URL`` - an explicit override;
2. ``CHRONOS_DB_PORT`` (default 5432) - the host port docker-compose publishes
   the ``db`` service on, with the standard chronos credentials.

If a native PostgreSQL install already owns 5432 on your machine, set
``CHRONOS_DB_PORT`` to the port you gave docker-compose, e.g.::

    $env:CHRONOS_DB_PORT = "55432"

The whole module skips when no local database is reachable, so a checkout with
Docker stopped still runs the rest of the suite.
"""

from __future__ import annotations

import os
import re
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as OrmSession

from db.models import (
    AbsenceRecord,
    AuditEntry,
    Base,
    Batch,
    Cohort,
    CohortType,
    CombinedDivisions,
    Department,
    Division,
    ElectiveGroup,
    Faculty,
    Institute,
    LabBlock,
    PinnedBlock,
    PinnedKind,
    Programme,
    QualificationSource,
    Room,
    RoomUsedAs,
    Semester,
    SessionType,
    Subject,
    SubjectSessionType,
    SubRoom,
    TermCode,
    Timetable,
    TimetableStatus,
    qualification,
)
from db.models import Session as SessionModel

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})

TEST_DB_NAME = "chronos_test"
MIGRATION_DB_NAME = "chronos_migration_test"


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

# Hard stop: these tests drop databases. They never touch shared staging.
if _host_of(BASE_URL) not in LOCAL_HOSTS:
    pytest.skip(
        f"refusing to run destructive DB tests against non-local host "
        f"{_host_of(BASE_URL)!r}",
        allow_module_level=True,
    )


def _admin_engine():
    """Engine on the maintenance database, for CREATE/DROP DATABASE."""
    return create_engine(_with_database(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")


def _recreate_database(name: str) -> None:
    with _admin_engine().connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))


def _drop_database(name: str) -> None:
    with _admin_engine().connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


try:
    with _admin_engine().connect() as _probe:
        _probe.execute(text("SELECT 1"))
except OperationalError as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        "local Postgres not reachable at "
        f"{_host_of(BASE_URL)}:{os.environ.get('CHRONOS_DB_PORT', '5432')} "
        f"- start it with `docker compose up db -d` ({exc.__class__.__name__})",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    _recreate_database(TEST_DB_NAME)
    eng = create_engine(_with_database(BASE_URL, TEST_DB_NAME))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    _drop_database(TEST_DB_NAME)


@pytest.fixture
def session(engine):
    """Each test runs in a transaction that is rolled back afterwards."""
    connection = engine.connect()
    transaction = connection.begin()
    orm_session = OrmSession(bind=connection)
    yield orm_session
    orm_session.close()
    # A failed flush (the IntegrityError tests) already rolled this back.
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def scaffold(session):
    """A minimal but complete object graph, one row per hierarchy level."""
    institute = Institute(code="SPIT", name="Sardar Patel Institute of Technology")
    session.add(institute)
    session.flush()

    ce = Department(institute_id=institute.id, code="CE", name="Computer Engineering")
    cse = Department(institute_id=institute.id, code="CSE", name="Computer Science")
    session.add_all([ce, cse])
    session.flush()

    programme = Programme(department_id=ce.id, code="BTECH", name="B.Tech CE")
    session.add(programme)
    session.flush()

    semester = Semester(
        department_id=ce.id,
        programme_id=programme.id,
        number=4,
        term_code=TermCode.EVEN,
        academic_year="2025-26",
    )
    session.add(semester)
    session.flush()

    division = Division(
        department_id=ce.id, label="SE-Comp B", strength=72, semester_id=semester.id
    )
    session.add(division)
    session.flush()

    batch = Batch(department_id=ce.id, label="A", strength=18, division_id=division.id)
    session.add(batch)

    room = Room(
        institute_id=institute.id,
        code="702",
        capacity=60,
        used_as=RoomUsedAs.LAB,
        separation="20-20-20",
    )
    session.add(room)
    session.flush()

    sub_room = SubRoom(room_id=room.id, label="702-A", capacity=20)
    faculty = Faculty(
        department_id=ce.id,
        full_name="A. G. Nikam",
        initials="AGN",
        theory_hours=6,
        practical_hours=8,
        total_hours=14,
    )
    subject = Subject(
        department_id=ce.id,
        code="OS",
        name="Operating Systems",
        session_type=SubjectSessionType.BOTH,
    )
    session.add_all([sub_room, faculty, subject])
    session.flush()

    timetable = Timetable(
        department_id=ce.id,
        semester_id=semester.id,
        name="CE EVEN 2025-26",
        status=TimetableStatus.DRAFT,
    )
    session.add(timetable)
    session.flush()

    return {
        "institute": institute,
        "department": ce,
        "other_department": cse,
        "programme": programme,
        "semester": semester,
        "division": division,
        "batch": batch,
        "room": room,
        "sub_room": sub_room,
        "faculty": faculty,
        "subject": subject,
        "timetable": timetable,
    }


def make_session_row(scaffold, **overrides) -> SessionModel:
    defaults = dict(
        department_id=scaffold["department"].id,
        timetable_id=scaffold["timetable"].id,
        cohort_id=scaffold["division"].id,
        subject_id=scaffold["subject"].id,
        faculty_id=scaffold["faculty"].id,
        room_id=scaffold["room"].id,
        day=0,
        period=1,
        duration_periods=2,
        session_type=SessionType.LAB,
        source_cell="OS / A / AGN / 702-A",
    )
    defaults.update(overrides)
    return SessionModel(**defaults)


# ---------------------------------------------------------------------------
# every model inserts
# ---------------------------------------------------------------------------


def test_scaffold_inserts_the_hierarchy(session, scaffold):
    session.flush()
    assert scaffold["institute"].id is not None
    assert scaffold["division"].semester_id == scaffold["semester"].id
    assert scaffold["batch"].division_id == scaffold["division"].id


def test_session_lab_block_and_pinned_block_insert(session, scaffold):
    lab_block = LabBlock(
        department_id=scaffold["department"].id,
        division_id=scaffold["division"].id,
        day=0,
        start_period=1,
        duration_periods=2,
    )
    session.add(lab_block)
    session.flush()

    row = make_session_row(scaffold, lab_block_id=lab_block.id)
    session.add(row)
    session.flush()

    pinned = PinnedBlock(
        department_id=scaffold["department"].id,
        cohort_id=scaffold["division"].id,
        label="MDM -I THEORY",
        day=3,
        period=4,
        duration_periods=1,
        kind=PinnedKind.MDM,
    )
    session.add(pinned)
    session.flush()

    assert row.lab_block_id == lab_block.id
    assert lab_block.must_be_contiguous is True
    assert pinned.id is not None


def test_qualification_association_inserts(session, scaffold):
    session.execute(
        qualification.insert().values(
            faculty_id=scaffold["faculty"].id,
            subject_id=scaffold["subject"].id,
            source=QualificationSource.OBSERVED,
        )
    )
    session.flush()
    session.refresh(scaffold["faculty"])
    assert [s.code for s in scaffold["faculty"].subjects] == ["OS"]


def test_absence_record_and_audit_entry_insert(session, scaffold):
    replacement = Faculty(
        department_id=scaffold["department"].id, full_name="N. Raut", initials="NR"
    )
    session.add(replacement)
    session.flush()

    absence = AbsenceRecord(
        department_id=scaffold["department"].id,
        faculty_id=scaffold["faculty"].id,
        absence_date=date(2026, 3, 9),
        day=0,
        period=1,
        replacement_faculty_id=replacement.id,
        reason="conference",
    )
    audit = AuditEntry(
        department_id=scaffold["department"].id,
        actor="coordinator@spit.ac.in",
        action="substitute_faculty",
        affected_session_ids=[11, 12, 13],
        detail="AGN -> NR",
    )
    session.add_all([absence, audit])
    session.flush()

    assert absence.replacement_faculty.initials == "NR"
    assert audit.affected_session_ids == [11, 12, 13]


def test_absence_replacement_is_nullable(session, scaffold):
    """No qualified faculty free is a real outcome - it triggers repair."""
    absence = AbsenceRecord(
        department_id=scaffold["department"].id,
        faculty_id=scaffold["faculty"].id,
        absence_date=date(2026, 3, 10),
        day=1,
        period=3,
    )
    session.add(absence)
    session.flush()
    assert absence.replacement_faculty_id is None


# ---------------------------------------------------------------------------
# CONTEXT.md rule 5 - rooms are institute-level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["room", "sub_room"])
def test_room_tables_have_no_department_column(engine, table_name):
    """Asserted against the real table, not against an unset attribute.

    A test that only checked `room.department_id is None` would pass just as
    happily if the column existed and nobody had filled it in.
    """
    columns = {col["name"] for col in inspect(engine).get_columns(table_name)}
    assert "department_id" not in columns, (
        f"{table_name} must stay institute-level (CONTEXT.md rule 5): the real "
        f"data has CE teaching in CSE rooms. Columns found: {sorted(columns)}"
    )


@pytest.mark.parametrize("table_name", ["room", "sub_room"])
def test_room_tables_have_no_foreign_key_to_department(engine, table_name):
    referred = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys(table_name)}
    assert "department" not in referred


@pytest.mark.parametrize(
    "table_name",
    ["programme", "semester", "cohort", "faculty", "subject", "session", "lab_block"],
)
def test_entities_below_department_carry_department_id(engine, table_name):
    """The positive half of rule 5 - everything else IS department-scoped."""
    columns = {col["name"] for col in inspect(engine).get_columns(table_name)}
    assert "department_id" in columns


def test_a_room_is_usable_by_any_department(session, scaffold):
    """A CE session and a CSE session may share one institute-level room."""
    cse_programme = Programme(
        department_id=scaffold["other_department"].id, code="BTECH", name="B.Tech CSE"
    )
    session.add(cse_programme)
    session.flush()
    cse_semester = Semester(
        department_id=scaffold["other_department"].id,
        programme_id=cse_programme.id,
        number=4,
        term_code=TermCode.EVEN,
        academic_year="2025-26",
    )
    session.add(cse_semester)
    session.flush()
    cse_division = Division(
        department_id=scaffold["other_department"].id,
        label="SE-CSE A",
        semester_id=cse_semester.id,
    )
    cse_subject = Subject(
        department_id=scaffold["other_department"].id,
        code="HMI",
        name="Human Machine Interaction",
        session_type=SubjectSessionType.THEORY,
    )
    session.add_all([cse_division, cse_subject])
    session.flush()
    cse_timetable = Timetable(
        department_id=scaffold["other_department"].id,
        semester_id=cse_semester.id,
        name="CSE EVEN",
        status=TimetableStatus.DRAFT,
    )
    session.add(cse_timetable)
    session.flush()

    ce_row = make_session_row(scaffold, day=0, period=0)
    cse_row = make_session_row(
        scaffold,
        department_id=scaffold["other_department"].id,
        timetable_id=cse_timetable.id,
        cohort_id=cse_division.id,
        subject_id=cse_subject.id,
        day=1,
        period=0,
        duration_periods=1,
        session_type=SessionType.THEORY,
    )
    session.add_all([ce_row, cse_row])
    session.flush()

    assert ce_row.room_id == cse_row.room_id == scaffold["room"].id


# ---------------------------------------------------------------------------
# cohort membership with no fixed cardinality
# ---------------------------------------------------------------------------


def _extra_division(session, scaffold, label: str) -> Division:
    division = Division(
        department_id=scaffold["department"].id,
        label=label,
        semester_id=scaffold["semester"].id,
    )
    session.add(division)
    session.flush()
    return division


def test_combined_divisions_references_two_divisions(session, scaffold):
    """'DAA / SE C & D / 508' - one lecture, one vertex, two divisions."""
    c = _extra_division(session, scaffold, "SE-Comp C")
    d = _extra_division(session, scaffold, "SE-Comp D")

    combined = CombinedDivisions(department_id=scaffold["department"].id, label="SE C & D")
    combined.member_divisions = [c, d]
    session.add(combined)
    session.flush()
    session.refresh(combined)

    assert combined.cohort_type is CohortType.COMBINED
    assert {div.label for div in combined.member_divisions} == {"SE-Comp C", "SE-Comp D"}


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_elective_group_references_an_arbitrary_number_of_divisions(
    session, scaffold, count
):
    """PE-II-A..PE-II-G span a number of divisions not known until parse time."""
    divisions = [_extra_division(session, scaffold, f"SE-Comp E{i}") for i in range(count)]

    elective = ElectiveGroup(department_id=scaffold["department"].id, label="PE-II-A")
    elective.member_divisions = divisions
    session.add(elective)
    session.flush()
    session.refresh(elective)

    assert elective.cohort_type is CohortType.ELECTIVE
    assert len(elective.member_divisions) == count


def test_cohort_batch_membership_expands_to_batches(session, scaffold):
    """Batch-level expansion is what COHORT conflict edges are derived from."""
    combined = CombinedDivisions(department_id=scaffold["department"].id, label="SE C & D")
    combined.member_batches = [scaffold["batch"]]
    session.add(combined)
    session.flush()
    session.refresh(combined)
    assert [b.label for b in combined.member_batches] == ["A"]


def test_subtypes_share_one_table_and_are_polymorphic(session, scaffold):
    """Single-table inheritance: one query over Cohort returns every subtype."""
    assert Division.__table__ is Cohort.__table__
    assert Batch.__table__ is Cohort.__table__

    combined = CombinedDivisions(department_id=scaffold["department"].id, label="SE C & D")
    elective = ElectiveGroup(department_id=scaffold["department"].id, label="PE-I-D")
    session.add_all([combined, elective])
    session.flush()

    found = session.query(Cohort).all()
    assert {type(c) for c in found} >= {Division, Batch, CombinedDivisions, ElectiveGroup}


def test_division_requires_a_semester(session, scaffold):
    """The CHECK that recovers what single-table inheritance made nullable."""
    session.add(Division(department_id=scaffold["department"].id, label="orphan"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_batch_requires_a_division(session, scaffold):
    session.add(Batch(department_id=scaffold["department"].id, label="orphan"))
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# the wall-clock period axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", list(range(10)))
def test_session_accepts_every_wall_clock_period(session, scaffold, period):
    """0-9, NOT 0-7.

    ``period`` is the wall-clock index from the edge-list contract: 2 is the
    short break and 5 is lunch, so the axis runs to 9. If someone later
    "corrects" the CHECK constraint to 0..7 -- mistaking it for the ingestion
    contract's teaching-order index -- periods 8 and 9 (16.15-17.15 and
    17.15-18.15, both real teaching hours) become unstorable and this fails.
    """
    row = make_session_row(scaffold, period=period, duration_periods=1)
    session.add(row)
    session.flush()
    assert row.period == period


@pytest.mark.parametrize("period", [8, 9])
def test_the_last_two_teaching_hours_are_storable(session, scaffold, period):
    """Named separately because these are the ones a 0..7 bound would break."""
    row = make_session_row(scaffold, period=period, duration_periods=1)
    session.add(row)
    session.flush()
    assert row.period == period


@pytest.mark.parametrize("period", [-1, 10, 42])
def test_session_rejects_periods_off_the_wall_clock_axis(session, scaffold, period):
    session.add(make_session_row(scaffold, period=period, duration_periods=1))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("day", [-1, 5])
def test_session_rejects_days_outside_the_week(session, scaffold, day):
    session.add(make_session_row(scaffold, day=day))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "table_name,column",
    [
        ("session", "period"),
        ("lab_block", "start_period"),
        ("pinned_block", "period"),
        ("absence_record", "period"),
    ],
)
def test_every_period_check_constraint_allows_nine(engine, table_name, column):
    """Read the CHECK clauses out of the database and assert the bound is 9."""
    with engine.connect() as conn:
        clauses = conn.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = :t AND c.contype = 'c'"
            ),
            {"t": table_name},
        ).scalars().all()

    relevant = [c for c in clauses if column in c and "<=" in c]
    assert relevant, f"no range CHECK found on {table_name}.{column}"
    assert any("9" in c for c in relevant), (
        f"{table_name}.{column} is not bounded at 9 -- someone may have "
        f"changed it to the ingestion contract's 0..7 axis: {relevant}"
    )


# ---------------------------------------------------------------------------
# room / sub-room exclusivity
# ---------------------------------------------------------------------------


def test_session_may_use_a_sub_room(session, scaffold):
    row = make_session_row(scaffold, room_id=None, sub_room_id=scaffold["sub_room"].id)
    session.add(row)
    session.flush()
    assert row.sub_room.label == "702-A"


def test_session_rejects_both_room_and_sub_room(session, scaffold):
    session.add(
        make_session_row(
            scaffold, room_id=scaffold["room"].id, sub_room_id=scaffold["sub_room"].id
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_session_permits_neither_room_nor_sub_room(session, scaffold):
    """ingestion_v1 allows room_id: null for a cell that named no room."""
    row = make_session_row(scaffold, room_id=None, sub_room_id=None)
    session.add(row)
    session.flush()
    assert row.room_id is None and row.sub_room_id is None


def test_two_sessions_share_a_parent_room_in_different_sub_rooms(session, scaffold):
    """Legal by design: 702-A and 702-B run at once inside room 702."""
    second = SubRoom(room_id=scaffold["room"].id, label="702-B", capacity=20)
    session.add(second)
    session.flush()

    a = make_session_row(scaffold, room_id=None, sub_room_id=scaffold["sub_room"].id)
    b = make_session_row(scaffold, room_id=None, sub_room_id=second.id)
    session.add_all([a, b])
    session.flush()

    assert a.sub_room.room_id == b.sub_room.room_id


def test_sub_room_label_accepts_letters_and_digits(session, scaffold):
    """Naming is inconsistent in the source; no format is assumed."""
    for label in ("702-C", "603-2", "606-4"):
        session.add(SubRoom(room_id=scaffold["room"].id, label=label, capacity=20))
    session.flush()


# ---------------------------------------------------------------------------
# migration 0001
# ---------------------------------------------------------------------------


@pytest.fixture
def migration_config():
    from alembic.config import Config

    _recreate_database(MIGRATION_DB_NAME)
    url = _with_database(BASE_URL, MIGRATION_DB_NAME)

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo_root, "migrations"))

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield cfg, url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        _drop_database(MIGRATION_DB_NAME)


def _table_names(url: str) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _enum_type_count(url: str) -> int:
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")
            ).scalar_one()
    finally:
        eng.dispose()


def test_migration_upgrades_an_empty_database(migration_config):
    from alembic import command

    cfg, url = migration_config
    assert _table_names(url) == set()

    command.upgrade(cfg, "head")

    tables = _table_names(url)
    assert "alembic_version" in tables
    # every table the models declare must exist
    assert set(Base.metadata.tables) <= tables


def test_migration_downgrade_base_reverses_it(migration_config):
    """Including the Postgres ENUM types, which drop_table does not remove."""
    from alembic import command

    cfg, url = migration_config
    command.upgrade(cfg, "head")
    assert _enum_type_count(url) > 0

    command.downgrade(cfg, "base")

    remaining = _table_names(url) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"
    assert _enum_type_count(url) == 0, (
        "downgrade left orphaned enum types -- the next upgrade will fail with "
        "DuplicateObject. migrations/versions/0001 drops them explicitly."
    )


def test_migration_is_repeatable(migration_config):
    """upgrade -> downgrade -> upgrade. This is what caught the enum defect."""
    from alembic import command

    cfg, _url = migration_config
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_migration_matches_the_models(migration_config):
    """No pending autogenerate diff: the migration and models agree."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    cfg, url = migration_config
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            context = MigrationContext.configure(conn)
            diff = compare_metadata(context, Base.metadata)
    finally:
        eng.dispose()

    assert diff == [], f"models have drifted from migration 0001: {diff}"


@pytest.mark.parametrize(
    "table_name,column",
    [
        ("qualification", "subject_id"),
        ("cohort_division_membership", "division_id"),
        ("cohort_batch_membership", "batch_id"),
    ],
)
def test_hand_added_indexes_exist(migration_config, table_name, column):
    """Autogenerate does not index the trailing column of a composite PK."""
    from alembic import command

    cfg, url = migration_config
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    try:
        indexes = inspect(eng).get_indexes(table_name)
    finally:
        eng.dispose()

    assert any(idx["column_names"] == [column] for idx in indexes), (
        f"missing index on {table_name}.{column}; found {indexes}"
    )
