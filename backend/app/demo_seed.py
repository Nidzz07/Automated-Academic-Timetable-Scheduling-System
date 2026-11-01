"""Demo accounts and reset (S16b, ROADMAP D55):
python -m backend.app.demo_seed [--reset | --solve]

Creates, when missing, ``demo-admin`` (administrator), ``demo-coordinator``,
``demo-faculty`` (linked to fac-anant-nimkar) and ``demo-student`` (linked to coh-se-a,
D50). Each account's password is ``CHRONOS_DEMO_PASSWORD_ADMIN``,
``_COORDINATOR``, ``_FACULTY`` or ``_STUDENT`` when set, else ``CHRONOS_DEMO_PASSWORD``:
never prompted, never printed; the script refuses to run unless every account has one of
at least 8 characters. Without ``--reset`` an account that exists is kept as it is,
password included, so a second run changes nothing.

``--reset`` sets every existing demo account's password again (S14r), so the known logins
come back, then clears the accepted changes of even-2025-26 exactly as
``DELETE /instances/{id}/changes`` does (audited, actor ``demo_seed``), then makes the
committed ``solution.json`` official without solving (S14y): one finished solve job, audited
as a solve by ``demo_seed``, so the demo starts from the timetable the docs measured.
``--solve`` does the same but runs one solve with the API's default budget to completion
instead, and that solve becomes official (D56).

Writes to DATABASE_URL, local hosts only (db.local_guard, as create_user). Run ``--reset``
while no API process is solving on the same database: like an API start, it marks jobs
left queued or running as ``error`` (ChronosService).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session as OrmSession

from backend.app.auth import hash_password
from backend.app.create_user import MIN_PASSWORD_LENGTH, REAL_INSTANCE, instance_ids, new_user
from backend.app.service import DEFAULT_MAX_MOVES, DEFAULT_TIME_LIMIT_S, ChronosService
from backend.app.store import InstanceStore
from db.local_guard import local_database_url
from db.models import User, UserRole

ACTOR = "demo_seed"
PASSWORD_VAR = "CHRONOS_DEMO_PASSWORD"
# (username, role, faculty link, cohort link, its own password variable)
ACCOUNTS = (
    ("demo-admin", UserRole.ADMINISTRATOR, None, None, f"{PASSWORD_VAR}_ADMIN"),
    ("demo-coordinator", UserRole.COORDINATOR, None, None, f"{PASSWORD_VAR}_COORDINATOR"),
    ("demo-faculty", UserRole.FACULTY, "fac-anant-nimkar", None, f"{PASSWORD_VAR}_FACULTY"),
    ("demo-student", UserRole.STUDENT, None, "coh-se-a", f"{PASSWORD_VAR}_STUDENT"),
)


def passwords() -> dict[str, str]:
    """Each demo username's password: its own variable, else ``CHRONOS_DEMO_PASSWORD``."""
    return {username: os.environ.get(own) or os.environ.get(PASSWORD_VAR, "")
            for username, *_, own in ACCOUNTS}


def seed_accounts(engine: Engine, password: dict[str, str], reset: bool = False) -> None:
    """Create the missing demo accounts; with *reset*, also set the others' passwords."""
    faculty, cohorts = instance_ids(InstanceStore().read(REAL_INSTANCE, "edge_list"))
    with OrmSession(engine) as db:
        for username, role, fac, coh, _ in ACCOUNTS:
            if (fac and fac not in faculty) or (coh and coh not in cohorts):
                raise SystemExit(f"no {fac or coh!r} in {REAL_INSTANCE}; nothing written")
            user = db.scalar(select(User).where(User.username == username))
            if user is not None and reset:
                user.password_hash = hash_password(password[username])
                print(f"reset the password of {username!r}")
                continue
            if user is not None:
                print(f"kept {username!r}: exists, unchanged")
                continue
            db.add(new_user(username, role, password[username], fac, coh))
            linked = f" linked to {fac or coh}" if fac or coh else ""
            print(f"created {role.value} {username!r}{linked}")
        db.commit()


def reset(engine: Engine, solve: bool = False) -> bool:
    """Clear the accepted changes, then restore the committed solution.json or, with
    *solve*, solve to completion; True when that job is solved and official."""
    service = ChronosService(InstanceStore(), engine)
    try:
        cleared = service.clear_changes(REAL_INSTANCE, ACTOR)
        print(f"cleared {len(cleared or [])} accepted change(s) of {REAL_INSTANCE}")
        if not solve:
            job_id = service.restore_committed(REAL_INSTANCE, ACTOR)
            print(f"restored the committed solution.json of {REAL_INSTANCE} (job {job_id})")
        else:
            job_id = service.start_solve(REAL_INSTANCE, DEFAULT_TIME_LIMIT_S, DEFAULT_MAX_MOVES,
                                         ACTOR)
            print(f"solving {REAL_INSTANCE} (job {job_id}, at most {DEFAULT_TIME_LIMIT_S:g} s)")
        while (job := service.job(job_id, details=True))["status"] in ("queued", "running"):
            time.sleep(0.5)
        official = job.get("solution") is not None and (
            service.solution(REAL_INSTANCE) == job["solution"])
    finally:
        service.close()
    print(f"job {job_id}: {job['status']}" + (", official" if official else ", NOT official")
          + (f" ({job['error']})" if job.get("error") else ""))
    return job["status"] == "solved" and official


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the demo accounts; reset the demo.")
    parser.add_argument("--reset", action="store_true",
                        help=f"clear {REAL_INSTANCE}'s accepted changes, then make its "
                        "committed solution.json official")
    parser.add_argument("--solve", action="store_true",
                        help="as --reset, but solve once at the default budget instead")
    args = parser.parse_args(argv)
    password = passwords()
    if missing := [u for u, p in password.items() if len(p) < MIN_PASSWORD_LENGTH]:
        print(f"{PASSWORD_VAR} (or the account's own {PASSWORD_VAR}_<ROLE>) must be set, at "
              f"least {MIN_PASSWORD_LENGTH} characters, for: {', '.join(missing)}",
              file=sys.stderr)
        return 1
    engine = create_engine(local_database_url())
    try:
        resetting = args.reset or args.solve
        seed_accounts(engine, password, reset=resetting)
        return 0 if not resetting or reset(engine, solve=args.solve) else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
