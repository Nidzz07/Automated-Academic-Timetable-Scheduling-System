"""Alembic environment for Chronos.

Two things this file does beyond the generated default.

**It resolves the database URL itself**, rather than reading
``sqlalchemy.url`` out of alembic.ini, so no connection string is ever
committed. Precedence:

1. the ``DATABASE_URL`` environment variable, if set;
2. ``DATABASE_URL`` in ``backend/.env``.

**It refuses to migrate a non-local database unless you say so explicitly.**
Supabase is shared staging for the whole team - three people running
``alembic upgrade head`` against one hosted instance corrupt each other's
schema state (CLAUDE.md, shared-database warning). Development and migrations
belong on the throwaway Docker Postgres. To promote a reviewed migration to
staging deliberately, set ``CHRONOS_ALLOW_REMOTE_DB=1`` for that one command::

    $env:CHRONOS_ALLOW_REMOTE_DB = "1"; alembic upgrade head

and unset it afterwards.
"""

from __future__ import annotations

import os
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Hosts treated as a developer's own throwaway database.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})


def _resolve_url() -> str:
    """Environment variable first, then backend/.env."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        load_dotenv(REPO_ROOT / "backend" / ".env")
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to backend/.env, or set "
            "DATABASE_URL for this command."
        )
    return url


def _host_of(url: str) -> str:
    match = re.search(r"@([^/:?]+)", url)
    return match.group(1) if match else ""


def _redact(url: str) -> str:
    return re.sub(r"//([^:]+):([^@]+)@", r"//\1:***@", url)


def _guard_remote(url: str) -> None:
    host = _host_of(url)
    if host in LOCAL_HOSTS:
        return
    if os.environ.get("CHRONOS_ALLOW_REMOTE_DB") == "1":
        print(f"[alembic] CHRONOS_ALLOW_REMOTE_DB=1 - proceeding against {host}")
        return
    raise SystemExit(
        f"\nRefusing to run migrations against '{host}'.\n\n"
        f"  resolved DATABASE_URL: {_redact(url)}\n\n"
        "This is not a local database. Supabase is shared staging for the whole\n"
        "team, and concurrent Alembic runs against it corrupt each other's schema\n"
        "state. Develop and migrate against the Docker Postgres:\n\n"
        "  docker compose up db -d\n"
        "  $env:DATABASE_URL = 'postgresql+psycopg2://chronos:chronos@localhost:5432/chronos'\n"
        "  alembic upgrade head\n\n"
        "If you really are promoting a reviewed migration to staging, set\n"
        "CHRONOS_ALLOW_REMOTE_DB=1 for that single command.\n"
    )


def run_migrations_offline() -> None:
    url = _resolve_url()
    _guard_remote(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _resolve_url()
    _guard_remote(url)

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Catch column type and server-default drift, which autogenerate
            # ignores by default.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
