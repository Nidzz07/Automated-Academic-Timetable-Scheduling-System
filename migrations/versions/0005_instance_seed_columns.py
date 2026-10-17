"""Columns the EVEN instance seed (S9) needs and the models could not hold

Revision ID: 0005_instance_seed
Revises: 0004_faculty_initials
Create Date: 2026-10-18

The S9 seeder loads the real EVEN SE+TE instance (ingestion.v2 payload plus its
D39 side file) and the exporter turns it back into an edge list. The 0004
schema could not hold:

- **a pinned block's teacher, room and timetable.** Out-of-scope sessions (D35)
  block a CE teacher and room, exam blocks (D37) a room; ``pinned_block`` held a
  cohort only, and named no timetable. Added: ``timetable_id``, ``faculty_id``,
  ``room_id`` / ``sub_room_id`` (exclusive, as on ``session``), ``source_ref``,
  and the kind ``out_of_scope``.
- **a frozen session.** Frozen observed sessions (D24, D26, D44) keep their
  subject, teacher, cohort and room, so they stay ``session`` rows with
  ``frozen_by`` = the decision id (null: the solver places it).
- **faculty unavailability** printed in a timetable (D36): new table
  ``faculty_unavailability``.
- **the room set a timetable may use** (D8, D10, D42): rooms are institute-level,
  so the set is a new association table ``timetable_room``.
- **a term-wide timetable.** EVEN 2025-26 spans SE (semester IV) and TE
  (semester VI); ``timetable.semester_id`` becomes nullable and the timetable
  carries ``term_code`` and ``academic_year`` instead (a CHECK keeps one of them).
- **stable ids.** ``source_ref`` on ``cohort``, ``session``, ``lab_block`` and
  ``pinned_block`` keeps the payload's id, so re-seeding updates rows in place
  and the exporter emits the same ids every time.

Like 0002-0004, the downgrade stops and reports what it would lose instead of
discarding it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_instance_seed"
down_revision: str | None = "0004_faculty_initials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERM_CODE = postgresql.ENUM("ODD", "EVEN", name="term_code", create_type=False)
OLD_PINNED_KINDS = ("mdm", "hss", "llc", "activity", "project", "exam", "break")


def upgrade() -> None:
    op.execute("ALTER TYPE pinned_kind ADD VALUE 'out_of_scope'")

    op.add_column("timetable", sa.Column("term_code", TERM_CODE, nullable=True))
    op.add_column("timetable", sa.Column("academic_year", sa.String(length=16), nullable=True))
    op.alter_column("timetable", "semester_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        op.f("ck_timetable_semester_or_term"),
        "timetable",
        "semester_id IS NOT NULL OR (term_code IS NOT NULL AND academic_year IS NOT NULL)",
    )

    op.add_column("cohort", sa.Column("source_ref", sa.String(length=128), nullable=True))
    op.add_column("lab_block", sa.Column("source_ref", sa.String(length=128), nullable=True))

    op.add_column("session", sa.Column("source_ref", sa.String(length=128), nullable=True))
    op.add_column("session", sa.Column("frozen_by", sa.String(length=8), nullable=True))
    op.create_unique_constraint(
        "uq_session_timetable_source_ref", "session", ["timetable_id", "source_ref"]
    )

    op.add_column("pinned_block", sa.Column("timetable_id", sa.Integer(), nullable=True))
    op.add_column("pinned_block", sa.Column("faculty_id", sa.Integer(), nullable=True))
    op.add_column("pinned_block", sa.Column("room_id", sa.Integer(), nullable=True))
    op.add_column("pinned_block", sa.Column("sub_room_id", sa.Integer(), nullable=True))
    op.add_column("pinned_block", sa.Column("source_ref", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        op.f("fk_pinned_block_timetable_id_timetable"), "pinned_block", "timetable",
        ["timetable_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_pinned_block_faculty_id_faculty"), "pinned_block", "faculty",
        ["faculty_id"], ["id"],
    )
    op.create_foreign_key(
        op.f("fk_pinned_block_room_id_room"), "pinned_block", "room", ["room_id"], ["id"]
    )
    op.create_foreign_key(
        op.f("fk_pinned_block_sub_room_id_sub_room"), "pinned_block", "sub_room",
        ["sub_room_id"], ["id"],
    )
    op.create_index(op.f("ix_pinned_block_timetable_id"), "pinned_block", ["timetable_id"])
    op.create_index(op.f("ix_pinned_block_faculty_id"), "pinned_block", ["faculty_id"])
    op.create_check_constraint(
        op.f("ck_pinned_block_room_xor_sub_room"),
        "pinned_block",
        "NOT (room_id IS NOT NULL AND sub_room_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_pinned_block_timetable_source_ref", "pinned_block", ["timetable_id", "source_ref"]
    )

    op.create_table(
        "faculty_unavailability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timetable_id", sa.Integer(), nullable=False),
        sa.Column("faculty_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "day >= 0 AND day <= 4", name=op.f("ck_faculty_unavailability_day_range")
        ),
        sa.CheckConstraint(
            "period >= 0 AND period <= 9", name=op.f("ck_faculty_unavailability_period_range")
        ),
        sa.ForeignKeyConstraint(
            ["timetable_id"], ["timetable.id"],
            name=op.f("fk_faculty_unavailability_timetable_id_timetable"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["faculty_id"], ["faculty.id"],
            name=op.f("fk_faculty_unavailability_faculty_id_faculty"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faculty_unavailability")),
        sa.UniqueConstraint(
            "timetable_id", "faculty_id", "day", "period", name="uq_faculty_unavailability_slot"
        ),
    )
    op.create_index(
        op.f("ix_faculty_unavailability_timetable_id"), "faculty_unavailability", ["timetable_id"]
    )
    op.create_index(
        op.f("ix_faculty_unavailability_faculty_id"), "faculty_unavailability", ["faculty_id"]
    )

    op.create_table(
        "timetable_room",
        sa.Column("timetable_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["timetable_id"], ["timetable.id"],
            name=op.f("fk_timetable_room_timetable_id_timetable"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["room.id"], name=op.f("fk_timetable_room_room_id_room"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("timetable_id", "room_id", name=op.f("pk_timetable_room")),
    )
    op.create_index(op.f("ix_timetable_room_room_id"), "timetable_room", ["room_id"])


def _refuse_lossy_downgrade() -> None:
    """Name everything the 0004 schema could not hold."""
    bind = op.get_bind()
    checks = {
        "faculty unavailability rows": "SELECT count(*) FROM faculty_unavailability",
        "timetable room rows": "SELECT count(*) FROM timetable_room",
        "term-wide timetables": "SELECT count(*) FROM timetable WHERE semester_id IS NULL",
        "out_of_scope pinned blocks": (
            "SELECT count(*) FROM pinned_block WHERE kind = 'out_of_scope'"
        ),
        "pinned blocks with a timetable, teacher, room or source ref": (
            "SELECT count(*) FROM pinned_block WHERE timetable_id IS NOT NULL OR faculty_id "
            "IS NOT NULL OR room_id IS NOT NULL OR sub_room_id IS NOT NULL "
            "OR source_ref IS NOT NULL"
        ),
        "frozen or source-referenced sessions": (
            "SELECT count(*) FROM session WHERE frozen_by IS NOT NULL OR source_ref IS NOT NULL"
        ),
        "source-referenced cohorts": "SELECT count(*) FROM cohort WHERE source_ref IS NOT NULL",
        "source-referenced lab blocks": (
            "SELECT count(*) FROM lab_block WHERE source_ref IS NOT NULL"
        ),
    }
    lost = {
        label: count
        for label, sql in checks.items()
        if (count := bind.execute(sa.text(sql)).scalar_one())
    }
    if lost:
        detail = ", ".join(f"{count} {label}" for label, count in lost.items())
        raise RuntimeError(
            f"cannot downgrade below 0005 without losing data: {detail}. Remove the "
            "instance seed (ingestion.seed_even) first; this migration will not discard it."
        )


def downgrade() -> None:
    _refuse_lossy_downgrade()

    op.drop_index(op.f("ix_timetable_room_room_id"), table_name="timetable_room")
    op.drop_table("timetable_room")
    op.drop_index(
        op.f("ix_faculty_unavailability_faculty_id"), table_name="faculty_unavailability"
    )
    op.drop_index(
        op.f("ix_faculty_unavailability_timetable_id"), table_name="faculty_unavailability"
    )
    op.drop_table("faculty_unavailability")

    op.drop_constraint("uq_pinned_block_timetable_source_ref", "pinned_block", type_="unique")
    op.drop_constraint(op.f("ck_pinned_block_room_xor_sub_room"), "pinned_block", type_="check")
    op.drop_index(op.f("ix_pinned_block_faculty_id"), table_name="pinned_block")
    op.drop_index(op.f("ix_pinned_block_timetable_id"), table_name="pinned_block")
    for fk in ("sub_room_id_sub_room", "room_id_room", "faculty_id_faculty",
               "timetable_id_timetable"):
        op.drop_constraint(op.f(f"fk_pinned_block_{fk}"), "pinned_block", type_="foreignkey")
    for column in ("source_ref", "sub_room_id", "room_id", "faculty_id", "timetable_id"):
        op.drop_column("pinned_block", column)

    op.drop_constraint("uq_session_timetable_source_ref", "session", type_="unique")
    op.drop_column("session", "frozen_by")
    op.drop_column("session", "source_ref")
    op.drop_column("lab_block", "source_ref")
    op.drop_column("cohort", "source_ref")

    op.drop_constraint(op.f("ck_timetable_semester_or_term"), "timetable", type_="check")
    op.alter_column("timetable", "semester_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("timetable", "academic_year")
    op.drop_column("timetable", "term_code")

    # Postgres cannot drop one value from an enum: rebuild the type without it.
    op.execute("ALTER TYPE pinned_kind RENAME TO pinned_kind_0005")
    values = ", ".join(f"'{v}'" for v in OLD_PINNED_KINDS)
    op.execute(f"CREATE TYPE pinned_kind AS ENUM ({values})")
    op.execute(
        "ALTER TABLE pinned_block ALTER COLUMN kind TYPE pinned_kind USING kind::text::pinned_kind"
    )
    op.execute("DROP TYPE pinned_kind_0005")
