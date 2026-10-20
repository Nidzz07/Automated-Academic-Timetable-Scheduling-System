"""Create an API user:  python -m backend.app.create_user <username> --role <role>

The password is read with getpass (typed twice, never echoed), so it never lands in a
file, the shell history or a chat. Writes to DATABASE_URL, local hosts only
(db.local_guard, the same rule as migrations/env.py).
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from backend.app.auth import hash_password
from db.local_guard import local_database_url
from db.models import User, UserRole

MIN_PASSWORD_LENGTH = 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Chronos API user.")
    parser.add_argument("username")
    parser.add_argument("--role", required=True, choices=[r.value for r in UserRole])
    args = parser.parse_args(argv)
    if not 1 <= len(args.username) <= 64:
        print("username must be 1 to 64 characters", file=sys.stderr)
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
                )
            )
            db.commit()
    except IntegrityError:
        print(f"user {args.username!r} already exists", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"created {args.role} {args.username!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
