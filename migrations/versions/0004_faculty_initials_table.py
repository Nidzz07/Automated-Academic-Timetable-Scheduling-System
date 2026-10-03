"""faculty_initials: scoped, case-sensitive, ambiguity-preserving initials

Revision ID: 0004_faculty_initials
Revises: 0003_subject_type_null
Create Date: 2026-09-26

A single ``faculty.initials`` column cannot represent the real data. The class
timetable legends (ingestion/initials_legend_report.txt) show:

    SD, SM, SK   each name different people depending on division
                 (SD = Sonali Dudhihalli in SE, Surekha Dholay in TE)
    SK           ODD BE's legend lists BOTH Swapnali Kurhade and Suhas Kakade
    AsT / AT     Asma Tambe and Anuj Tawari - case is significant

So the column is replaced by ``faculty_initials`` - one row per (faculty,
initials, semester, division), with a ``source`` of legend | manual and an
``is_ambiguous`` flag. An ambiguous initial keeps every candidate row; this
schema never picks one.

Alongside it:

- ``faculty_alias`` records another spelling of an existing person, so a
  legend's 'Prof. Jotsna Bhagat' resolves to the 'Jostna Bhagat' row rather
  than creating a second person.
- ``faculty.source`` records provenance (spreadsheet | legend | manual). It is
  nullable: this migration cannot tell a spreadsheet row from a manual one, so
  existing rows stay null until the seeder is re-run.

Data: every non-null ``faculty.initials`` (the 8 seeded by
seed_reference.FACULTY_INITIALS) is copied into ``faculty_initials`` as an
unscoped ``manual`` row before the column is dropped.

The downgrade is lossy in principle - a scoped or ambiguous mapping, an alias,
or a legend-sourced person has no pre-0004 representation - so, like 0002 and
0003, it stops and reports what it would lose instead of discarding it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_faculty_initials"
down_revision: str | None = "0003_subject_type_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the types are created and dropped explicitly below, once
# each, because mapping_source is shared by two tables.
MAPPING_SOURCE = postgresql.ENUM("legend", "manual", name="mapping_source", create_type=False)
FACULTY_SOURCE = postgresql.ENUM(
    "spreadsheet", "legend", "manual", name="faculty_source", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    MAPPING_SOURCE.create(bind, checkfirst=False)
    FACULTY_SOURCE.create(bind, checkfirst=False)

    op.add_column("faculty", sa.Column("source", FACULTY_SOURCE, nullable=True))

    op.create_table(
        "faculty_initials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("faculty_id", sa.Integer(), nullable=False),
        sa.Column("initials", sa.String(length=16), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=True),
        sa.Column("division_id", sa.Integer(), nullable=True),
        sa.Column("source", MAPPING_SOURCE, nullable=False),
        sa.Column("is_ambiguous", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "division_id IS NULL OR semester_id IS NOT NULL",
            name=op.f("ck_faculty_initials_division_requires_semester"),
        ),
        sa.CheckConstraint(
            "source <> 'legend' OR division_id IS NOT NULL",
            name=op.f("ck_faculty_initials_legend_requires_division"),
        ),
        sa.ForeignKeyConstraint(
            ["faculty_id"],
            ["faculty.id"],
            name=op.f("fk_faculty_initials_faculty_id_faculty"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semester_id"],
            ["semester.id"],
            name=op.f("fk_faculty_initials_semester_id_semester"),
        ),
        sa.ForeignKeyConstraint(
            ["division_id"],
            ["cohort.id"],
            name=op.f("fk_faculty_initials_division_id_cohort"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faculty_initials")),
        sa.UniqueConstraint(
            "faculty_id",
            "initials",
            "semester_id",
            "division_id",
            name="uq_faculty_initials_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_faculty_initials_faculty_id"), "faculty_initials", ["faculty_id"])
    op.create_index(op.f("ix_faculty_initials_semester_id"), "faculty_initials", ["semester_id"])
    op.create_index(
        "ix_faculty_initials_division_initials",
        "faculty_initials",
        ["division_id", "initials"],
    )

    op.create_table(
        "faculty_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("faculty_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("source", MAPPING_SOURCE, nullable=False),
        sa.ForeignKeyConstraint(
            ["faculty_id"],
            ["faculty.id"],
            name=op.f("fk_faculty_alias_faculty_id_faculty"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faculty_alias")),
        sa.UniqueConstraint("faculty_id", "alias", name="uq_faculty_alias_faculty_alias"),
    )
    op.create_index(op.f("ix_faculty_alias_faculty_id"), "faculty_alias", ["faculty_id"])
    op.create_index(op.f("ix_faculty_alias_alias"), "faculty_alias", ["alias"])

    # Carry the existing unscoped initials across before the column goes.
    op.execute(
        sa.text(
            "INSERT INTO faculty_initials (faculty_id, initials, source, is_ambiguous) "
            "SELECT id, initials, 'manual', false FROM faculty WHERE initials IS NOT NULL"
        )
    )

    op.drop_index(op.f("ix_faculty_initials"), table_name="faculty")
    op.drop_column("faculty", "initials")


def _refuse_lossy_downgrade() -> None:
    """Name everything the single initials column could not hold."""
    bind = op.get_bind()
    checks = {
        "legend-scoped initials rows": (
            "SELECT count(*) FROM faculty_initials WHERE source = 'legend'"
        ),
        "scoped manual initials rows": (
            "SELECT count(*) FROM faculty_initials "
            "WHERE source = 'manual' AND semester_id IS NOT NULL"
        ),
        "faculty with more than one initials row": (
            "SELECT count(*) FROM (SELECT faculty_id FROM faculty_initials "
            "GROUP BY faculty_id HAVING count(*) > 1) AS multi"
        ),
        "faculty aliases": "SELECT count(*) FROM faculty_alias",
        "legend-sourced faculty": "SELECT count(*) FROM faculty WHERE source = 'legend'",
    }
    lost = {
        label: count
        for label, sql in checks.items()
        if (count := bind.execute(sa.text(sql)).scalar_one())
    }
    if lost:
        detail = ", ".join(f"{count} {label}" for label, count in lost.items())
        raise RuntimeError(
            f"cannot downgrade below 0004 without losing data: {detail}. A single "
            "faculty.initials column cannot express a scoped, ambiguous or "
            "legend-sourced mapping. Remove the legend seed first; this migration "
            "will not choose which mapping to keep."
        )


def downgrade() -> None:
    _refuse_lossy_downgrade()

    op.add_column("faculty", sa.Column("initials", sa.String(length=16), nullable=True))
    op.create_index(op.f("ix_faculty_initials"), "faculty", ["initials"])
    op.execute(
        sa.text(
            "UPDATE faculty SET initials = fi.initials FROM faculty_initials AS fi "
            "WHERE fi.faculty_id = faculty.id AND fi.source = 'manual'"
        )
    )

    op.drop_index(op.f("ix_faculty_alias_alias"), table_name="faculty_alias")
    op.drop_index(op.f("ix_faculty_alias_faculty_id"), table_name="faculty_alias")
    op.drop_table("faculty_alias")
    op.drop_index("ix_faculty_initials_division_initials", table_name="faculty_initials")
    op.drop_index(op.f("ix_faculty_initials_semester_id"), table_name="faculty_initials")
    op.drop_index(op.f("ix_faculty_initials_faculty_id"), table_name="faculty_initials")
    op.drop_table("faculty_initials")
    op.drop_column("faculty", "source")

    # drop_table does not remove Postgres ENUM types.
    bind = op.get_bind()
    FACULTY_SOURCE.drop(bind, checkfirst=False)
    MAPPING_SOURCE.drop(bind, checkfirst=False)
