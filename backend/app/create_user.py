"""Create an API user:  python -m backend.app.create_user <username> --role <role>
[--faculty <faculty id> | --cohort <cohort id>]

The password is read with getpass (typed twice, never echoed), so it never lands in a
file, the shell history or a chat. Writes to DATABASE_URL, local hosts only
(db.local_guard, the same rule as migrations/env.py).

S14c (ROADMAP D50): ``--faculty`` or ``--cohort`` links the account to one faculty member
or cohort of the real instance; the id must appear in that instance's edge list.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from backend.app.auth import hash_password
from backend.app.store import InstanceStore
from db.local_guard import local_database_url
from db.models import User, UserRole

MIN_PASSWORD_LENGTH = 8
REAL_INSTANCE = "even-2025-26"


def instance_ids(edge_list: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(faculty ids, cohort ids) an edge_list_v1 payload names: in its sessions, faculty
    availability and pinned occupancy."""
    faculty = {s["faculty_id"] for s in edge_list["sessions"]}
    faculty |= {e["faculty_id"] for e in edge_list["faculty_availability"]}
    cohorts = {s["cohort_id"] for s in edge_list["sessions"]}
    for pin in edge_list["pinned_occupancy"]:
        faculty |= set(pin["faculty_ids"])
        cohorts |= set(pin["cohort_ids"])
    return faculty, cohorts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Chronos API user.")
    parser.add_argument("username")
    parser.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    link = parser.add_mutually_exclusive_group()
    link.add_argument("--faculty", help=f"a faculty id of {REAL_INSTANCE}, e.g. fac-...")
    link.add_argument("--cohort", help=f"a cohort id of {REAL_INSTANCE}, e.g. coh-...")
    args = parser.parse_args(argv)
    if not 1 <= len(args.username) <= 64:
        print("username must be 1 to 64 characters", file=sys.stderr)
        return 1
    if args.faculty or args.cohort:
        faculty, cohorts = instance_ids(InstanceStore().read(REAL_INSTANCE, "edge_list"))
        if args.faculty and args.faculty not in faculty:
            print(f"no faculty {args.faculty!r} in {REAL_INSTANCE}", file=sys.stderr)
            return 1
        if args.cohort and args.cohort not in cohorts:
            print(f"no cohort {args.cohort!r} in {REAL_INSTANCE}", file=sys.stderr)
            return 1

    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"password must be at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("passwords do not match", file=sys.stderr)
        return 1

    engine = create_engine(local_database_url())
    try:
        with OrmSession(engine) as db:
            db.add(
                User(
                    username=args.username,
                    password_hash=hash_password(password),
                    role=UserRole(args.role),
                    faculty_ref=args.faculty,
                    cohort_ref=args.cohort,
                )
            )
            db.commit()
    except IntegrityError:
        print(f"user {args.username!r} already exists", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    linked = f" linked to {args.faculty or args.cohort}" if args.faculty or args.cohort else ""
    print(f"created {args.role} {args.username!r}{linked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
