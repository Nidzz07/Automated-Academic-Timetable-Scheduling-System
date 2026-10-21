"""S13a API: every endpoint, contract-checked responses, the job lifecycle and 404s.

Solves use synthetic presets (D19) in a scratch instance directory. S13d: the real
EVEN instance is solved and improved under another id in a scratch directory, so the
committed solution stays what is served for ``even-2025-26``; jobs are database rows.
Every client carries a coordinator token (S13b); auth itself is tested in test_auth.py.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from backend.app import service as service_module
from backend.app.main import create_app
from backend.app.service import MAX_MAX_MOVES, solve_edge_list
from backend.app.store import INSTANCES_DIR, InstanceStore
from backend.tests.conftest import AUTH, bearer
from db.models import AuditEntry, SolveJob
from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.validate import validate_solution

REPO = Path(__file__).resolve().parents[2]
REAL = "even-2025-26"


def conforms(contract: str, payload: Any) -> bool:
    schema = json.loads((REPO / "contracts" / f"{contract}.schema.json").read_text("utf-8"))
    return not list(Draft202012Validator(schema).iter_errors(payload))


def client_for(root: Path, database_url: str) -> TestClient:
    app = create_app(root, database_url=database_url, auth=AUTH)
    return TestClient(app, headers=bearer("coordinator"))


@pytest.fixture(scope="module")
def real(database_url: str) -> Iterator[TestClient]:
    with client_for(INSTANCES_DIR, database_url) as client:
        yield client


@pytest.fixture(scope="module")
def synthetic(
    tmp_path_factory: pytest.TempPathFactory, database_url: str
) -> Iterator[TestClient]:
    root = tmp_path_factory.mktemp("instances")
    broken = generate(PRESETS["small"], 1)
    broken["lab_blocks"][0]["session_ids"].append("ghost")  # schema-valid, solver rejects it
    edge_lists = {
        "small": generate(PRESETS["small"], 1),
        "timeout": generate(PRESETS["small"], 1),
        "infeasible": generate(PRESETS["infeasible"], 1),
        "broken": broken,
    }
    for name, edge_list in edge_lists.items():
        (root / name).mkdir()
        (root / name / "edge_list.json").write_text(json.dumps(edge_list), encoding="utf-8")
    with client_for(root, database_url) as client:
        yield client


def solve(
    client: TestClient, instance: str, time_limit_s: float = 60.0, **body: Any
) -> dict[str, Any]:
    """POST a solve, then poll the job until it leaves queued/running."""
    accepted = client.post(
        f"/instances/{instance}/solve", json={"time_limit_s": time_limit_s, **body}
    )
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    deadline = time.monotonic() + 120
    while (job := client.get(f"/jobs/{job_id}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
    assert job["id"] == job_id and job["instance_id"] == instance
    assert "phase" not in job  # only while running
    return job


def test_health(real: TestClient) -> None:
    assert real.get("/health").json() == {"status": "ok"}


def test_openapi_lists_every_route(real: TestClient) -> None:
    paths = real.get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/health",
        "/auth/login",
        "/audit",
        "/instances",
        "/instances/{instance_id}/edge-list",
        "/instances/{instance_id}/display",
        "/instances/{instance_id}/anomalies",
        "/instances/{instance_id}/solution",
        "/instances/{instance_id}/solve",
        "/instances/{instance_id}/repair",
        "/jobs/{job_id}",
        "/jobs/{job_id}/accept",
    }


class TestRealInstanceFiles:
    def test_list(self, real: TestClient) -> None:
        assert {"id": REAL} in real.get("/instances").json()

    def test_edge_list_conforms(self, real: TestClient) -> None:
        body = real.get(f"/instances/{REAL}/edge-list").json()
        assert conforms("edge_list_v1", body)

    @pytest.mark.parametrize("resource", ["display", "anomalies"])
    def test_served_as_committed(self, real: TestClient, resource: str) -> None:
        committed = json.loads(
            (REPO / "data" / "instances" / REAL / f"{resource}.json").read_text("utf-8")
        )
        assert real.get(f"/instances/{REAL}/{resource}").json() == committed

    def test_solution_served_as_committed(self, real: TestClient) -> None:
        # S12d committed solution.json; nothing has been solved here, so it is what is served
        committed = json.loads(
            (REPO / "data" / "instances" / REAL / "solution.json").read_text("utf-8")
        )
        response = real.get(f"/instances/{REAL}/solution")
        assert response.status_code == 200
        assert conforms("solution_v2", response.json())
        assert response.json() == committed

    def test_no_solution_file(self, tmp_path: Path, database_url: str) -> None:
        (tmp_path / "unsolved").mkdir()
        (tmp_path / "unsolved" / "edge_list.json").write_text(
            json.dumps(generate(PRESETS["small"], 1)), encoding="utf-8"
        )
        with client_for(tmp_path, database_url) as client:
            assert client.get("/instances/unsolved/solution").status_code == 404


class TestNotFound:
    @pytest.mark.parametrize(
        "path", ["edge-list", "display", "anomalies", "solution"]
    )
    def test_unknown_instance(self, real: TestClient, path: str) -> None:
        assert real.get(f"/instances/nope/{path}").status_code == 404

    def test_id_is_never_a_path(self) -> None:
        # the path resolves to a real edge_list.json, but the id is not a listed instance
        assert (INSTANCES_DIR / f"../instances/{REAL}" / "edge_list.json").is_file()
        assert InstanceStore().read(f"../instances/{REAL}", "edge_list") is None

    def test_solve_unknown_instance(self, real: TestClient) -> None:
        assert real.post("/instances/nope/solve").status_code == 404

    def test_unknown_job(self, real: TestClient) -> None:
        assert real.get("/jobs/nope").status_code == 404

    def test_missing_sidecar(self, synthetic: TestClient) -> None:
        assert synthetic.get("/instances/small/display").status_code == 404
        assert synthetic.get("/instances/small/anomalies").status_code == 404


class TestJobs:
    def test_solved(self, synthetic: TestClient) -> None:
        job = solve(synthetic, "small", max_moves=2000)
        assert job["status"] == "solved"
        assert conforms("solution_v2", job["solution"])
        assert job["solution"]["status"] == "solved"
        assert synthetic.get("/instances/small/solution").json() == job["solution"]

    def test_infeasible_carries_the_diagnosis(self, synthetic: TestClient) -> None:
        job = solve(synthetic, "infeasible")
        assert job["status"] == "infeasible"
        assert conforms("solution_v2", job["solution"])
        assert job["solution"]["diagnosis"]["method"] == "presolve"
        assert synthetic.get("/instances/infeasible/solution").json() == job["solution"]

    def test_timeout_is_a_status_not_a_solution(self, synthetic: TestClient) -> None:
        job = solve(synthetic, "timeout", time_limit_s=1e-9)
        assert job["status"] == "timeout"
        assert "solution" not in job  # D33
        assert synthetic.get("/instances/timeout/solution").status_code == 404

    def test_solver_error(self, synthetic: TestClient) -> None:
        job = solve(synthetic, "broken")
        assert job["status"] == "error"
        assert "ghost" in job["error"]
        assert "solution" not in job

    def test_first_status_is_queued_or_running(self, synthetic: TestClient) -> None:
        # infeasible by pre-solve: no local search left running at the default 200000 moves
        body = synthetic.post("/instances/infeasible/solve").json()
        assert body["status"] in ("queued", "running")
        job = synthetic.get(f"/jobs/{body['job_id']}").json()
        assert (job["time_limit_s"], job["max_moves"]) == (300.0, 200_000)

    @pytest.mark.parametrize("limit", [0, -1, 1801])
    def test_rejects_a_bad_time_limit(self, synthetic: TestClient, limit: float) -> None:
        response = synthetic.post("/instances/small/solve", json={"time_limit_s": limit})
        assert response.status_code == 422

    @pytest.mark.parametrize("moves", [-1, MAX_MAX_MOVES + 1, 1.5])
    def test_rejects_a_bad_move_budget(self, synthetic: TestClient, moves: float) -> None:
        response = synthetic.post("/instances/small/solve", json={"max_moves": moves})
        assert response.status_code == 422


def test_phases_in_order() -> None:
    edge_list = generate(PRESETS["small"], 1)
    for moves, expected in [(0, ["search"]), (100, ["search", "improve"])]:
        heard: list[str] = []
        assert solve_edge_list(edge_list, 60.0, moves, heard.append)[0] == "solved"
        assert heard == expected


@pytest.fixture(scope="module")
def real_copy(
    tmp_path_factory: pytest.TempPathFactory, database_url: str
) -> Iterator[TestClient]:
    root = tmp_path_factory.mktemp("real")
    (root / "real-copy").mkdir()
    shutil.copy(INSTANCES_DIR / REAL / "edge_list.json", root / "real-copy" / "edge_list.json")
    with client_for(root, database_url) as client:
        yield client


@pytest.fixture(scope="module")
def real_edge_list() -> dict[str, Any]:
    return json.loads((INSTANCES_DIR / REAL / "edge_list.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def backtracked(real_edge_list: dict[str, Any]) -> dict[str, Any]:
    """The real instance solved by backtracking alone, outside the API."""
    graph = build_conflict_graph(real_edge_list)
    return backtrack_solve(graph, real_edge_list, time_limit_s=60).to_solution_v2_dict()


def without_runtime(solution: dict[str, Any]) -> dict[str, Any]:
    return solution | {"metadata": solution["metadata"] | {"runtime_ms": None}}


class TestImprove:
    """S13d on the real EVEN instance: search, then local search, in one job."""

    def test_no_moves_is_plain_backtracking(
        self, real_copy: TestClient, backtracked: dict[str, Any]
    ) -> None:
        job = solve(real_copy, "real-copy", max_moves=0)
        assert job["status"] == "solved" and job["max_moves"] == 0
        assert without_runtime(job["solution"]) == without_runtime(backtracked)

    def test_improves_and_stays_valid(
        self, real_copy: TestClient, real_edge_list: dict[str, Any],
        backtracked: dict[str, Any],
    ) -> None:
        job = solve(real_copy, "real-copy", max_moves=2000)
        solution = job["solution"]
        assert job["status"] == "solved"
        assert conforms("solution_v2", solution)
        assert validate_solution(real_edge_list, solution) == []
        assert solution["quality"]["score"] >= backtracked["quality"]["score"]
        assert "local-search" in solution["metadata"]["algorithm"]
        # seed 0 and a move budget fix the result (solver/improve.py)
        expected = improve(real_edge_list, backtracked, max_moves=2000, seed=0)
        assert without_runtime(solution) == without_runtime(expected)
        assert real_copy.get("/instances/real-copy/solution").json() == solution


def test_phase_while_running(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each phase the worker reports is what GET /jobs shows, step by step: the worker
    (in a thread here) waits for the test before moving on, so no timing is involved."""
    phases = ("search", "improve")
    reached: queue.Queue[str] = queue.Queue()
    go = {phase: threading.Event() for phase in phases}

    def worker(edge_list, time_limit_s, max_moves, on_phase) -> tuple[str, None]:
        for phase in phases:
            on_phase(phase)  # the real _mark_running: a database write
            reached.put(phase)
            assert go[phase].wait(60)
        return "timeout", None

    monkeypatch.setattr(service_module, "solve_edge_list", worker)
    (tmp_path / "phases").mkdir()
    (tmp_path / "phases" / "edge_list.json").write_text(
        json.dumps(generate(PRESETS["small"], 1)), encoding="utf-8"
    )
    with client_for(tmp_path, database_url) as client:
        service = client.app.state.service
        service._pool.shutdown()
        service._pool = ThreadPoolExecutor(max_workers=1)
        job_id = client.post("/instances/phases/solve").json()["job_id"]
        for phase in phases:
            assert reached.get(timeout=60) == phase
            job = client.get(f"/jobs/{job_id}").json()
            assert (job["status"], job["phase"]) == ("running", phase)
            go[phase].set()
        service._pool.shutdown()  # returns once the job's done callback has run
        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "timeout" and "phase" not in job


class TestPersistence:
    def test_jobs_and_solution_survive_a_new_app(
        self, tmp_path: Path, database_url: str
    ) -> None:
        (tmp_path / "persist").mkdir()
        (tmp_path / "persist" / "edge_list.json").write_text(
            json.dumps(generate(PRESETS["small"], 3)), encoding="utf-8"
        )
        with client_for(tmp_path, database_url) as first:
            job = solve(first, "persist", max_moves=100)
        assert job["status"] == "solved"
        with client_for(tmp_path, database_url) as second:
            assert second.get(f"/jobs/{job['id']}").json() == job
            assert second.get("/instances/persist/solution").json() == job["solution"]

    def test_restart_marks_unfinished_jobs_as_error(self, database_url: str) -> None:
        engine = create_engine(database_url)
        with OrmSession(engine) as db:
            entry = AuditEntry(actor="t", action="solve", detail=json.dumps(
                {"job_id": "restart-running", "status": "queued", "ended_at": None}))
            db.add(entry)
            db.flush()
            db.add_all([
                SolveJob(id="restart-queued", instance_id="gone", requested_by="t",
                         status="queued", params={"time_limit_s": 1.0, "max_moves": 0}),
                SolveJob(id="restart-running", instance_id="gone", requested_by="t",
                         status="running", phase="improve", audit_id=entry.id,
                         params={"time_limit_s": 1.0, "max_moves": 5}),
            ])
            db.commit()
            audit_id = entry.id
        with client_for(INSTANCES_DIR, database_url) as client:
            for job_id in ("restart-queued", "restart-running"):
                job = client.get(f"/jobs/{job_id}").json()
                assert (job["status"], job["error"]) == ("error", "server restarted")
                assert "phase" not in job
        with OrmSession(engine) as db:
            detail = json.loads(db.get_one(AuditEntry, audit_id).detail)
        engine.dispose()
        assert detail.pop("ended_at") is not None
        assert detail == {"job_id": "restart-running", "status": "error"}
