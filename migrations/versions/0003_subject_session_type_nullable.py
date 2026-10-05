"""Subject.session_type nullable until Phase 2 ingestion can determine it

Revision ID: 0003_subject_type_null
Revises: 0002_room_used_as_raw
Create Date: 2026-09-25

None of the three source spreadsheets states theory/lab/both for any subject.
That is only observable from the timetable .docx files, where a subject
appearing in a lab cell versus a theory cell settles it - so the column is made
nullable and Phase 2 ingestion backfills it from real timetable cells.

The alternative was defaulting 23 seeded rows to a guess. 'both' is not a safe
neutral: it would make every subject look lab-capable to the room allocator,
and a wrong value here is invisible until the solver produces a timetable that
puts a theory lecture in a 20-seat lab.

The downgrade cannot restore NOT NULL while rows hold null, so it reports the
affected subject codes instead of inventing a value for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_subject_type_null"
down_revision: str | None = "0002_room_used_as_raw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_TYPE = sa.Enum("theory", "lab", "both", name="subject_session_type")


def upgrade() -> None:
    op.alter_column(
        "subject",
        "session_type",
        existing_type=SESSION_TYPE,
        nullable=True,
    )


def downgrade() -> None:
    unset = op.get_bind().execute(
        sa.text("SELECT code FROM subject WHERE session_type IS NULL ORDER BY code")
    ).scalars().all()
    if unset:
        raise RuntimeError(
            f"cannot restore NOT NULL on subject.session_type: {len(unset)} subject(s) "
            f"have no session_type yet - {', '.join(unset)}. Phase 2 ingestion fills "
            "these in from the timetable .docx files; this migration will not default "
            "them to a guess."
        )
    op.alter_column(
        "subject",
        "session_type",
        existing_type=SESSION_TYPE,
        nullable=False,
    )
