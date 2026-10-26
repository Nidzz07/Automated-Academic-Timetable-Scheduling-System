"""Demo accounts and reset (S16b, ROADMAP D55):  python -m backend.app.demo_seed [--reset]

Creates, when missing, ``demo-admin`` (administrator), ``demo-coordinator``,
``demo-faculty`` (linked to fac-anant-nimkar) and ``demo-student`` (linked to coh-se-a,
D50), with the password in ``CHRONOS_DEMO_PASSWORD``: never prompted, never printed; the
script refuses to run without it. An account that exists is kept as it is, password
included, so a second run changes nothing.

``--reset`` then clears the accepted changes of even-2025-26 exactly as
``DELETE /instances/{id}/changes`` does (audited, actor ``demo_seed``; D56 picks the
official timetable) and runs one solve with the API's default budget to completion.

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

from backend.app.create_user import MIN_PASSWORD_LENGTH, REAL_INSTANCE, instance_ids, new_user
from backend.app.service import DEFAULT_MAX_MOVES, DEFAULT_TIME_LIMIT_S, ChronosService
from backend.app.store import InstanceStore
from db.local_guard import local_database_url
from db.models import User, UserRole

ACTOR = "demo_seed"
PASSWORD_VAR = "CHRONOS_DEMO_PASSWORD"
# (username, role, faculty link, cohort link)
ACCOUNTS = (
    ("demo-admin", UserRole.ADMINISTRATOR, None, None),
    ("demo-coordinator", UserRole.COORDINATOR, None, None),
    ("demo-faculty", UserRole.FACULTY, "fac-anant-nimkar", None),
    ("demo-student", UserRole.STUDENT, None, "coh-se-a"),
)


def seed_accounts(engine: Engine, password: str) -> None:
    faculty, cohorts = instance_ids(InstanceStore().read(REAL_INSTANCE, "edge_list"))
    with OrmSession(engine) as db:
        for username, role, fac, coh in ACCOUNTS:
            if (fac and fac not in faculty) or (coh and coh not in cohorts):
                raise SystemExit(f"no {fac or coh!r} in {REAL_INSTANCE}; nothing written")
            if db.scalar(select(User).where(User.username == username)) is not None:
                print(f"kept {username!r}: exists, unchanged")
                continue
            db.add(new_user(username, role, password, fac, coh))
            linked = f" linked to {fac or coh}" if fac or coh else ""
            print(f"created {role.value} {username!r}{linked}")
        db.commit()


def reset(engine: Engine) -> bool:
    """Clear the accepted changes, then solve to completion; True when the solve is
    solved and official."""
    service = ChronosService(InstanceStore(), engine)
    try:
        cleared = service.clear_changes(REAL_INSTANCE, ACTOR)
        print(f"cleared {len(cleared or [])} accepted change(s) of {REAL_INSTANCE}")
        job_id = service.start_solve(REAL_INSTANCE, DEFAULT_TIME_LIMIT_S, DEFAULT_MAX_MOVES,
                                     ACTOR)
        print(f"solving {REAL_INSTANCE} (job {job_id}, at most {DEFAULT_TIME_LIMIT_S:g} s)")
        while (job := service.job(job_id))["status"] in ("queued", "running"):
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
                        help=f"clear {REAL_INSTANCE}'s accepted changes, then solve it")
    args = parser.parse_args(argv)
    password = os.environ.get(PASSWORD_VAR, "")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"{PASSWORD_VAR} must be set, at least {MIN_PASSWORD_LENGTH} characters",
              file=sys.stderr)
        return 1
    engine = create_engine(local_database_url())
    try:
        seed_accounts(engine, password)
        return 0 if not args.reset or reset(engine) else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
