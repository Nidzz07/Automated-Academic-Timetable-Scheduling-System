"""S13a API: every endpoint, contract-checked responses, the job lifecycle and 404s.

Solves use synthetic presets (D19) in a scratch instance directory; the real
EVEN instance is only read, never solved here (it times out at 300 s, S12a).
Every client carries a coordinator token (S13b); auth itself is tested in test_auth.py.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.main import create_app
from backend.app.store import INSTANCES_DIR, InstanceStore
from backend.tests.conftest import AUTH, bearer
from solver.benchmarks.synthetic import PRESETS, generate

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


def solve(client: TestClient, instance: str, time_limit_s: float = 60.0) -> dict[str, Any]:
    """POST a solve, then poll the job until it leaves queued/running."""
    accepted = client.post(f"/instances/{instance}/solve", json={"time_limit_s": time_limit_s})
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]
    deadline = time.monotonic() + 120
    while (job := client.get(f"/jobs/{job_id}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
    assert job["id"] == job_id and job["instance_id"] == instance
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
        "/jobs/{job_id}",
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
        job = solve(synthetic, "small")
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
        body = synthetic.post("/instances/small/solve").json()
        assert body["status"] in ("queued", "running")
        assert synthetic.get(f"/jobs/{body['job_id']}").json()["time_limit_s"] == 300.0

    @pytest.mark.parametrize("limit", [0, -1, 1801])
    def test_rejects_a_bad_time_limit(self, synthetic: TestClient, limit: float) -> None:
        response = synthetic.post("/instances/small/solve", json={"time_limit_s": limit})
        assert response.status_code == 422
