"""SQLAlchemy 2.0 models for the Chronos domain (CONTEXT.md section 4).

Three decisions in here are load-bearing. Read them before changing anything.

**1. Rooms are institute-level, never department-scoped.**
Every entity below ``Department`` carries a ``department_id`` *except*
:class:`Room` and :class:`SubRoom`, which carry none at all. This is
CONTEXT.md section 2 rule 5, and it is not a simplification we can revisit
later: the real data shows CE teaching in ``509 new CSE`` and ``403-B``, and
running combined CSE+CE lectures. Adding ``department_id`` to ``Room`` would
make those rows unrepresentable and would need a migration plus a data
backfill to undo. :class:`Faculty` *does* carry a department - the owning one -
but nothing here restricts a faculty member to teaching inside it.

**2. Cohort uses single-table inheritance.**
``Division``, ``Batch``, ``ElectiveGroup`` and ``CombinedDivisions`` all live
in the ``cohort`` table, discriminated by ``cohort_type``. Single-table was
chosen over joined-table because:

- :class:`Session` points at *any* cohort type through one nullable-free FK.
  With joined-table that FK still works, but every load of a session's cohort
  becomes a join against whichever subtype table it turns out to be, and the
  solver's constraint-derivation queries fan out into four-way unions.
- The subtype-specific columns are few (``semester_id`` for a division,
  ``division_id`` for a batch) and cheap to carry as nullable columns.

The cost of single-table is real and worth stating: those two columns *must*
be nullable at the DB level even though each is mandatory for its own subtype.
That integrity is recovered with CHECK constraints keyed on the discriminator
(``ck_cohort_division_requires_semester`` and
``ck_cohort_batch_requires_division``), so the database still refuses a
division with no semester. If the subtypes ever grow a lot of private columns,
revisit this - joined-table would then be the better trade.

**3. ``period`` is the WALL-CLOCK index 0-9, not a teaching-order index.**
It matches ``slot_grid`` in ``contracts/edge_list_v1.schema.json`` and
:mod:`solver.slots` exactly: index 2 is the 11.00-11.15 short break and index 5
is the 13.15-14.15 lunch break, and neither can hold a session. The *ingestion*
contract uses a different axis - teaching-order 0..7, breaks skipped - and
translating between the two is this layer's job. Do not "fix" the CHECK
constraints down to 0..7; that is the exact confusion the edge-list contract
was written to prevent, and there is a test asserting period 8 and 9 are
accepted.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Explicit naming convention. Without it, Alembic emits unnamed CHECK and UNIQUE
# constraints that cannot be dropped again in a downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    """Store enum *values* in Postgres, not Python member names."""
    return [member.value for member in enum_cls]


class TermCode(enum.Enum):
    ODD = "ODD"
    EVEN = "EVEN"


class RoomUsedAs(enum.Enum):
    """The 'used as' column of classrooms.xlsx, verbatim.

    Every member is a string the source actually contains. Nothing is
    normalised: 'as a lab' is kept apart from 'lab' and 'Mtech lab' from both,
    because the distinction may be a real scheduling constraint and CONTEXT.md
    section 3.5 requires defects and oddities to be *reported*, not smoothed
    over. 'unsure' (rooms 605 and 609) is likewise stored as written.

    A previous revision had a normalised ``UNKNOWN = "unknown"`` member. It was
    a guess made before the real data was in hand, and the data never produces
    it, so migration 0002 removed it.

    **Not the same value set as the ingestion contract.**
    ``contracts/ingestion_v1.schema.json`` still declares
    ``rooms[].room_type`` as class | lab | unknown - a *normalised*
    classification, which is a different thing from this raw column. The
    Phase 2 parser therefore has to map between the two rather than passing a
    value straight through. Changing that contract needs all three members to
    agree, so it is deliberately untouched here.
    """

    CLASS = "class"
    LAB = "lab"
    UNSURE = "unsure"
    AS_A_LAB = "as a lab"
    MTECH_LAB = "Mtech lab"


class SubjectSessionType(enum.Enum):
    """A subject may have a theory component, a lab component, or both."""

    THEORY = "theory"
    LAB = "lab"
    BOTH = "both"


class SessionType(enum.Enum):
    """A single scheduled session is one or the other - never 'both'."""

    THEORY = "theory"
    LAB = "lab"


class QualificationSource(enum.Enum):
    OBSERVED = "observed"
    DECLARED = "declared"


class CohortType(enum.Enum):
    DIVISION = "division"
    BATCH = "batch"
    ELECTIVE = "elective"
    COMBINED = "combined"


class PinnedKind(enum.Enum):
    MDM = "mdm"
    HSS = "hss"
    LLC = "llc"
    ACTIVITY = "activity"
    PROJECT = "project"
    EXAM = "exam"
    BREAK = "break"


class TimetableStatus(enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    OBSERVED = "observed"  # ingested from the department's published timetable


# ---------------------------------------------------------------------------
# association tables
# ---------------------------------------------------------------------------

#: Faculty <-> Subject competence, many-to-many. Drives substitution: when a
#: faculty member is absent, candidates are the qualified-and-free set.
qualification = Table(
    "qualification",
    Base.metadata,
    Column("faculty_id", ForeignKey("faculty.id", ondelete="CASCADE"), primary_key=True),
    # index=True: the composite PK indexes faculty_id first, so "who else can
    # teach this subject?" - the substitution candidate query - has no index
    # without this one.
    Column(
        "subject_id",
        ForeignKey("subject.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column(
        "source",
        SAEnum(QualificationSource, name="qualification_source", values_callable=_values),
        nullable=False,
    ),
)

#: Cohort -> Division membership, with no fixed cardinality.
#:
#: 'DAA / SE C & D' is a CombinedDivisions over two divisions; 'PE-I-D' is an
#: ElectiveGroup that may span any number of them, and the count is not known
#: until the source file is parsed. Hence an association table rather than
#: columns like division_a_id / division_b_id.
cohort_division_membership = Table(
    "cohort_division_membership",
    Base.metadata,
    Column("cohort_id", ForeignKey("cohort.id", ondelete="CASCADE"), primary_key=True),
    # index=True: reverse lookup, "which cohorts contain this division?"
    Column(
        "division_id",
        ForeignKey("cohort.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)

#: Cohort -> Batch membership, the full expansion down to batch level.
#:
#: Two cohorts clash exactly when their batch sets intersect, which is how
#: COHORT edges are derived for ``contracts/edge_list_v1.schema.json``. For a
#: division or a combined division this is derivable by walking the hierarchy,
#: but an elective draws a *subset* of students from each division it spans, so
#: for electives it can only be stored, not computed.
cohort_batch_membership = Table(
    "cohort_batch_membership",
    Base.metadata,
    Column("cohort_id", ForeignKey("cohort.id", ondelete="CASCADE"), primary_key=True),
    # index=True: reverse lookup, "which cohorts contain this batch?" - the
    # query that derives COHORT conflict edges.
    Column(
        "batch_id",
        ForeignKey("cohort.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)


# ---------------------------------------------------------------------------
# academic hierarchy
# ---------------------------------------------------------------------------


class Institute(Base):
    __tablename__ = "institute"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    departments: Mapped[list[Department]] = relationship(back_populates="institute")
    rooms: Mapped[list[Room]] = relationship(back_populates="institute")


class Department(Base):
    __tablename__ = "department"
    __table_args__ = (
        UniqueConstraint("institute_id", "code", name="uq_department_institute_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    institute_id: Mapped[int] = mapped_column(ForeignKey("institute.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))

    institute: Mapped[Institute] = relationship(back_populates="departments")
    programmes: Mapped[list[Programme]] = relationship(back_populates="department")


class Programme(Base):
    __tablename__ = "programme"
    __table_args__ = (
        UniqueConstraint("department_id", "code", name="uq_programme_department_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))

    department: Mapped[Department] = relationship(back_populates="programmes")
    semesters: Mapped[list[Semester]] = relationship(back_populates="programme")


class Semester(Base):
    """One term of one programme, e.g. B.Tech semester IV of 2025-26 EVEN."""

    __tablename__ = "semester"
    __table_args__ = (
        CheckConstraint("number >= 1 AND number <= 10", name="number_range"),
        UniqueConstraint(
            "programme_id",
            "number",
            "academic_year",
            name="uq_semester_programme_number_year",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    programme_id: Mapped[int] = mapped_column(ForeignKey("programme.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    term_code: Mapped[TermCode] = mapped_column(
        SAEnum(TermCode, name="term_code", values_callable=_values)
    )
    academic_year: Mapped[str] = mapped_column(String(16))

    programme: Mapped[Programme] = relationship(back_populates="semesters")
    #: Read-only: writes go through Cohort.semester. Targeting the Division
    #: subclass makes SQLAlchemy add the cohort_type discriminator itself.
    divisions: Mapped[list[Division]] = relationship(
        "Division", foreign_keys="Cohort.semester_id", viewonly=True
    )


# ---------------------------------------------------------------------------
# rooms - institute-level, NO department_id (CONTEXT.md section 2 rule 5)
# ---------------------------------------------------------------------------


class Room(Base):
    """A physical room. Belongs to the institute, never to a department.

    Do not add ``department_id`` here. See the module docstring.
    """

    __tablename__ = "room"

    id: Mapped[int] = mapped_column(primary_key=True)
    institute_id: Mapped[int] = mapped_column(ForeignKey("institute.id"), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    capacity: Mapped[int] = mapped_column(Integer)
    used_as: Mapped[RoomUsedAs] = mapped_column(
        SAEnum(RoomUsedAs, name="room_used_as", values_callable=_values)
    )
    #: Raw 'separation' value from classrooms.xlsx, e.g. '20-20-20'. Kept
    #: verbatim; sub_rooms below is the parsed expansion.
    separation: Mapped[str | None] = mapped_column(String(64), nullable=True)

    institute: Mapped[Institute] = relationship(back_populates="rooms")
    sub_rooms: Mapped[list[SubRoom]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class SubRoom(Base):
    """A partition of a :class:`Room`, derived from its separation column.

    Institute-level like its parent - no ``department_id``.
    """

    __tablename__ = "sub_room"
    __table_args__ = (UniqueConstraint("room_id", "label", name="uq_sub_room_room_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("room.id", ondelete="CASCADE"), index=True)
    #: Plain string. The source mixes letters ('702-A') and digits ('603-2'),
    #: so no format is assumed or validated here - see CONTEXT.md section 3.4.
    label: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer)

    room: Mapped[Room] = relationship(back_populates="sub_rooms")


# ---------------------------------------------------------------------------
# people and subjects
# ---------------------------------------------------------------------------


class Faculty(Base):
    """A faculty member, owned by a department but schedulable institute-wide.

    ``department_id`` records who they belong to. Nothing at the ORM level
    filters sessions, substitutions or availability to that department - the
    real data has cross-department teaching, and a default filter here would
    silently hide it.
    """

    __tablename__ = "faculty"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    #: Initials as used in class-timetable cells ('KKD', 'AGN'). Nullable: the
    #: mapping is derived and human-verified, not guessed, and stays null until
    #: it is confirmed.
    initials: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    #: From the '6T+ 8P =14' workload line. All three are nullable because that
    #: line is absent on some faculty pages (anomaly MISSING_WORKLOAD), and the
    #: printed total is stored separately from theory+practical so an
    #: arithmetic error in the source stays visible instead of being corrected.
    theory_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    practical_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    department: Mapped[Department] = relationship()
    subjects: Mapped[list[Subject]] = relationship(
        secondary=qualification, back_populates="faculty"
    )


class Subject(Base):
    __tablename__ = "subject"
    __table_args__ = (UniqueConstraint("department_id", "code", name="uq_subject_department_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    #: Nullable, and null is the correct state for a freshly seeded subject.
    #:
    #: None of the three source spreadsheets states theory/lab/both for any
    #: subject. It is only observable from the timetable .docx files, where a
    #: subject's appearance in a lab cell versus a theory cell settles it, so
    #: **Phase 2 ingestion backfills this from real timetable cells**. It is
    #: not defaulted here: 'both' in particular is not a safe neutral, since it
    #: would make every subject look lab-capable to the room allocator.
    session_type: Mapped[SubjectSessionType | None] = mapped_column(
        SAEnum(SubjectSessionType, name="subject_session_type", values_callable=_values),
        nullable=True,
    )

    department: Mapped[Department] = relationship()
    faculty: Mapped[list[Faculty]] = relationship(
        secondary=qualification, back_populates="subjects"
    )


# ---------------------------------------------------------------------------
# cohorts - single-table inheritance
# ---------------------------------------------------------------------------


class Cohort(Base):
    """The student group a session is taught to; one vertex constituency.

    Four subtypes share this table, discriminated by ``cohort_type``. See the
    module docstring for why single-table inheritance was chosen.
    """

    __tablename__ = "cohort"
    __table_args__ = (
        # Recover the NOT NULL integrity that single-table inheritance costs us.
        CheckConstraint(
            "cohort_type <> 'division' OR semester_id IS NOT NULL",
            name="division_requires_semester",
        ),
        CheckConstraint(
            "cohort_type <> 'batch' OR division_id IS NOT NULL",
            name="batch_requires_division",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    cohort_type: Mapped[CohortType] = mapped_column(
        SAEnum(CohortType, name="cohort_type", values_callable=_values), index=True
    )
    #: Label exactly as printed: 'SE-Comp B', 'PE-I-D', 'SE C & D'.
    label: Mapped[str] = mapped_column(String(128), index=True)
    strength: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Division only - nullable at the DB level, enforced by CHECK above.
    semester_id: Mapped[int | None] = mapped_column(
        ForeignKey("semester.id"), nullable=True, index=True
    )
    #: Batch only - nullable at the DB level, enforced by CHECK above.
    division_id: Mapped[int | None] = mapped_column(
        ForeignKey("cohort.id"), nullable=True, index=True
    )

    department: Mapped[Department] = relationship()
    semester: Mapped[Semester | None] = relationship("Semester", foreign_keys=[semester_id])

    # Division <-> Batch is an adjacency list *within this one table*, because
    # single-table inheritance puts both subtypes in `cohort`. It is therefore
    # declared once here with remote_side rather than separately on the two
    # subclasses, where the self-join would be ambiguous. A Batch reads
    # `.division`; a Division reads `.batches`. The inverse on each is simply
    # empty.
    division: Mapped[Cohort | None] = relationship(
        "Cohort",
        remote_side=[id],
        foreign_keys=[division_id],
        back_populates="batches",
    )
    batches: Mapped[list[Cohort]] = relationship(
        "Cohort",
        foreign_keys=[division_id],
        back_populates="division",
    )

    #: Divisions this cohort is composed of. Populated for CombinedDivisions
    #: and ElectiveGroup; empty for a plain Division or Batch.
    member_divisions: Mapped[list[Division]] = relationship(
        "Division",
        secondary=cohort_division_membership,
        primaryjoin="Cohort.id == cohort_division_membership.c.cohort_id",
        secondaryjoin="Division.id == cohort_division_membership.c.division_id",
        viewonly=False,
    )

    #: Full batch-level expansion, used to derive COHORT conflict edges.
    member_batches: Mapped[list[Batch]] = relationship(
        "Batch",
        secondary=cohort_batch_membership,
        primaryjoin="Cohort.id == cohort_batch_membership.c.cohort_id",
        secondaryjoin="Batch.id == cohort_batch_membership.c.batch_id",
        viewonly=False,
    )

    __mapper_args__: ClassVar[dict[str, Any]] = {
        "polymorphic_on": cohort_type,
        "polymorphic_identity": None,
    }


class Division(Cohort):
    """A whole division, e.g. 'SE-Comp B'.

    Hangs off a :class:`Semester` via the inherited ``semester`` relationship,
    and owns its lab batches via the inherited ``batches`` adjacency list.
    """

    __mapper_args__: ClassVar[dict[str, Any]] = {"polymorphic_identity": CohortType.DIVISION}


class Batch(Cohort):
    """One lab batch (A-D) within a division.

    Reaches its parent through the inherited ``division`` relationship.
    """

    __mapper_args__: ClassVar[dict[str, Any]] = {"polymorphic_identity": CohortType.BATCH}


class ElectiveGroup(Cohort):
    """A cross-division elective cohort, e.g. 'PE-I-D', 'PE-II-A'..'PE-II-G'.

    Membership lives in :data:`cohort_division_membership` and
    :data:`cohort_batch_membership`; the number of divisions spanned is not
    known until the source file is parsed.
    """

    __mapper_args__: ClassVar[dict[str, Any]] = {"polymorphic_identity": CohortType.ELECTIVE}


class CombinedDivisions(Cohort):
    """Two or more divisions taught as one lecture, e.g. 'SE C & D'.

    A single vertex for the solver. Membership lives in
    :data:`cohort_division_membership`, with no fixed cardinality.
    """

    __mapper_args__: ClassVar[dict[str, Any]] = {"polymorphic_identity": CohortType.COMBINED}


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------


class Timetable(Base):
    __tablename__ = "timetable"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("semester.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[TimetableStatus] = mapped_column(
        SAEnum(TimetableStatus, name="timetable_status", values_callable=_values),
        default=TimetableStatus.DRAFT,
    )
    #: Null until the timetable has been scored by solver.scoring.
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    #: Which algorithm produced it, for the benchmark harness.
    algorithm: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="timetable", cascade="all, delete-orphan"
    )


class LabBlock(Base):
    """N batch-parallel sessions of one division that run simultaneously.

    Four batches, four subjects, four faculty, four rooms, one slot. Modelled
    as a block rather than N independent sessions so the contiguity constraint
    has somewhere to live. ``must_be_contiguous`` mirrors the field of the same
    name in ``contracts/edge_list_v1.schema.json``, where it is ``const: true``
    in v1; it is a column rather than a constant so a future revision can relax
    it without a migration.
    """

    __tablename__ = "lab_block"
    __table_args__ = (
        CheckConstraint("day >= 0 AND day <= 4", name="day_range"),
        # WALL-CLOCK 0-9. See the module docstring - not 0..7.
        CheckConstraint("start_period >= 0 AND start_period <= 9", name="start_period_range"),
        CheckConstraint("duration_periods >= 1", name="duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    division_id: Mapped[int] = mapped_column(ForeignKey("cohort.id"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    start_period: Mapped[int] = mapped_column(Integer)
    duration_periods: Mapped[int] = mapped_column(Integer, default=2)
    must_be_contiguous: Mapped[bool] = mapped_column(default=True, server_default="true")

    sessions: Mapped[list[Session]] = relationship(back_populates="lab_block")


class Session(Base):
    """One teaching event. The vertex the solver colours.

    ``room_id`` and ``sub_room_id`` are a mutually exclusive pair: a session
    occupies a whole room or one partition of it, never both. The CHECK
    constraint enforces that exclusivity but deliberately permits *neither* to
    be set - ``contracts/ingestion_v1.schema.json`` allows ``room_id: null``
    for a cell that named no room, or one absent from classrooms.xlsx, and the
    seeder has to be able to store that rather than drop the session.
    """

    __tablename__ = "session"
    __table_args__ = (
        CheckConstraint("day >= 0 AND day <= 4", name="day_range"),
        # WALL-CLOCK index 0-9, matching slot_grid in the edge-list contract and
        # solver.slots: 2 is the short break, 5 is lunch. NOT teaching-order
        # 0..7 - that axis belongs to the ingestion contract alone.
        CheckConstraint("period >= 0 AND period <= 9", name="period_range"),
        CheckConstraint("duration_periods >= 1", name="duration_positive"),
        CheckConstraint(
            "NOT (room_id IS NOT NULL AND sub_room_id IS NOT NULL)",
            name="room_xor_sub_room",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    timetable_id: Mapped[int] = mapped_column(
        ForeignKey("timetable.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[int] = mapped_column(ForeignKey("cohort.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id"), index=True)
    #: Nullable: ingestion may fail to resolve initials to a faculty member
    #: (anomaly UNRESOLVED_FACULTY_INITIALS) and still keeps the session.
    faculty_id: Mapped[int | None] = mapped_column(
        ForeignKey("faculty.id"), nullable=True, index=True
    )
    room_id: Mapped[int | None] = mapped_column(ForeignKey("room.id"), nullable=True, index=True)
    sub_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_room.id"), nullable=True, index=True
    )
    lab_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("lab_block.id", ondelete="SET NULL"), nullable=True, index=True
    )

    day: Mapped[int] = mapped_column(Integer)
    #: WALL-CLOCK period index 0-9. See the class and module docstrings.
    period: Mapped[int] = mapped_column(Integer)
    duration_periods: Mapped[int] = mapped_column(Integer, default=1)
    session_type: Mapped[SessionType] = mapped_column(
        SAEnum(SessionType, name="session_type", values_callable=_values)
    )
    #: Raw cell text, kept verbatim for traceability back to the .docx.
    source_cell: Mapped[str | None] = mapped_column(String(512), nullable=True)

    timetable: Mapped[Timetable] = relationship(back_populates="sessions")
    cohort: Mapped[Cohort] = relationship()
    subject: Mapped[Subject] = relationship()
    faculty: Mapped[Faculty | None] = relationship()
    room: Mapped[Room | None] = relationship()
    sub_room: Mapped[SubRoom | None] = relationship()
    lab_block: Mapped[LabBlock | None] = relationship(back_populates="sessions")


class PinnedBlock(Base):
    """Immovable occupancy: MDM, HSS, LLC, activity, project, exams, breaks.

    Carries no solver-assigned fields - it is an input constraint, never an
    output. ``department_id`` is nullable because an institute-wide block (a
    break) belongs to no single department.
    """

    __tablename__ = "pinned_block"
    __table_args__ = (
        CheckConstraint("day >= 0 AND day <= 4", name="day_range"),
        CheckConstraint("period >= 0 AND period <= 9", name="period_range"),
        CheckConstraint("duration_periods >= 1", name="duration_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id"), nullable=True, index=True
    )
    #: Null when the block holds a slot institute-wide rather than one cohort.
    cohort_id: Mapped[int | None] = mapped_column(
        ForeignKey("cohort.id"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    day: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    duration_periods: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[PinnedKind] = mapped_column(
        SAEnum(PinnedKind, name="pinned_kind", values_callable=_values)
    )

    cohort: Mapped[Cohort | None] = relationship()


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------


class AbsenceRecord(Base):
    """A faculty member unavailable for one slot on one date."""

    __tablename__ = "absence_record"
    __table_args__ = (
        CheckConstraint("day >= 0 AND day <= 4", name="day_range"),
        CheckConstraint("period >= 0 AND period <= 9", name="period_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id"), index=True)
    absence_date: Mapped[date] = mapped_column()
    day: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    #: Null until a substitution is confirmed, and stays null when no qualified
    #: faculty member is free - that path triggers freeze-and-expand repair.
    replacement_faculty_id: Mapped[int | None] = mapped_column(
        ForeignKey("faculty.id"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    faculty: Mapped[Faculty] = relationship(foreign_keys=[faculty_id])
    replacement_faculty: Mapped[Faculty | None] = relationship(
        foreign_keys=[replacement_faculty_id]
    )


class AuditEntry(Base):
    """Who changed what, when. Written on every mutating action.

    ``affected_session_ids`` is JSONB rather than an association table: the
    audit log is append-only and read as a whole record, never joined against,
    and keeping it denormalised means a session that is later deleted does not
    erase the history of it having been moved.
    """

    __tablename__ = "audit_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Null for an institute-wide administrative action.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    affected_session_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
