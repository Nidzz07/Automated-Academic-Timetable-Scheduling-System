"""Shared fixtures: a scratch database on the LOCAL Docker Postgres, and signed tokens.

Connection as db/tests/test_models.py: ``CHRONOS_TEST_DATABASE_URL``, else the chronos
credentials on ``CHRONOS_DB_PORT``. Tests that need the database skip when it is not
reachable (a skip is not a pass) and refuse a non-local host.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.app.auth import Actor, AuthSettings, issue_token
from db.local_guard import LOCAL_HOSTS, host_of
from db.models import Base, UserRole

DB_NAME = "chronos_backend_test"
AUTH = AuthSettings("test-only-secret-" + "0" * 32, expire_minutes=5)


def bearer(role: str, username: str | None = None) -> dict[str, str]:
    """An Authorization header for a token of *role* (no account needed: tokens are
    stateless)."""
    token = issue_token(Actor(username or f"test-{role}", UserRole(role)), AUTH)
    return {"Authorization": f"Bearer {token}"}


def pytest_configure(config: pytest.Config) -> None:
    # pyproject's addopts deselects these; run them with -m slow
    config.addinivalue_line("markers", "slow: runs longer than 60 s (the full Kurhade explanation)")


def _base_url() -> str:
    override = os.environ.get("CHRONOS_TEST_DATABASE_URL")
    if override:
        return override
    port = os.environ.get("CHRONOS_DB_PORT", "5432")
    return f"postgresql+psycopg2://chronos:chronos@127.0.0.1:{port}/chronos"


def _with_database(url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?|$)", f"/{name}\\1", url)


def _drop(conn) -> None:
    conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": DB_NAME})
    conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A fresh database with every table, dropped after the session."""
    base = _base_url()
    host = host_of(base)
    if host not in LOCAL_HOSTS:
        pytest.skip(f"refusing to create a scratch database on non-local host {host!r}")
    admin = create_engine(_with_database(base, "postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            _drop(conn)
            conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    except OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"local Postgres not reachable ({exc.__class__.__name__}); "
                    "start it with `docker compose up db -d`")
    url = _with_database(base, DB_NAME)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url
    with admin.connect() as conn:
        _drop(conn)
    admin.dispose()
