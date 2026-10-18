"""The database URL for scripts that write or read the instance, local only.

Same rule as ``migrations/env.py``: ``DATABASE_URL`` from the environment, else
from ``backend/.env``; any host other than a developer's own database is refused
unless ``CHRONOS_ALLOW_REMOTE_DB=1`` is set for that one command (Supabase is
shared staging; touching it is a deliberate human decision).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Hosts treated as a developer's own throwaway database (as migrations/env.py).
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})


def host_of(url: str) -> str:
    match = re.search(r"@([^/:?]+)", url)
    return match.group(1) if match else ""


def local_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        load_dotenv(REPO_ROOT / "backend" / ".env")
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set; point it at the local Docker Postgres.")
    host = host_of(url)
    if host not in LOCAL_HOSTS and os.environ.get("CHRONOS_ALLOW_REMOTE_DB") != "1":
        raise SystemExit(
            f"Refusing to use the database on '{host}': not local. Use the Docker Postgres "
            "(see CLAUDE.md); a shared database needs CHRONOS_ALLOW_REMOTE_DB=1, a human decision."
        )
    return url
