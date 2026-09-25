"""Tests for the Phase 1 reference-data seed.

Split in two, mirroring the module:

* **Parsing tests** need no database. They assert the real shape of the three
  spreadsheets - both "507" rows, 702's lettered sub-rooms, the 607A/607B
  split - and they document the disagreements between the two faculty/subject
  files precisely enough that a change to either file fails a test.
* **Seeding tests** need the local Docker Postgres and skip without it, using
  the same rules as ``db/tests``: never a non-local host, and
  ``CHRONOS_DB_PORT`` when a native Postgres owns 5432.

Migrations 0002 and 0003 unblocked rooms and subjects, so the tripwires that
used to assert those steps were blocked now assert the opposite: that the enum
covers every raw string and that ``session_type`` is nullable. They still fail
loudly if either is reverted.
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
    Faculty,
    QualificationSource,
    Room,
    RoomUsedAs,
    Subject,
    SubRoom,
    qualification,
)
from ingestion.seed_reference import (
    EXTRA_FACULTY_NAME,
    EXTRA_SUBJECT_CODE,
    FACULTY_INITIALS,
    INITIALS_NAME_ALIASES,
    LETTERED_SUBROOM_ROOMS,
    SPLIT_AS_SEPARATE_ROOMS,
    UNVERIFIED_FACULTY_NAMES,
    SeedBlocked,
    apply_faculty_initials,
    cross_check,
    orphaned_qualification_pairs,
    parse_classrooms,
    parse_faculty_subjects,
    parse_subject_wise,
    room_used_as_gap,
    seed_faculty,
    seed_institute_and_department,
    seed_qualifications,
    seed_reference_data,
    seed_rooms,
    seed_subjects,
    subject_codes_to_seed,
)

# ---------------------------------------------------------------------------
# classrooms.xlsx
# ---------------------------------------------------------------------------


def test_classrooms_has_twenty_data_rows():
    assert len(parse_classrooms()) == 20


def test_both_507_rooms_are_kept_as_distinct_records():
    """CONTEXT.md 3.5: room 507 is listed twice. Both rows survive parsing.

    They are a documented defect to report, not a duplicate to merge, and they
    differ in both capacity and usage - so collapsing them would lose a
    160-seat classroom or a 20-seat lab.
    """
    rooms_507 = [room for room in parse_classrooms() if room.code == "507"]

    assert len(rooms_507) == 2
    assert {room.capacity for room in rooms_507} == {160, 20}
    assert {room.used_as for room in rooms_507} == {"class", "as a lab"}
    assert rooms_507[0] != rooms_507[1]


def test_room_code_has_no_unique_constraint():
    """The two 507 rows are only insertable because `code` is not unique."""
    from db.models import Room

    unique_indexes = [ix for ix in Room.__table__.indexes if ix.unique]
    assert unique_indexes == []
    assert Room.__table__.c.code.unique is not True


def test_702_sub_rooms_are_lettered():
    """Timetable cells write '702-A', so the labels must be letters."""
    room = next(r for r in parse_classrooms() if r.code == "702")

    assert room.separation == "20-20-20"
    assert [sub.label for sub in room.sub_rooms] == ["A", "B", "C"]
    assert [sub.capacity for sub in room.sub_rooms] == [20, 20, 20]


@pytest.mark.parametrize(
    "code,expected_labels,expected_capacities",
    [("603", ["1", "2", "3"], [20, 20, 20]), ("606", ["1", "2"], [20, 20])],
)
def test_other_separable_rooms_are_numbered(code, expected_labels, expected_capacities):
    """603 and 606 are referenced as '603-2' in the source, so digits."""
    room = next(r for r in parse_classrooms() if r.code == code)

    assert [sub.label for sub in room.sub_rooms] == expected_labels
    assert [sub.capacity for sub in room.sub_rooms] == expected_capacities


def test_702_is_the_only_lettered_room():
    lettered = {
        room.code
        for room in parse_classrooms()
        if any(sub.label.isalpha() for sub in room.sub_rooms)
    }
    assert lettered == set(LETTERED_SUBROOM_ROOMS) == {"702"}


def test_only_three_rooms_are_separable():
    separable = {r.code for r in parse_classrooms() if r.sub_rooms}
    assert separable == {"603", "606", "702"}


def test_607a_and_607b_are_independent_rooms_not_sub_rooms():
    """The source has no row for '607', so there is no parent to hang them on."""
    rooms = parse_classrooms()
    codes = [room.code for room in rooms]

    assert "607A" in codes and "607B" in codes
    assert "607" not in codes, "a synthetic parent room would be fabricated data"

    for code in SPLIT_AS_SEPARATE_ROOMS:
        room = next(r for r in rooms if r.code == code)
        assert room.sub_rooms == ()
        assert room.separation is None


def test_used_as_is_stored_raw_for_every_row():
    """Five distinct strings, none of them normalised during parsing."""
    values = {room.used_as for room in parse_classrooms()}
    assert values == {"class", "lab", "unsure", "as a lab", "Mtech lab"}


def test_unsure_rooms_are_not_defaulted():
    unsure = {r.code for r in parse_classrooms() if r.used_as == "unsure"}
    assert unsure == {"605", "609"}


# ---------------------------------------------------------------------------
# the two faculty/subject files, and where they disagree
# ---------------------------------------------------------------------------


def test_faculty_sheet_has_32_rows():
    faculty = parse_faculty_subjects()
    assert len(faculty) == 32
    assert len({f.full_name for f in faculty}) == 32


def test_subject_wise_sheet_has_22_codes():
    assert len(parse_subject_wise()) == 22


def test_subject_list_comes_from_the_faculty_sheet_not_the_inverted_one():
    """24 distinct codes across the faculty rows, plus PCS."""
    codes = subject_codes_to_seed()

    assert len(codes) == 25
    assert EXTRA_SUBJECT_CODE in codes

    # The three the inverted sheet drops or merges away now exist in their own right.
    assert "MDM-I Lab" in codes
    assert "MDM-III Theory (CC)" in codes
    assert "MDM-III Lab (CC)" in codes

    # And the inverted sheet's merged version is NOT seeded - no faculty row names it.
    assert "MDM-III (CC)" not in codes


def test_subject_list_is_exactly_the_union_of_taught_codes_plus_pcs():
    taught = {code for row in parse_faculty_subjects() for code in row.subject_codes}
    assert set(subject_codes_to_seed()) == taught | {EXTRA_SUBJECT_CODE}


def test_the_two_files_disagree_in_exactly_four_places():
    """Documents the mismatch rather than asserting the files agree.

    They do not agree, and the seeder must not silently trust one. Three pairs
    exist only in Faculty___Subjects.xlsx and one only in the inverted sheet:
    the inverted sheet collapses Soni Bhambar's separate MDM-III theory and lab
    entries into a single 'MDM-III (CC)', and drops Rupali Sawant's
    'MDM-I Lab' entirely.
    """
    check = cross_check()

    assert len(check.forward_pairs) == 63
    assert len(check.inverted_pairs) == 61
    assert not check.agrees

    assert check.forward_only == {
        ("Rupali Sawant", "MDM-I Lab"),
        ("Soni Bhambar", "MDM-III Theory (CC)"),
        ("Soni Bhambar", "MDM-III Lab (CC)"),
    }
    assert check.inverted_only == {("Soni Bhambar", "MDM-III (CC)")}


def test_three_subject_codes_are_missing_from_the_inverted_sheet():
    check = cross_check()
    assert check.codes_missing_from_subject_wise == {
        "MDM-I Lab",
        "MDM-III Lab (CC)",
        "MDM-III Theory (CC)",
    }
    assert check.codes_unused_by_faculty_sheet == {"MDM-III (CC)"}


def test_faculty_names_agree_between_the_two_files():
    """The names match exactly both ways - only the subject codes diverge."""
    check = cross_check()
    assert check.names_only_in_subject_wise == set()
    assert check.names_only_in_faculty_sheet == set()


def test_no_qualification_pair_is_orphaned():
    """Every faculty->subject pair now has a subject to point at.

    This was three orphans while the subject list came from the inverted sheet.
    Deriving both from Faculty___Subjects.xlsx is what closes it.
    """
    assert orphaned_qualification_pairs() == set()

    codes = set(subject_codes_to_seed())
    assert {code for _, code in cross_check().forward_pairs} <= codes


# ---------------------------------------------------------------------------
# the partial initials map
# ---------------------------------------------------------------------------


def test_initials_map_is_eight_of_thirty_three():
    assert len(FACULTY_INITIALS) == 8


def test_every_mapped_initial_resolves_to_a_real_person():
    """Three entries are written more fully than the sheet writes them."""
    sheet_names = {f.full_name for f in parse_faculty_subjects()}

    for initials, as_given in FACULTY_INITIALS.items():
        resolved = INITIALS_NAME_ALIASES.get(as_given, as_given)
        if resolved == EXTRA_FACULTY_NAME:
            continue  # not in either spreadsheet, by design
        assert resolved in sheet_names, f"{initials} -> {as_given!r} resolves nowhere"


def test_aliases_do_not_create_second_people():
    """'Dr. Kailas Kisan Devadkar' is 'Kailas Devadkar', not a 33rd faculty."""
    sheet_names = {f.full_name for f in parse_faculty_subjects()}
    assert INITIALS_NAME_ALIASES["Dr. Kailas Kisan Devadkar"] == "Kailas Devadkar"
    assert INITIALS_NAME_ALIASES["Dr. Prasenjit B. Bhavathankar"] == "Prasenjit Bhavathankar"
    assert "Dr. Kailas Kisan Devadkar" not in sheet_names
    assert "Kailas Devadkar" in sheet_names


def test_deepak_nair_is_flagged_unverified():
    """He is in neither spreadsheet; the flag says so."""
    assert EXTRA_FACULTY_NAME.strip() == "Dr. Deepak Nair"
    assert EXTRA_FACULTY_NAME in UNVERIFIED_FACULTY_NAMES

    sheet_names = {f.full_name for f in parse_faculty_subjects()}
    assert EXTRA_FACULTY_NAME not in sheet_names
    assert not any("Nair" in name for name in sheet_names)


def test_no_other_faculty_is_flagged_unverified():
    flagged = set(UNVERIFIED_FACULTY_NAMES)
    assert flagged == {EXTRA_FACULTY_NAME}


# ---------------------------------------------------------------------------
# schema guards - formerly the "blocked" tripwires
# ---------------------------------------------------------------------------


def test_room_used_as_enum_covers_every_raw_string():
    """Migration 0002 widened the enum to the five verbatim values.

    'as a lab' stays distinct from 'lab' and 'Mtech lab' from both. If someone
    collapses them, or narrows the enum back, this fails.
    """
    assert room_used_as_gap() == []
    assert {m.value for m in RoomUsedAs} == {
        "class",
        "lab",
        "unsure",
        "as a lab",
        "Mtech lab",
    }


def test_the_guessed_unknown_value_is_gone():
    """'unknown' predated the real data and the data never produces it."""
    assert "unknown" not in {m.value for m in RoomUsedAs}


def test_room_used_as_enum_matches_the_data_exactly():
    """No spare members either - every enum value occurs in classrooms.xlsx."""
    in_sheet = {room.used_as for room in parse_classrooms()}
    assert {m.value for m in RoomUsedAs} == in_sheet


def test_subject_session_type_is_nullable():
    """Migration 0003. Phase 2 backfills it from real timetable cells."""
    assert Subject.__table__.c.session_type.nullable is True


def test_room_gap_guard_still_reports_an_unexpected_value():
    """The guard is live, not decorative: a sixth wording must be reported."""
    from ingestion.seed_reference import ParsedRoom

    invented = [ParsedRoom(code="999", capacity=10, separation=None, used_as="staff room")]
    assert room_used_as_gap(invented) == ["staff room"]


def test_seed_rooms_refuses_an_unstorable_value(monkeypatch):
    """seed_rooms stops rather than coercing if the sheet gains a new wording."""
    import ingestion.seed_reference as seed_module

    monkeypatch.setattr(seed_module, "room_used_as_gap", lambda *a, **k: ["staff room"])
    with pytest.raises(SeedBlocked, match="staff room"):
        seed_module.seed_rooms(None, None)


# ---------------------------------------------------------------------------
# database-backed seeding
# ---------------------------------------------------------------------------

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})
SEED_DB_NAME = "chronos_seed_test"


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

if _host_of(BASE_URL) not in LOCAL_HOSTS:
    pytest.skip(
        f"refusing to seed against non-local host {_host_of(BASE_URL)!r}",
        allow_module_level=True,
    )


def _admin_engine():
    return create_engine(_with_database(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")


try:
    with _admin_engine().connect() as _probe:
        _probe.execute(text("SELECT 1"))
except OperationalError as exc:  # pragma: no cover - environment dependent
    pytest.skip(
        "local Postgres not reachable - start it with `docker compose up db -d` "
        f"({exc.__class__.__name__})",
        allow_module_level=True,
    )


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
def department(session):
    _institute, dept = seed_institute_and_department(session)
    return dept


def test_seeds_exactly_33_faculty(session, department):
    """32 from the spreadsheet, plus the unverified Deepak Nair."""
    seed_faculty(session, department)
    assert session.query(Faculty).count() == 33


def test_the_33rd_is_deepak_nair(session, department):
    seed_faculty(session, department)
    names = {f.full_name for f in session.query(Faculty).all()}
    assert EXTRA_FACULTY_NAME in names
    assert names - {EXTRA_FACULTY_NAME} == {f.full_name for f in parse_faculty_subjects()}


def test_every_faculty_is_scoped_to_ce(session, department):
    seed_faculty(session, department)
    assert all(f.department_id == department.id for f in session.query(Faculty).all())
    assert department.code == "CE"


def test_workload_is_left_null(session, department):
    """T/P hours are not in these files; they arrive with the Phase 2 docx."""
    seed_faculty(session, department)
    for row in session.query(Faculty).all():
        assert row.theory_hours is None
        assert row.practical_hours is None
        assert row.total_hours is None


def test_seeding_twice_does_not_duplicate(session, department):
    seed_faculty(session, department)
    seed_faculty(session, department)
    assert session.query(Faculty).count() == 33


def test_institute_and_department_are_reused_not_duplicated(session):
    from db.models import Department, Institute

    seed_institute_and_department(session)
    seed_institute_and_department(session)
    assert session.query(Institute).count() == 1
    assert session.query(Department).count() == 1


def test_initials_applied_to_exactly_eight(session, department):
    seed_faculty(session, department)
    applied = apply_faculty_initials(session, department)

    assert len(applied) == 8
    with_initials = session.query(Faculty).filter(Faculty.initials.isnot(None)).all()
    assert len(with_initials) == 8
    assert {f.initials for f in with_initials} == set(FACULTY_INITIALS)


def test_the_other_25_have_no_initials(session, department):
    seed_faculty(session, department)
    apply_faculty_initials(session, department)
    without = session.query(Faculty).filter(Faculty.initials.is_(None)).count()
    assert without == 25


def test_kkd_attaches_to_the_spreadsheet_row_not_a_new_one(session, department):
    """The alias must not split one person into two Faculty rows."""
    seed_faculty(session, department)
    apply_faculty_initials(session, department)

    kkd = session.query(Faculty).filter(Faculty.initials == "KKD").one()
    assert kkd.full_name == "Kailas Devadkar"

    pbb = session.query(Faculty).filter(Faculty.initials == "PBB").one()
    assert pbb.full_name == "Prasenjit Bhavathankar"

    assert session.query(Faculty).count() == 33


def test_dn_attaches_to_deepak_nair(session, department):
    seed_faculty(session, department)
    apply_faculty_initials(session, department)
    dn = session.query(Faculty).filter(Faculty.initials == "DN").one()
    assert dn.full_name == EXTRA_FACULTY_NAME


def test_full_seed_writes_rooms_subjects_and_qualifications(session):
    result = seed_reference_data(session)

    assert session.query(Room).count() == 20
    assert session.query(SubRoom).count() == 8  # 3 + 2 + 3
    assert session.query(Subject).count() == 25
    assert session.execute(select(qualification)).all() != []
    assert result["orphaned_pairs"] == set()


def test_orchestrator_reports_what_it_completed(session):
    result = seed_reference_data(session)

    assert result["room_count"] == 20
    assert result["sub_room_count"] == 8
    assert result["faculty_count"] == 33
    assert len(result["initials_applied"]) == 8
    assert result["subject_count"] == 25
    assert result["qualification_count"] == 64
    assert result["orphaned_pairs"] == set()
    # The two files still disagree - that is a fact about the data, and fixing
    # the derivation did not change it. It just no longer orphans anything.
    assert result["cross_check"].agrees is False


def test_seeding_is_idempotent(session):
    """A second full run must not duplicate anything."""
    first = seed_reference_data(session)
    second = seed_reference_data(session)

    assert second["room_count"] == first["room_count"] == 20
    assert session.query(Room).count() == 20
    assert session.query(SubRoom).count() == 8
    assert session.query(Faculty).count() == 33
    assert session.query(Subject).count() == 25
    assert second["qualification_count"] == 0  # nothing new to insert
    assert len(session.execute(select(qualification)).all()) == 64


def test_seed_rooms_takes_the_institute_not_a_department(session):
    """Rooms are institute-level, and the signature says so."""
    institute, _department = seed_institute_and_department(session)
    rooms = seed_rooms(session, institute)

    assert len(rooms) == 20
    assert all(r.institute_id == institute.id for r in rooms)


def test_seed_subjects_alone_leaves_session_type_null(session):
    _institute, department = seed_institute_and_department(session)
    subjects = seed_subjects(session, department)

    assert len(subjects) == 25
    assert all(s.session_type is None for s in subjects)


def test_qualifications_before_subjects_is_refused(session):
    """Ordering matters, and getting it wrong stops rather than half-writing."""
    _institute, department = seed_institute_and_department(session)
    seed_faculty(session, department)

    with pytest.raises(SeedBlocked, match="cannot be linked"):
        seed_qualifications(session, department)


def test_both_507_rooms_are_seeded_as_distinct_rows(session):
    """The documented duplicate survives all the way into the database."""
    seed_reference_data(session)

    rows = session.query(Room).filter(Room.code == "507").all()
    assert len(rows) == 2
    assert {r.capacity for r in rows} == {160, 20}
    assert {r.used_as for r in rows} == {RoomUsedAs.CLASS, RoomUsedAs.AS_A_LAB}
    assert rows[0].id != rows[1].id


def test_702_sub_rooms_are_lettered_in_the_database(session):
    seed_reference_data(session)

    room = session.query(Room).filter(Room.code == "702").one()
    labels = sorted(sub.label for sub in room.sub_rooms)
    assert labels == ["A", "B", "C"]


@pytest.mark.parametrize("code,labels", [("603", ["1", "2", "3"]), ("606", ["1", "2"])])
def test_other_sub_rooms_are_numbered_in_the_database(session, code, labels):
    seed_reference_data(session)

    room = session.query(Room).filter(Room.code == code).one()
    assert sorted(sub.label for sub in room.sub_rooms) == labels


def test_607a_and_607b_are_two_rooms_with_no_sub_rooms(session):
    seed_reference_data(session)

    codes = {r.code for r in session.query(Room).all()}
    assert {"607A", "607B"} <= codes
    assert "607" not in codes
    for code in ("607A", "607B"):
        room = session.query(Room).filter(Room.code == code).one()
        assert room.sub_rooms == []


def test_raw_used_as_strings_reach_the_database(session):
    seed_reference_data(session)

    values = {r.used_as.value for r in session.query(Room).all()}
    assert values == {"class", "lab", "unsure", "as a lab", "Mtech lab"}

    unsure = {r.code for r in session.query(Room).filter(Room.used_as == RoomUsedAs.UNSURE)}
    assert unsure == {"605", "609"}

    mtech = session.query(Room).filter(Room.used_as == RoomUsedAs.MTECH_LAB).one()
    assert mtech.code == "607A"


def test_rooms_carry_no_department(session):
    """Rule 5, verified on the seeded rows, not just the table definition."""
    seed_reference_data(session)
    assert not hasattr(session.query(Room).first(), "department_id")


def test_every_subject_has_a_null_session_type(session):
    """Null is correct: Phase 2 backfills it from real timetable cells."""
    seed_reference_data(session)

    subjects = session.query(Subject).all()
    assert len(subjects) == 25
    assert all(s.session_type is None for s in subjects)


def test_merged_subject_code_is_not_seeded(session):
    seed_reference_data(session)
    codes = {s.code for s in session.query(Subject).all()}

    assert {"MDM-I Lab", "MDM-III Theory (CC)", "MDM-III Lab (CC)"} <= codes
    assert "MDM-III (CC)" not in codes


def test_pcs_is_the_one_subject_with_a_real_name(session):
    seed_reference_data(session)

    pcs = session.query(Subject).filter(Subject.code == "PCS").one()
    assert pcs.name == "Professional Communication Skills"


def test_qualification_count_is_63_pairs_plus_deepak_nair(session):
    """63 from Faculty___Subjects.xlsx, plus the one unverified DN -> PCS."""
    seed_reference_data(session)

    rows = session.execute(select(qualification)).all()
    assert len(rows) == 64
    assert len(cross_check().forward_pairs) == 63


def test_deepak_nair_is_qualified_for_pcs(session):
    seed_reference_data(session)

    nair = session.query(Faculty).filter(Faculty.full_name == EXTRA_FACULTY_NAME).one()
    assert [s.code for s in nair.subjects] == ["PCS"]


def test_every_qualification_is_marked_observed(session):
    """Read off a spreadsheet of current practice, not an allocation order."""
    seed_reference_data(session)

    sources = {row.source for row in session.execute(select(qualification)).all()}
    assert sources == {QualificationSource.OBSERVED}


def test_a_known_faculty_has_the_expected_subjects(session):
    """Spot-check against the sheet: Nataasha Raul teaches three."""
    seed_reference_data(session)

    raul = session.query(Faculty).filter(Faculty.full_name == "Nataasha Raul").one()
    assert sorted(s.code for s in raul.subjects) == ["DAA", "DFIR", "PSOOP"]


def test_rupali_sawant_keeps_her_mdm_lab(session):
    """The pair the inverted sheet drops. It survives now."""
    seed_reference_data(session)

    sawant = session.query(Faculty).filter(Faculty.full_name == "Rupali Sawant").one()
    assert "MDM-I Lab" in {s.code for s in sawant.subjects}


def test_soni_bhambar_keeps_theory_and_lab_separately(session):
    """The pair the inverted sheet merges. Both survive."""
    seed_reference_data(session)

    bhambar = session.query(Faculty).filter(Faculty.full_name == "Soni Bhambar").one()
    codes = {s.code for s in bhambar.subjects}
    assert {"MDM-III Theory (CC)", "MDM-III Lab (CC)"} <= codes
    assert "MDM-III (CC)" not in codes
