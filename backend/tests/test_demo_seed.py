"""S16b (ROADMAP D55): python -m backend.app.demo_seed creates the demo accounts once and
--reset clears the accepted changes and makes the committed solution.json official again
(S14y); --solve solves the real instance to an official timetable instead.

Its own scratch database: --reset makes a new official solution for even-2025-26, which
the shared one must not see.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from backend.app import demo_seed
from backend.app import service as service_module
from backend.app.auth import hash_password
from backend.app.store import INSTANCES_DIR
from backend.tests.conftest import bearer, scratch_database
from backend.tests.test_api import REAL, client_for
from backend.tests.test_repair import ROOM_603_MONDAY, accept, audit, run
from db.models import AuditEntry, SolveJob, User
from solver.validate import validate_solution

PASSWORD = "demo-pass-" + "x" * 8


@pytest.fixture(scope="module")
def url() -> Iterator[str]:
    yield from scratch_database("chronos_demo_seed_test")


@pytest.fixture
def env(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv(demo_seed.PASSWORD_VAR, PASSWORD)


@pytest.fixture(scope="module")
def client(url: str) -> Iterator[TestClient]:
    with client_for(INSTANCES_DIR, url) as c:
        yield c


def users(url: str) -> list[tuple]:
    engine = create_engine(url)
    try:
        with OrmSession(engine) as db:
            return [(u.username, u.role.value, u.faculty_ref, u.cohort_ref, u.password_hash)
                    for u in db.scalars(select(User).order_by(User.username))]
    finally:
        engine.dispose()


@pytest.mark.parametrize("password", [None, "short"])
def test_refuses_without_a_password(
    url: str, env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    password: str | None,
) -> None:
    if password is None:
        monkeypatch.delenv(demo_seed.PASSWORD_VAR)
    else:
        monkeypatch.setenv(demo_seed.PASSWORD_VAR, password)
    assert demo_seed.main([]) == 1
    assert users(url) == []
    assert "short" not in capsys.readouterr().out


def test_creates_once_then_changes_nothing(
    url: str, env: None, client: TestClient, capsys: pytest.CaptureFixture
) -> None:
    assert demo_seed.main([]) == 0
    first = users(url)
    assert [u[:4] for u in first] == [
        ("demo-admin", "administrator", None, None),
        ("demo-coordinator", "coordinator", None, None),
        ("demo-faculty", "faculty", "fac-anant-nimkar", None),
        ("demo-student", "student", None, "coh-se-a"),
    ]
    out = capsys.readouterr().out
    assert out.count("created") == 4 and PASSWORD not in out

    assert demo_seed.main([]) == 0
    assert users(url) == first
    out = capsys.readouterr().out
    assert out.count("kept") == 4 and "created" not in out

    login = client.post("/auth/login", json={"username": "demo-faculty", "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["faculty_id"] == "fac-anant-nimkar"


def rows(url: str) -> tuple[dict[str, SolveJob], dict[int, AuditEntry]]:
    """Every solve_job and audit_entry row, by id."""
    engine = create_engine(url)
    try:
        with OrmSession(engine, expire_on_commit=False) as db:
            return ({j.id: j for j in db.scalars(select(SolveJob))},
                    {a.id: a for a in db.scalars(select(AuditEntry))})
    finally:
        engine.dispose()


def test_reset_restores_the_committed_solution(
    url: str, env: None, client: TestClient, capsys: pytest.CaptureFixture
) -> None:
    """S14y: an accepted change is cleared and the official timetable is the committed
    solution.json again, recorded as one solved job without a solver run; no row is
    deleted and the demo passwords are set again."""
    committed = json.loads((INSTANCES_DIR / REAL / "solution.json").read_text("utf-8"))
    repaired = run(client, REAL, ROOM_603_MONDAY)
    assert repaired["status"] == "solved", repaired
    assert accept(client, repaired["id"]).status_code == 200
    assert len(client.get(f"/instances/{REAL}/changes").json()) == 1
    assert client.get(f"/instances/{REAL}/solution").json() != committed
    jobs, audits = rows(url)

    assert demo_seed.main(["--reset"]) == 0
    out = capsys.readouterr().out
    assert out.count("reset the password of") == 4 and PASSWORD not in out
    assert "cleared 1 accepted change(s)" in out and ", official" in out
    assert "restored the committed solution.json" in out and "solving" not in out

    assert client.get(f"/instances/{REAL}/changes").json() == []
    cleared = audit(url, demo_seed.ACTOR, "clear_changes")
    assert len(cleared) == 1 and '"cleared": 1' in cleared[0].detail
    jobs_after, audits_after = rows(url)
    assert jobs.keys() <= jobs_after.keys() and audits.keys() <= audits_after.keys()
    (new,) = (jobs_after[i] for i in jobs_after.keys() - jobs.keys())
    assert (new.kind, new.status, new.built_with, new.requested_by, new.params) == (
        "solve", "solved", [], demo_seed.ACTOR, {"source": "solution.json"})
    assert new.solution == committed and new.error is None
    solved = audit(url, demo_seed.ACTOR, "solve")
    assert [a.id for a in solved] == [new.audit_id]
    assert json.loads(solved[0].detail) | {"started_at": None, "ended_at": None} == {
        "instance_id": REAL, "job_id": new.id, "source": "solution.json",
        "status": "solved", "started_at": None, "ended_at": None}
    for job_id, job in jobs.items():  # earlier jobs: only the cleared change's cleared_at
        assert (job.status, job.solution, job.accepted_at) == (
            jobs_after[job_id].status, jobs_after[job_id].solution,
            jobs_after[job_id].accepted_at)
    assert all(audits_after[i].detail == a.detail for i, a in audits.items())

    official = client.get(f"/instances/{REAL}/solution", headers=bearer("student")).json()
    for key in ("assignment", "quality", "metadata"):
        assert official[key] == committed[key], key
    assert official == committed
    view = client.get(f"/jobs/{new.id}", headers=bearer("student")).json()
    assert (view["source"], view["status"], view["stale"]) == ("solution.json", "solved", False)
    assert "time_limit_s" not in view and "max_moves" not in view
    current = client.get(f"/instances/{REAL}/edge-list/current").json()
    assert validate_solution(current, official) == []


def test_solve_keeps_the_fresh_solve(
    url: str, env: None, client: TestClient, capsys: pytest.CaptureFixture
) -> None:
    """--solve clears the accepted changes and solves once at the default budget; that
    solve becomes official (D56) and no earlier row is deleted."""
    jobs, audits = rows(url)
    assert demo_seed.main(["--solve"]) == 0
    out = capsys.readouterr().out
    assert "solving" in out and ", official" in out and "restored" not in out
    jobs_after, audits_after = rows(url)
    assert jobs.keys() <= jobs_after.keys() and audits.keys() <= audits_after.keys()
    (job,) = (jobs_after[i] for i in jobs_after.keys() - jobs.keys())
    assert (job.kind, job.status, job.built_with, job.requested_by) == (
        "solve", "solved", [], demo_seed.ACTOR)
    assert job.params == {"time_limit_s": service_module.DEFAULT_TIME_LIMIT_S,
                          "max_moves": service_module.DEFAULT_MAX_MOVES}
    official = client.get(f"/instances/{REAL}/solution", headers=bearer("student")).json()
    assert official == job.solution
    current = client.get(f"/instances/{REAL}/edge-list/current").json()
    assert validate_solution(current, official) == []


def test_reset_restores_the_known_logins(
    url: str, env: None, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """S14r: --reset sets every demo account's password again, each role's own variable
    first, else CHRONOS_DEMO_PASSWORD; without --reset a changed password is kept."""
    def login(username: str, password: str) -> int:
        return client.post("/auth/login", json={"username": username, "password": password}
                           ).status_code

    assert demo_seed.main([]) == 0  # the accounts exist
    engine = create_engine(url)
    try:
        with OrmSession(engine) as db:
            for user in db.scalars(select(User)):
                user.password_hash = hash_password("changed-by-someone")
            db.commit()
        assert demo_seed.main([]) == 0
        assert login("demo-admin", "changed-by-someone") == 200  # kept without --reset

        admin_only = "admin-own-pass-" + "y" * 8
        monkeypatch.setenv(f"{demo_seed.PASSWORD_VAR}_ADMIN", admin_only)
        capsys.readouterr()
        demo_seed.seed_accounts(engine, demo_seed.passwords(), reset=True)  # --reset's step
    finally:
        engine.dispose()
    out = capsys.readouterr().out
    assert out.count("reset the password of") == 4
    assert PASSWORD not in out and admin_only not in out
    assert login("demo-admin", admin_only) == 200
    assert login("demo-admin", PASSWORD) == 401
    for username in ("demo-coordinator", "demo-faculty", "demo-student"):
        assert login(username, PASSWORD) == 200


def test_refuses_a_short_role_password(
    env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv(f"{demo_seed.PASSWORD_VAR}_STUDENT", "short")
    assert demo_seed.main(["--reset"]) == 1
    err = capsys.readouterr().err
    assert "demo-student" in err and "demo-admin" not in err
    assert "short" not in err  # the password itself is never printed
