"""app_user: API accounts with one role each (S13b)

Revision ID: 0006_app_user
Revises: 0005_instance_seed
Create Date: 2026-10-20

The API needs logins. One row per account: a unique username, a scrypt password
hash (never the password) and one of the four frontend roles. ``user`` is a
reserved word in Postgres, hence ``app_user``. Login attempts and solve requests
are audited in the existing ``audit_entry`` table (0001), which needs no change.

Like 0002-0005, the downgrade stops and reports what it would lose instead of
discarding accounts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_app_user"
down_revision: str | None = "0005_instance_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE = postgresql.ENUM(
    "administrator", "coordinator", "faculty", "student", name="user_role", create_type=False
)


def upgrade() -> None:
    USER_ROLE.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["department.id"],
            name=op.f("fk_app_user_department_id_department"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("username", name=op.f("uq_app_user_username")),
    )
    op.create_index(op.f("ix_app_user_department_id"), "app_user", ["department_id"])


def downgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM app_user")).scalar_one()
    if count:
        raise RuntimeError(
            f"cannot downgrade below 0006 without losing data: {count} user accounts. "
            "Delete them first; this migration will not discard them."
        )
    op.drop_index(op.f("ix_app_user_department_id"), table_name="app_user")
    op.drop_table("app_user")
    USER_ROLE.drop(op.get_bind(), checkfirst=False)
