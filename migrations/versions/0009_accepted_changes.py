"""accepted changes accumulate (S14f)

Revision ID: 0009_accepted_changes
Revises: 0008_repair_and_links
Create Date: 2026-10-23

ROADMAP D52: accepted faculty and room unavailability changes are part of every
later solve and repair until an administrator clears them. ``solve_job`` gains
``accepted_by`` (who made a repair official), ``cleared_at`` (when its accepted
change was cleared) and ``built_with`` (the job ids of the accepted changes a
job's edge list was built with, in acceptance order).

Like 0002-0008, the downgrade stops and reports what it would lose instead of
discarding it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_accepted_changes"
down_revision: str | None = "0008_repair_and_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("solve_job", sa.Column("accepted_by", sa.String(length=255), nullable=True))
    op.add_column("solve_job", sa.Column(
        "cleared_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("solve_job", sa.Column(
        "built_with", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    lost = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM solve_job WHERE accepted_by IS NOT NULL "
        "OR cleared_at IS NOT NULL OR built_with IS NOT NULL"
    )).scalar_one()
    if lost:
        raise RuntimeError(
            f"cannot downgrade below 0009 without losing data: {lost} solve jobs record "
            "who accepted them, a cleared change or the accepted changes they were built "
            "with. Delete them first; this migration will not discard them."
        )
    op.drop_column("solve_job", "built_with")
    op.drop_column("solve_job", "cleared_at")
    op.drop_column("solve_job", "accepted_by")
