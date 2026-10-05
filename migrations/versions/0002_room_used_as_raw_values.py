"""room_used_as: store the raw 'used as' strings from classrooms.xlsx

Revision ID: 0002_room_used_as_raw
Revises: 1c8c78738a94
Create Date: 2026-09-25

Migration 0001 declared room_used_as as class | lab | unknown. That was a
normalisation invented before the real data was in hand. classrooms.xlsx
actually contains five distinct strings, and three of them had nowhere to go:

    'unsure'     rooms 605 and 609
    'as a lab'   room 703 and the 20-seat 507
    'Mtech lab'  room 607A

Folding 'as a lab' into 'lab' or 'unsure' into 'unknown' would erase exactly
the distinctions the anomaly reporter exists to surface ('Mtech lab' looks like
a real scheduling constraint, not a synonym), so the enum is widened to the
verbatim set instead. 'unknown' is dropped: nothing in the codebase constructs
it and the data never produces it.

NOTE, deliberately out of scope: contracts/ingestion_v1.schema.json still
declares rooms[].room_type as class | lab | unknown. That is a *normalised*
classification on the contract boundary, a different thing from this raw
column, and it is one of the three frozen contracts - changing it needs all
three members to agree. The Phase 2 parser maps between the two.

Postgres cannot remove a value from an existing enum, so the type is recreated
and the column cast across rather than altered in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_room_used_as_raw"
down_revision: str | None = "1c8c78738a94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_VALUES = ("class", "lab", "unknown")
NEW_VALUES = ("class", "lab", "unsure", "as a lab", "Mtech lab")

ENUM_NAME = "room_used_as"


def _swap_enum(new_values: tuple[str, ...], *, lost: tuple[str, ...]) -> None:
    """Recreate the enum type and cast room.used_as onto it.

    ``lost`` names values the target type does not contain. Any row still
    holding one would fail the cast with a bare Postgres error, so they are
    checked first and reported by room code.
    """
    bind = op.get_bind()

    if lost:
        placeholders = ", ".join(f"'{value}'" for value in lost)
        stranded = bind.execute(
            sa.text(
                f"SELECT code, used_as::text FROM room "  # noqa: S608 - fixed literals
                f"WHERE used_as::text IN ({placeholders})"
            )
        ).all()
        if stranded:
            detail = ", ".join(f"{code} ({value})" for code, value in stranded)
            raise RuntimeError(
                f"cannot convert room_used_as: {len(stranded)} room(s) still use a "
                f"value the target type does not have - {detail}. Reclassify these "
                "rows first; this migration will not guess a replacement."
            )

    op.execute(sa.text(f"ALTER TYPE {ENUM_NAME} RENAME TO {ENUM_NAME}_old"))
    sa.Enum(*new_values, name=ENUM_NAME).create(bind)
    op.execute(
        sa.text(
            f"ALTER TABLE room ALTER COLUMN used_as TYPE {ENUM_NAME} "
            f"USING used_as::text::{ENUM_NAME}"
        )
    )
    op.execute(sa.text(f"DROP TYPE {ENUM_NAME}_old"))


def upgrade() -> None:
    _swap_enum(NEW_VALUES, lost=("unknown",))


def downgrade() -> None:
    """Lossy in principle: the three added values have no pre-0002 equivalent.

    A room recorded as 'unsure', 'as a lab' or 'Mtech lab' cannot be expressed
    in the old type without inventing a classification, so the downgrade stops
    and names the rows rather than silently collapsing them.
    """
    _swap_enum(OLD_VALUES, lost=("unsure", "as a lab", "Mtech lab"))
