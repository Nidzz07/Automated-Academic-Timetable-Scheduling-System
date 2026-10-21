"""solve_job: API solve jobs and their results (S13d)

Revision ID: 0007_solve_job
Revises: 0006_app_user
Create Date: 2026-10-21

Solve jobs lived in the API process's memory and died with it. One row per job:
the instance, who asked, status, phase while running, the request parameters,
timestamps, the solution.v2 payload (solved or infeasible) and the error.
``department_id`` is nullable, as on ``audit_entry`` and ``app_user``.

Like 0002-0006, the downgrade stops and reports what it would lose instead of
discarding jobs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_solve_job"
down_revision: str | None = "0006_app_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solve_job",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("instance_id", sa.String(length=128), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("solution", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["department_id"], ["department.id"],
            name=op.f("fk_solve_job_department_id_department"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solve_job")),
    )
    op.create_index(op.f("ix_solve_job_department_id"), "solve_job", ["department_id"])
    op.create_index(op.f("ix_solve_job_instance_id"), "solve_job", ["instance_id"])


def downgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM solve_job")).scalar_one()
    if count:
        raise RuntimeError(
            f"cannot downgrade below 0007 without losing data: {count} solve jobs. "
            "Delete them first; this migration will not discard them."
        )
    op.drop_index(op.f("ix_solve_job_instance_id"), table_name="solve_job")
    op.drop_index(op.f("ix_solve_job_department_id"), table_name="solve_job")
    op.drop_table("solve_job")
