"""S16b (ROADMAP D55): python -m backend.app.demo_seed creates the demo accounts once and
--reset clears the accepted changes and solves the real instance to an official timetable.

Its own scratch database: --reset makes a new official solution for even-2025-26, which
the shared one must not see.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from backend.app import demo_seed
from backend.app.store import INSTANCES_DIR
from backend.tests.conftest import bearer, scratch_database
from backend.tests.test_api import REAL, client_for
from backend.tests.test_repair import ROOM_603_MONDAY, accept, audit, run
from db.models import SolveJob, User
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


def test_reset_clears_changes_and_leaves_a_valid_official_solve(
    url: str, env: None, client: TestClient, capsys: pytest.CaptureFixture
) -> None:
    repaired = run(client, REAL, ROOM_603_MONDAY)
    assert repaired["status"] == "solved", repaired
    assert accept(client, repaired["id"]).status_code == 200
    assert len(client.get(f"/instances/{REAL}/changes").json()) == 1

    assert demo_seed.main(["--reset"]) == 0
    out = capsys.readouterr().out
    assert "cleared 1 accepted change(s)" in out and ", official" in out

    assert client.get(f"/instances/{REAL}/changes").json() == []
    cleared = audit(url, demo_seed.ACTOR, "clear_changes")
    assert len(cleared) == 1 and '"cleared": 1' in cleared[0].detail
    engine = create_engine(url)
    try:
        with OrmSession(engine) as db:
            job = db.scalars(select(SolveJob).where(SolveJob.requested_by == demo_seed.ACTOR)).one()
            assert (job.kind, job.status, job.built_with) == ("solve", "solved", [])
    finally:
        engine.dispose()
    official = client.get(f"/instances/{REAL}/solution", headers=bearer("student")).json()
    assert official == job.solution
    current = client.get(f"/instances/{REAL}/edge-list/current").json()
    assert validate_solution(current, official) == []
