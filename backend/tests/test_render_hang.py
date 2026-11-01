"""S17b: the repair that hung on Render. A dead solver worker ends its job and the next job
gets a new pool; the worker count comes from CHRONOS_SOLVER_WORKERS; a request that cannot
get a database connection gets 503; requests return while a job runs in a worker.

The workers here are real processes, so the stand-in solve functions are module-level (a
spawned worker imports them by name) and are released through a file, not an Event.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import pytest

from backend.app import main as main_module
from backend.app import service as service_module
from backend.app.main import DB_UNAVAILABLE
from backend.app.service import WORKER_STOPPED, solver_workers
from backend.app.store import INSTANCES_DIR
from backend.tests.test_api import REAL, client_for, solve
from solver.benchmarks.synthetic import PRESETS, generate

RELEASE = "CHRONOS_TEST_RELEASE"  # the file whose existence lets held() return


def die(*_args: Any) -> None:
    """Runs in a pool worker: the process ends at once, as when killed for memory."""
    os._exit(1)


def held(*args: Any) -> tuple[str, None]:
    """Runs in a pool worker: running (its on_phase is the real database write) until the
    test creates the file named by RELEASE, then a timeout."""
    on_phase = args[-1]
    on_phase("search")
    release, deadline = Path(os.environ[RELEASE]), time.monotonic() + 60
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return "timeout", None


def small(root: Path, name: str) -> None:
    (root / name).mkdir()
    (root / name / "edge_list.json").write_text(
        json.dumps(generate(PRESETS["small"], 1)), encoding="utf-8")


@pytest.mark.parametrize("value, workers", [(None, 2), ("", 2), ("1", 1), ("3", 3)])
def test_solver_workers_reads_the_variable(
    monkeypatch: pytest.MonkeyPatch, value: str | None, workers: int
) -> None:
    if value is None:
        monkeypatch.delenv("CHRONOS_SOLVER_WORKERS", raising=False)
    else:
        monkeypatch.setenv("CHRONOS_SOLVER_WORKERS", value)
    assert solver_workers() == workers


@pytest.mark.parametrize("value", ["0", "-1"])
def test_solver_workers_refuses_below_one(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("CHRONOS_SOLVER_WORKERS", value)
    with pytest.raises(ValueError, match="at least 1"):
        solver_workers()


def test_dead_worker_ends_its_job_and_the_next_job_runs(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    small(tmp_path, "dead")
    monkeypatch.setenv("CHRONOS_SOLVER_WORKERS", "1")
    real_solve = service_module.solve_edge_list
    with client_for(tmp_path, database_url) as client:
        assert client.app.state.service._pool._max_workers == 1
        monkeypatch.setattr(service_module, "solve_edge_list", die)
        died = solve(client, "dead", max_moves=0)
        # plain, so every role sees it, not only an administrator
        assert (died["status"], died["error"]) == ("error", WORKER_STOPPED)

        monkeypatch.setattr(service_module, "solve_edge_list", real_solve)
        assert solve(client, "dead", max_moves=0)["status"] == "solved"


def test_no_free_connection_is_a_503(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "POOL_SIZE", 1)
    monkeypatch.setattr(main_module, "POOL_TIMEOUT_S", 0.5)
    with client_for(INSTANCES_DIR, database_url) as client:
        engine = client.app.state.service._engine
        with engine.connect():  # the pool's only connection
            began = time.monotonic()
            response = client.get(f"/instances/{REAL}/solution")
            assert time.monotonic() - began < 5
        assert (response.status_code, response.json()) == (503, {"detail": DB_UNAVAILABLE})
        assert client.get(f"/instances/{REAL}/solution").status_code == 200  # free again


def test_requests_return_while_a_job_runs(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    small(tmp_path, "busy")
    release = tmp_path / "release"
    monkeypatch.setenv(RELEASE, str(release))  # before the pool spawns its worker
    monkeypatch.setenv("CHRONOS_SOLVER_WORKERS", "1")
    monkeypatch.setattr(service_module, "solve_edge_list", held)
    caplog.set_level(logging.INFO, logger=service_module.__name__)
    with client_for(tmp_path, database_url) as client:
        first = client.post("/instances/busy/solve", json={"max_moves": 0}).json()["job_id"]
        deadline = time.monotonic() + 120
        while client.get(f"/jobs/{first}").json()["status"] != "running":
            assert time.monotonic() < deadline
            time.sleep(0.05)

        began = time.monotonic()
        second = client.post("/instances/busy/solve", json={"max_moves": 0})
        assert (second.status_code, second.json()["status"]) == (202, "queued")
        assert client.get("/instances").status_code == 200
        assert client.get(f"/jobs/{first}").json()["status"] == "running"
        assert time.monotonic() - began < 5

        release.touch()
        jobs = [first, second.json()["job_id"]]
        deadline = time.monotonic() + 120
        while any(client.get(f"/jobs/{j}").json()["status"] in ("queued", "running")
                  for j in jobs):
            assert time.monotonic() < deadline
            time.sleep(0.05)
    lines = [r.getMessage() for r in caplog.records if r.name == service_module.__name__]
    for job_id in jobs:
        [line] = [m for m in lines if m.startswith(f"job {job_id} solve: queued ")]
        assert line.endswith(" s, timeout") and "started -" not in line
