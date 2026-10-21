"""repair jobs and account links (S14c)

Revision ID: 0008_repair_and_links
Revises: 0007_solve_job
Create Date: 2026-10-21

``solve_job`` gains ``kind`` (``solve`` or ``repair``, existing rows are solves),
``base`` (the solution a repair started from: a job id or ``committed``),
``accepted_at`` (a repair made official, ROADMAP D49) and ``audit_id`` (the
request's audit row, so a job a restart interrupted can complete it).
``app_user`` gains ``faculty_ref`` and ``cohort_ref`` (ROADMAP D50: at most one
of them), edge-list ids rather than foreign keys because instances are files.

Like 0002-0007, the downgrade stops and reports what it would lose instead of
discarding repair jobs or account links. ``audit_id`` is dropped without a
check: the audit row's detail also names the job id.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_repair_and_links"
down_revision: str | None = "0007_solve_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("solve_job", sa.Column(
        "kind", sa.String(length=16), server_default="solve", nullable=False))
    op.add_column("solve_job", sa.Column("base", sa.String(length=32), nullable=True))
    op.add_column("solve_job", sa.Column(
        "accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("solve_job", sa.Column("audit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_solve_job_audit_id_audit_entry"), "solve_job", "audit_entry",
        ["audit_id"], ["id"],
    )
    op.add_column("app_user", sa.Column("faculty_ref", sa.String(length=128), nullable=True))
    op.add_column("app_user", sa.Column("cohort_ref", sa.String(length=128), nullable=True))
    op.create_check_constraint(
        op.f("ck_app_user_one_link"), "app_user", "faculty_ref IS NULL OR cohort_ref IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    repairs = bind.execute(
        sa.text("SELECT count(*) FROM solve_job WHERE kind = 'repair'")).scalar_one()
    links = bind.execute(sa.text(
        "SELECT count(*) FROM app_user WHERE faculty_ref IS NOT NULL OR cohort_ref IS NOT NULL"
    )).scalar_one()
    if repairs or links:
        raise RuntimeError(
            f"cannot downgrade below 0008 without losing data: {repairs} repair jobs, "
            f"{links} linked accounts. Delete or unlink them first; this migration will "
            "not discard them."
        )
    op.drop_constraint(op.f("ck_app_user_one_link"), "app_user", type_="check")
    op.drop_column("app_user", "cohort_ref")
    op.drop_column("app_user", "faculty_ref")
    op.drop_constraint(
        op.f("fk_solve_job_audit_id_audit_entry"), "solve_job", type_="foreignkey"
    )
    op.drop_column("solve_job", "audit_id")
    op.drop_column("solve_job", "accepted_at")
    op.drop_column("solve_job", "base")
    op.drop_column("solve_job", "kind")
