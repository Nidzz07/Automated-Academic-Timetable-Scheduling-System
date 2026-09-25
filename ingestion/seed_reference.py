"""Seed reference data from the three source spreadsheets in ``data/real/``.

This is Phase 1 seed data: the entities that exist independently of any
timetable. Programme, Semester, Division, Batch and faculty T/P workloads are
deliberately NOT seeded here - none of that is in these three files. It comes
from the .docx timetables in Phase 2.

Parsing and inserting are kept apart on purpose. Every ``parse_*`` function is
pure - it reads a spreadsheet and returns plain dataclasses, with no database
and no session - so the shape of the real data can be tested, and disagreements
between the two faculty/subject files reported, without a database at all.

All six steps run. Two of them were blocked until migrations 0002 and 0003
landed: 0002 widened ``room_used_as`` to the five verbatim strings the source
actually contains, and 0003 made ``Subject.session_type`` nullable so a
seeded subject can honestly say "not known yet". :class:`SeedBlocked` is still
raised - by :func:`seed_rooms` if a sixth 'used as' wording ever appears, and
by :func:`seed_qualifications` if a pair would be orphaned - because the right
response to unexpected data is to stop and report, never to coerce.

The subject list is derived from the "Subjects taught" column of
Faculty___Subjects.xlsx, not from the inverted sheet. See
:func:`subject_codes_to_seed` for why that choice decides three rows.

The governing rule is CONTEXT.md section 3.5: the ingestion layer *reports*
data-quality defects, it never silently repairs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    Department,
    Faculty,
    Institute,
    QualificationSource,
    Room,
    RoomUsedAs,
    Subject,
    SubRoom,
    qualification,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "real"

CLASSROOMS_XLSX = DATA_DIR / "classrooms.xlsx"
FACULTY_SUBJECTS_XLSX = DATA_DIR / "Faculty___Subjects.xlsx"
SUBJECT_WISE_XLSX = DATA_DIR / "Subject-wise_faculty.xlsx"

INSTITUTE_CODE = "SPIT"
INSTITUTE_NAME = "Sardar Patel Institute of Technology"
DEPARTMENT_CODE = "CE"
DEPARTMENT_NAME = "Computer Engineering"

# The header in classrooms.xlsx is misspelled "seperation(if any)". Matched
# verbatim - correcting it here would just fail to find the column.
CLASSROOM_HEADERS = ("Classroom no", "capacity", "seperation(if any)", "used as")


class SeedBlocked(RuntimeError):
    """A seed step cannot run without either a schema change or a decision.

    Raised instead of guessing. The message names exactly what is missing.
    """


# ---------------------------------------------------------------------------
# parsed shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedSubRoom:
    label: str
    capacity: int


@dataclass(frozen=True)
class ParsedRoom:
    code: str
    capacity: int
    #: Raw value of the misspelled "seperation(if any)" column, or None.
    separation: str | None
    #: Raw "used as" string, exactly as written in the sheet. Never normalised.
    used_as: str
    sub_rooms: tuple[ParsedSubRoom, ...] = ()


@dataclass(frozen=True)
class ParsedFaculty:
    #: The sheet's own "#" column, kept so a row can be traced back.
    index: int | None
    full_name: str
    subject_codes: tuple[str, ...]


@dataclass
class CrossCheck:
    """Result of comparing the two faculty/subject files against each other."""

    forward_pairs: set[tuple[str, str]] = field(default_factory=set)
    inverted_pairs: set[tuple[str, str]] = field(default_factory=set)
    forward_only: set[tuple[str, str]] = field(default_factory=set)
    inverted_only: set[tuple[str, str]] = field(default_factory=set)
    codes_missing_from_subject_wise: set[str] = field(default_factory=set)
    codes_unused_by_faculty_sheet: set[str] = field(default_factory=set)
    names_only_in_subject_wise: set[str] = field(default_factory=set)
    names_only_in_faculty_sheet: set[str] = field(default_factory=set)

    @property
    def agrees(self) -> bool:
        return not (self.forward_only or self.inverted_only)


# ---------------------------------------------------------------------------
# room 702 and the 607A/607B shape
# ---------------------------------------------------------------------------

# Sub-room labels are plain digits (1, 2, 3) for every separable room EXCEPT
# 702, which gets letters (A, B, C).
#
# Why the exception: the labels have to match what the real timetables
# actually write, because the Phase 2 .docx parser resolves cells like
# "OS / A / AGN / 702-A" by looking the sub-room up by label. CONTEXT.md
# section 3.4 records 702's sub-rooms as "702-A" and 603's as "603-2" - the
# source is genuinely inconsistent between letters and digits, and inventing a
# uniform scheme here would make half those lookups miss.
LETTERED_SUBROOM_ROOMS = frozenset({"702"})

# 607A and 607B arrive as two separate rows with no separation value, so they
# are inserted as two independent Rooms. There is NO row for "607" itself, so
# there is nothing to hang sub-rooms off - creating a synthetic parent would be
# fabricating a room the source does not contain.
#
# Note for whoever writes the Phase 2 .docx parser: 603/606/702 and 607A/607B
# are two different *representations of the same real-world pattern* - one
# physical space with several usable areas. A timetable cell may therefore
# reference either shape. "607-A" appearing in a cell would have to resolve to
# the Room with code "607A", not to a sub-room of a room called "607".
SPLIT_AS_SEPARATE_ROOMS = frozenset({"607A", "607B"})

# ---------------------------------------------------------------------------
# faculty additions and the partial initials map
# ---------------------------------------------------------------------------

#: Deepak Nair appears in NEITHER spreadsheet. He is added on the strength of a
#: verbal instruction only, so his record is flagged: it has not been checked
#: against any source file and should be confirmed before the data is trusted.
EXTRA_FACULTY_NAME = "Dr. Deepak Nair"
UNVERIFIED_FACULTY_NAMES = frozenset({EXTRA_FACULTY_NAME})

#: PCS reaches us only through Deepak Nair's mapping - it is absent from
#: Subject-wise_faculty.xlsx, so it is added explicitly rather than parsed.
EXTRA_SUBJECT_CODE = "PCS"
EXTRA_SUBJECT_NAME = "Professional Communication Skills"

# Initials -> faculty, 8 of 33. NOT a complete mapping and not to be extended
# by guesswork.
#
# The remaining 25 are filled in during Phase 2 .docx ingestion, where each
# initial is verified against the timetable cell it actually appears in. Two
# faculty share a surname often enough in this department that deriving
# initials from names would produce plausible-looking wrong answers, and a
# wrong initials mapping silently assigns somebody else's teaching load.
FACULTY_INITIALS: dict[str, str] = {
    "AGN": "Amey Ganesh Nile",
    "NR": "Nataasha Raul",
    "JR": "Jyoti Ramteke",
    "DRK": "D. R. Kalbande",
    "JS": "Jignesh Sisodia",
    "KKD": "Dr. Kailas Kisan Devadkar",
    "PBB": "Dr. Prasenjit B. Bhavathankar",
    "DN": EXTRA_FACULTY_NAME,
}

# Three names in FACULTY_INITIALS are written more fully than the spreadsheet
# writes them (honorific, middle name). They are the same people, so they map
# onto the existing rows - creating a second Faculty row for
# "Dr. Kailas Kisan Devadkar" alongside "Kailas Devadkar" would split one
# person's timetable in two. The spreadsheet spelling stays authoritative for
# full_name; this table only resolves the alias.
INITIALS_NAME_ALIASES: dict[str, str] = {
    "Dr. Kailas Kisan Devadkar": "Kailas Devadkar",
    "Dr. Prasenjit B. Bhavathankar": "Prasenjit Bhavathankar",
    # Deepak Nair has no spreadsheet row at all; he is seeded under this name.
    EXTRA_FACULTY_NAME: EXTRA_FACULTY_NAME,
}


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def _sheet_rows(path: Path) -> list[tuple]:
    workbook = openpyxl.load_workbook(path, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    return list(sheet.iter_rows(values_only=True))


def _split_list(cell: str | None) -> tuple[str, ...]:
    """Split a comma-separated cell.

    A plain comma split is safe here: no subject code in the source contains a
    comma inside its parentheses ("MDM-I (DBMS)", "MDM-III Theory (CC)").
    """
    if not cell:
        return ()
    return tuple(part.strip() for part in str(cell).split(",") if part.strip())


def _sub_room_labels(room_code: str, count: int) -> list[str]:
    if room_code in LETTERED_SUBROOM_ROOMS:
        return [chr(ord("A") + i) for i in range(count)]
    return [str(i + 1) for i in range(count)]


def parse_classrooms(path: Path = CLASSROOMS_XLSX) -> list[ParsedRoom]:
    """Parse classrooms.xlsx into rooms, expanding the separation column.

    Every row becomes one :class:`ParsedRoom`, including the two rows that both
    say "507" - they are a documented defect (CONTEXT.md section 3.5), not a
    duplicate to merge. ``used_as`` is carried through untouched.
    """
    rows = _sheet_rows(path)
    header = tuple(str(cell).strip() if cell is not None else "" for cell in rows[0][:4])
    if header != CLASSROOM_HEADERS:
        raise SeedBlocked(
            f"classrooms.xlsx header changed.\n  expected: {CLASSROOM_HEADERS}\n"
            f"  found   : {header}\n"
            "The third column is misspelled 'seperation(if any)' in the source; "
            "that is expected."
        )

    rooms: list[ParsedRoom] = []
    for code, capacity, separation, used_as in (row[:4] for row in rows[1:]):
        if code is None:
            continue
        code = str(code).strip()
        separation = str(separation).strip() if separation is not None else None

        sub_rooms: tuple[ParsedSubRoom, ...] = ()
        if separation:
            capacities = [int(part) for part in separation.split("-")]
            labels = _sub_room_labels(code, len(capacities))
            sub_rooms = tuple(
                ParsedSubRoom(label=label, capacity=cap)
                for label, cap in zip(labels, capacities, strict=True)
            )

        rooms.append(
            ParsedRoom(
                code=code,
                capacity=int(capacity),
                separation=separation,
                used_as=str(used_as).strip(),
                sub_rooms=sub_rooms,
            )
        )
    return rooms


def parse_faculty_subjects(path: Path = FACULTY_SUBJECTS_XLSX) -> list[ParsedFaculty]:
    """Parse Faculty___Subjects.xlsx - the authoritative direction."""
    rows = _sheet_rows(path)
    parsed: list[ParsedFaculty] = []
    for index, full_name, subjects in (row[:3] for row in rows[1:]):
        if not full_name:
            continue
        parsed.append(
            ParsedFaculty(
                index=int(index) if index is not None else None,
                full_name=str(full_name).strip(),
                subject_codes=_split_list(subjects),
            )
        )
    return parsed


def parse_subject_wise(path: Path = SUBJECT_WISE_XLSX) -> dict[str, tuple[str, ...]]:
    """Parse Subject-wise_faculty.xlsx - the inverted CROSS-CHECK only.

    This file is not a second source of truth. Where the two disagree,
    Faculty___Subjects.xlsx wins and the disagreement is reported.
    """
    rows = _sheet_rows(path)
    mapping: dict[str, tuple[str, ...]] = {}
    for code, faculty in (row[:2] for row in rows[1:]):
        if not code:
            continue
        mapping[str(code).strip()] = _split_list(faculty)
    return mapping


def cross_check(
    faculty: list[ParsedFaculty] | None = None,
    subject_wise: dict[str, tuple[str, ...]] | None = None,
) -> CrossCheck:
    """Compare the two files in both directions and report every difference."""
    faculty = parse_faculty_subjects() if faculty is None else faculty
    subject_wise = parse_subject_wise() if subject_wise is None else subject_wise

    forward = {(f.full_name, code) for f in faculty for code in f.subject_codes}
    inverted = {
        (name, code) for code, names in subject_wise.items() for name in names
    }

    forward_names = {f.full_name for f in faculty}
    forward_codes = {code for _, code in forward}

    return CrossCheck(
        forward_pairs=forward,
        inverted_pairs=inverted,
        forward_only=forward - inverted,
        inverted_only=inverted - forward,
        codes_missing_from_subject_wise=forward_codes - set(subject_wise),
        codes_unused_by_faculty_sheet=set(subject_wise) - forward_codes,
        names_only_in_subject_wise={n for n, _ in inverted} - forward_names,
        names_only_in_faculty_sheet=forward_names - {n for n, _ in inverted},
    )


# ---------------------------------------------------------------------------
# seeding - step 1: minimal hierarchy
# ---------------------------------------------------------------------------


def seed_institute_and_department(session: Session) -> tuple[Institute, Department]:
    """Create the Institute and CE Department if a prior seed has not.

    Looked up by code rather than blindly inserted, so re-running the seeder
    does not accumulate duplicate parents.
    """
    institute = session.scalar(select(Institute).where(Institute.code == INSTITUTE_CODE))
    if institute is None:
        institute = Institute(code=INSTITUTE_CODE, name=INSTITUTE_NAME)
        session.add(institute)
        session.flush()

    department = session.scalar(
        select(Department).where(
            Department.institute_id == institute.id,
            Department.code == DEPARTMENT_CODE,
        )
    )
    if department is None:
        department = Department(
            institute_id=institute.id,
            code=DEPARTMENT_CODE,
            name=DEPARTMENT_NAME,
        )
        session.add(department)
        session.flush()

    return institute, department

# ---------------------------------------------------------------------------
# seeding - step 2: rooms and sub-rooms
# ---------------------------------------------------------------------------


def room_used_as_gap(rooms: list[ParsedRoom] | None = None) -> list[str]:
    """Raw ``used as`` strings the ``room_used_as`` enum cannot store.

    Empty since migration 0002 widened the enum to the verbatim five. Kept as a
    live guard: if classrooms.xlsx ever gains a sixth wording, this reports it
    instead of the seeder dying on an opaque Postgres cast error.
    """
    rooms = parse_classrooms() if rooms is None else rooms
    allowed = {member.value for member in RoomUsedAs}
    return sorted({room.used_as for room in rooms} - allowed)


def seed_rooms(session: Session, institute: Institute) -> list[Room]:
    """Seed every classrooms.xlsx row, expanding the separation column.

    Takes the Institute, not a Department: rooms are institute-level and carry
    no department scoping at all (CONTEXT.md section 2 rule 5).

    Idempotency keys on (code, capacity, used_as) rather than code alone,
    because ``code`` is deliberately not unique - room 507 legitimately appears
    twice, as a 160-seat class and a 20-seat "as a lab" (CONTEXT.md 3.5).
    Keying on code would silently collapse the pair on a re-run.
    """
    gap = room_used_as_gap()
    if gap:
        raise SeedBlocked(
            f"classrooms.xlsx contains 'used as' values the room_used_as enum "
            f"cannot store: {gap}. Widen the enum in a migration - do not fold "
            "them into a neighbouring value (CONTEXT.md 3.5)."
        )

    seeded: list[Room] = []
    for parsed in parse_classrooms():
        used_as = RoomUsedAs(parsed.used_as)
        room = session.scalar(
            select(Room).where(
                Room.institute_id == institute.id,
                Room.code == parsed.code,
                Room.capacity == parsed.capacity,
                Room.used_as == used_as,
            )
        )
        if room is None:
            room = Room(
                institute_id=institute.id,
                code=parsed.code,
                capacity=parsed.capacity,
                used_as=used_as,
                separation=parsed.separation,
            )
            session.add(room)
            session.flush()

        for sub in parsed.sub_rooms:
            existing = session.scalar(
                select(SubRoom).where(
                    SubRoom.room_id == room.id, SubRoom.label == sub.label
                )
            )
            if existing is None:
                session.add(
                    SubRoom(room_id=room.id, label=sub.label, capacity=sub.capacity)
                )
        session.flush()
        seeded.append(room)
    return seeded


# seeding - step 3: faculty
# ---------------------------------------------------------------------------


def seed_faculty(
    session: Session,
    department: Department,
    faculty: list[ParsedFaculty] | None = None,
) -> list[Faculty]:
    """Seed the 32 spreadsheet faculty plus the unverified 33rd.

    Workload (T/P hours) is left null: it is not in these files, it comes from
    the faculty .docx in Phase 2.
    """
    faculty = parse_faculty_subjects() if faculty is None else faculty

    names = [row.full_name for row in faculty]
    names.append(EXTRA_FACULTY_NAME)

    seeded: list[Faculty] = []
    for name in names:
        existing = session.scalar(
            select(Faculty).where(
                Faculty.department_id == department.id, Faculty.full_name == name
            )
        )
        if existing is None:
            existing = Faculty(department_id=department.id, full_name=name)
            session.add(existing)
            session.flush()
        seeded.append(existing)
    return seeded


def apply_faculty_initials(session: Session, department: Department) -> dict[str, str]:
    """Apply the partial 8-of-33 initials map, leaving the other 25 null.

    Returns the initials actually applied. Raises if an entry does not resolve
    to exactly one Faculty row - a silently unmatched initial would leave a
    timetable cell unattributable later.
    """
    applied: dict[str, str] = {}
    for initials, as_given in FACULTY_INITIALS.items():
        sheet_name = INITIALS_NAME_ALIASES.get(as_given, as_given)
        row = session.scalar(
            select(Faculty).where(
                Faculty.department_id == department.id, Faculty.full_name == sheet_name
            )
        )
        if row is None:
            raise SeedBlocked(
                f"initials {initials!r} map to {as_given!r} (spreadsheet name "
                f"{sheet_name!r}) but no such Faculty row exists"
            )
        row.initials = initials
        applied[initials] = row.full_name
    session.flush()
    return applied


# ---------------------------------------------------------------------------
# seeding - steps 4 and 5: subjects and qualifications
# ---------------------------------------------------------------------------


def subject_codes_to_seed(faculty: list[ParsedFaculty] | None = None) -> list[str]:
    """Every distinct subject code across all faculty rows, plus PCS.

    Derived from the "Subjects taught" column of Faculty___Subjects.xlsx - the
    authoritative direction - NOT from Subject-wise_faculty.xlsx.

    That choice decides three rows. The inverted sheet drops Rupali Sawant's
    'MDM-I Lab' and collapses Soni Bhambar's 'MDM-III Theory (CC)' and
    'MDM-III Lab (CC)' into a single merged 'MDM-III (CC)'. Seeding from it
    would leave those three qualification pairs pointing at subjects that do
    not exist, and would insert a merged code no faculty row actually names.
    Deriving from the faculty sheet gives every pair a home and drops
    'MDM-III (CC)' entirely.
    """
    faculty = parse_faculty_subjects() if faculty is None else faculty
    codes = {code for row in faculty for code in row.subject_codes}
    codes.add(EXTRA_SUBJECT_CODE)
    return sorted(codes)


def orphaned_qualification_pairs(
    faculty: list[ParsedFaculty] | None = None,
) -> set[tuple[str, str]]:
    """Faculty->subject pairs whose subject code is not in the seed list.

    Must be empty. A non-empty result means the subject list and the pair list
    were derived from different files again.
    """
    faculty = parse_faculty_subjects() if faculty is None else faculty
    codes = set(subject_codes_to_seed(faculty))
    return {
        (row.full_name, code)
        for row in faculty
        for code in row.subject_codes
        if code not in codes
    }


def seed_subjects(session: Session, department: Department) -> list[Subject]:
    """Seed one Subject per distinct code, leaving ``session_type`` null.

    Null is the correct state, not a gap to fill: no source file states
    theory/lab/both, and **Phase 2 .docx ingestion backfills it from real
    timetable cells** - a subject seen in a lab cell versus a theory cell.
    Defaulting it here would write a guess into every row.

    ``name`` falls back to the code for all but PCS. The spreadsheets carry
    codes only, and inventing expansions ("DAA" -> "Design and Analysis of
    Algorithms") would be fabricated institutional data. Phase 2, or a subject
    master list, replaces them.
    """
    seeded: list[Subject] = []
    for code in subject_codes_to_seed():
        subject = session.scalar(
            select(Subject).where(
                Subject.department_id == department.id, Subject.code == code
            )
        )
        if subject is None:
            subject = Subject(
                department_id=department.id,
                code=code,
                name=EXTRA_SUBJECT_NAME if code == EXTRA_SUBJECT_CODE else code,
                session_type=None,
            )
            session.add(subject)
            session.flush()
        seeded.append(subject)
    return seeded


def seed_qualifications(session: Session, department: Department) -> int:
    """Seed Faculty <-> Subject from the faculty sheet, plus Deepak Nair -> PCS.

    ``source`` is OBSERVED for every pair: these were read off a spreadsheet of
    who currently teaches what, not off an authoritative allocation order.

    Deepak Nair's PCS pair is the one entry with no spreadsheet backing - it
    rests on the same unverified instruction as his Faculty row.
    """
    orphans = orphaned_qualification_pairs()
    if orphans:
        raise SeedBlocked(
            f"{len(orphans)} qualification pair(s) reference a subject that will "
            f"not be seeded: {sorted(orphans)}. The subject list and the pair "
            "list must both derive from Faculty___Subjects.xlsx."
        )

    pairs: list[tuple[str, str]] = [
        (row.full_name, code)
        for row in parse_faculty_subjects()
        for code in row.subject_codes
    ]
    pairs.append((EXTRA_FACULTY_NAME, EXTRA_SUBJECT_CODE))

    faculty_by_name = {
        row.full_name: row
        for row in session.scalars(
            select(Faculty).where(Faculty.department_id == department.id)
        )
    }
    subject_by_code = {
        row.code: row
        for row in session.scalars(
            select(Subject).where(Subject.department_id == department.id)
        )
    }

    inserted = 0
    for name, code in pairs:
        faculty_row = faculty_by_name.get(name)
        subject_row = subject_by_code.get(code)
        if faculty_row is None or subject_row is None:
            raise SeedBlocked(
                f"qualification {name!r} -> {code!r} cannot be linked: "
                f"faculty found={faculty_row is not None}, "
                f"subject found={subject_row is not None}"
            )
        already = session.execute(
            select(qualification).where(
                qualification.c.faculty_id == faculty_row.id,
                qualification.c.subject_id == subject_row.id,
            )
        ).first()
        if already is None:
            session.execute(
                qualification.insert().values(
                    faculty_id=faculty_row.id,
                    subject_id=subject_row.id,
                    source=QualificationSource.OBSERVED,
                )
            )
            inserted += 1
    session.flush()
    return inserted


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def seed_reference_data(session: Session) -> dict[str, object]:
    """Run the full reference seed and report what it wrote.

    Order matters: rooms need the Institute, subjects need the Department, and
    qualifications need both faculty and subjects to exist first.

    Nothing here swallows a :class:`SeedBlocked`. If the source data stops
    fitting the schema, the seed stops - a partially seeded database that looks
    complete is worse than one that failed loudly.
    """
    institute, department = seed_institute_and_department(session)
    rooms = seed_rooms(session, institute)
    faculty = seed_faculty(session, department)
    initials = apply_faculty_initials(session, department)
    subjects = seed_subjects(session, department)
    qualifications = seed_qualifications(session, department)

    return {
        "institute": institute,
        "department": department,
        "room_count": len(rooms),
        "sub_room_count": sum(len(r.sub_rooms) for r in parse_classrooms()),
        "faculty_count": len(faculty),
        "initials_applied": initials,
        "subject_count": len(subjects),
        "qualification_count": qualifications,
        "orphaned_pairs": orphaned_qualification_pairs(),
        "cross_check": cross_check(),
    }
