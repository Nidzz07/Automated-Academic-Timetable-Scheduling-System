"""S14i: the official timetable after clearing accepted changes and stale solves (ROADMAP
D56), a repair's time limit over the whole job, infeasible solves explained, the edge lists
jobs run on, and qualified faculty outside the instance.

Runs on copies of the real EVEN instance in a scratch directory, as test_repair.py does;
infeasible solves on the synthetic infeasible preset (D19), never on committed data.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import service as service_module
from backend.app.store import INSTANCES_DIR
from backend.tests.conftest import bearer
from backend.tests.test_api import REAL, client_for, conforms, solve, without_runtime
from backend.tests.test_repair import (
    FREE_DRAG,
    KURHADE_AFTERNOON,
    KURHADE_TUESDAY,
    ROOM_603_MONDAY,
    accept,
    audit,
    run,
    start,
    wait,
)
from backend.tests.test_substitution import FILES, LECTURE, read, sub
from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.mus import explain
from solver.repair import apply_change
from solver.validate import validate_solution

# a real SPIT teacher (data/generated/ingestion_v2_even.json) the edge list has no
# faculty_availability entry for; qualifications.json does not list him, the test does
OUTSIDE = "fac-suhas-kakade"


def copy_real(root: Path, name: str) -> None:
    (root / name).mkdir()
    for file in FILES:
        shutil.copy(INSTANCES_DIR / REAL / file, root / name / file)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory, database_url: str) -> Iterator[TestClient]:
    """Real copies, one per test; ``explain``: the synthetic infeasible preset; ``outside``:
    qualifications.json also lists OUTSIDE for CE207."""
    root = tmp_path_factory.mktemp("fixes")
    for name in ("cleared-sub", "cleared-absence", "deadline", "edges", "outside"):
        copy_real(root, name)
    sheet = read("qualifications.json")
    sheet["subjects"]["subj-ce207"]["faculty"].append(
        {"faculty_id": OUTSIDE, "session_type": None})
    (root / "outside" / "qualifications.json").write_text(json.dumps(sheet), encoding="utf-8")
    (root / "explain").mkdir()
    (root / "explain" / "edge_list.json").write_text(
        json.dumps(generate(PRESETS["infeasible"], 1)), encoding="utf-8")
    with client_for(root, database_url) as c:
        yield c


def official(client: TestClient, instance: str) -> dict[str, Any]:
    return client.get(f"/instances/{instance}/solution").json()


def clear(client: TestClient, instance: str, user: str) -> list[dict[str, Any]]:
    response = client.delete(f"/instances/{instance}/changes",
                             headers=bearer("administrator", user))
    assert response.status_code == 200, response.text
    return response.json()


class TestClearedChanges:
    """D56 (a): after clearing, the official timetable is valid for the changes in force."""

    def test_cleared_substitution(self, client: TestClient, database_url: str) -> None:
        edge_list, committed = read("edge_list.json"), read("solution.json")
        change = sub(LECTURE, "fac-nataasha-raul")  # busy then: the repair moves the lecture
        job = run(client, "cleared-sub", change)
        assert job["status"] == "solved" and accept(client, job["id"]).status_code == 200
        assert official(client, "cleared-sub") == job["solution"]
        # with Anant Nimkar back, that timetable clashed in the S12g solution.json (what D56
        # fixes); in the S14u one his lecture lands where he is free, so it does not
        assert [v.kind for v in validate_solution(edge_list, job["solution"])] == []

        assert [c["job_id"] for c in clear(client, "cleared-sub", "sub-clearer")] == [job["id"]]
        now = official(client, "cleared-sub")
        assert now == committed  # the substitution was the only finished job
        current = client.get("/instances/cleared-sub/edge-list/current").json()
        assert current == edge_list and validate_solution(current, now) == []
        listed = client.get(f"/instances/cleared-sub/sessions/{LECTURE}/substitutes")
        assert listed.status_code == 200 and listed.json()["faculty_id"] == "fac-anant-nimkar"
        again = run(client, "cleared-sub", change)
        assert (again["status"], again["base"], again["built_with"]) == ("solved", "committed", [])

        [row] = audit(database_url, "sub-clearer", "clear_changes")
        assert json.loads(row.detail) == {"instance_id": "cleared-sub", "cleared": 1,
                                          "official": "committed"}

    def test_cleared_absence(self, client: TestClient, database_url: str) -> None:
        """The newest finished job that depends on no cleared change becomes official: a
        solve from before the absence, not the absence or the solve built with it."""
        edge_list = read("edge_list.json")
        before = solve(client, "cleared-absence", max_moves=0)
        assert (before["built_with"], before["stale"]) == ([], False)
        absence = run(client, "cleared-absence", KURHADE_AFTERNOON)
        assert accept(client, absence["id"]).status_code == 200
        after = solve(client, "cleared-absence", max_moves=0)
        assert (after["built_with"], after["stale"]) == ([absence["id"]], False)
        assert official(client, "cleared-absence") == after["solution"]

        clear(client, "cleared-absence", "absence-clearer")
        now = official(client, "cleared-absence")
        assert now == before["solution"] and validate_solution(edge_list, now) == []
        assert client.get(f"/jobs/{after['id']}").json()["stale"] is False  # it was official
        listed = client.get(f"/instances/cleared-absence/sessions/{LECTURE}/substitutes")
        assert listed.status_code == 200
        assert run(client, "cleared-absence", FREE_DRAG)["base"] == before["id"]

        [row] = audit(database_url, "absence-clearer", "clear_changes")
        assert json.loads(row.detail) == {"instance_id": "cleared-absence", "cleared": 1,
                                          "official": before["id"]}


def test_solve_that_ends_after_an_accept_is_stale(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D56 (b): a solve started before an accept and finished after it is kept, never
    official. The solve (in a thread here) waits for the test, so no timing is involved."""
    began, release = threading.Event(), threading.Event()
    real_solve = service_module.solve_edge_list

    def held(*args: Any) -> tuple[str, dict[str, Any] | None]:
        began.set()
        assert release.wait(60)
        return real_solve(*args)

    monkeypatch.setattr(service_module, "solve_edge_list", held)
    copy_real(tmp_path, "stale")
    with client_for(tmp_path, database_url) as client:
        service = client.app.state.service
        service._pool.shutdown()
        service._pool = ThreadPoolExecutor(max_workers=2)
        accepted = client.post("/instances/stale/solve", json={"max_moves": 0})
        assert began.wait(60)
        repaired = run(client, "stale", KURHADE_AFTERNOON)
        assert accept(client, repaired["id"]).status_code == 200
        release.set()

        late = wait(client, accepted.json()["job_id"])
        assert (late["status"], late["built_with"], late["stale"]) == ("solved", [], True)
        assert official(client, "stale") == repaired["solution"]
        [row] = [r for r in audit(database_url, "test-coordinator", "solve")
                 if json.loads(r.detail)["job_id"] == late["id"]]
        assert json.loads(row.detail)["stale"] is True

        fresh = solve(client, "stale", max_moves=0)
        assert (fresh["built_with"], fresh["stale"]) == ([repaired["id"]], False)
        assert official(client, "stale") == fresh["solution"]
        assert validate_solution(apply_change(read("edge_list.json"), KURHADE_AFTERNOON),
                                 fresh["solution"]) == []


def test_repair_time_limit_covers_the_explanation(client: TestClient) -> None:
    """Kurhade unavailable all Tuesday: pre-solve proves it impossible at once, and
    explaining it takes about two minutes (test_repair's slow test). With 3 s the job
    ends by then: S14b's unfinished diagnosis or a timeout, never solved."""
    run(client, "deadline", FREE_DRAG)  # a warm pool worker: imports are not repair time
    limit = 3.0
    began = time.monotonic()
    job = run(client, "deadline", KURHADE_TUESDAY, time_limit_s=limit)
    assert time.monotonic() - began < limit + 2.0
    assert job["status"] in ("infeasible", "timeout")
    if job["status"] == "infeasible":
        assert conforms("solution_v2", job["solution"])
        assert job["solution"]["diagnosis"]["method"] in ("presolve", "mus")
        assert job["solution"]["metadata"]["runtime_ms"] < (limit + 1.0) * 1000


class TestInfeasibleSolveExplained:
    def test_minimal_set_and_verified_relaxation(self, client: TestClient) -> None:
        edge_list = generate(PRESETS["infeasible"], 1)
        job = solve(client, "explain")
        assert job["status"] == "infeasible" and conforms("solution_v2", job["solution"])
        diagnosis = job["solution"]["diagnosis"]
        assert diagnosis["method"] == "mus"
        assert [m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]] == [
            "cohort_clash.d00", "cohort_clash.d00.d00-b0", "pin.0"]
        relaxation = diagnosis["suggested_relaxation"]
        assert relaxation["action"]["action_type"] == "RELAX_PINNED_BLOCK"
        assert relaxation["verification"]["status"] == "restored"
        # exactly solver.mus.explain on the solver's raw diagnosis
        raw = backtrack_solve(build_conflict_graph(edge_list), edge_list,
                              time_limit_s=60).to_solution_v2_dict()
        assert raw["diagnosis"]["method"] == "presolve"
        assert without_runtime(job["solution"]) == without_runtime(explain(edge_list, raw))

    def test_explained_within_the_time_limit(self, client: TestClient) -> None:
        """Pre-solve proves it at once; the explanation (about 2 s) is cut by the job's
        remaining time and keeps the proof, never a timeout (D33)."""
        job = solve(client, "explain", time_limit_s=0.2)
        assert job["status"] == "infeasible" and conforms("solution_v2", job["solution"])
        assert job["solution"]["diagnosis"]["method"] == "presolve"
        assert job["solution"]["metadata"]["runtime_ms"] < 1200


def test_edge_lists_jobs_run_on(client: TestClient) -> None:
    edge_list = read("edge_list.json")
    current = "/instances/edges/edge-list/current"
    assert client.get(current).json() == edge_list

    absence = run(client, "edges", KURHADE_AFTERNOON)
    assert accept(client, absence["id"]).status_code == 200
    change = sub(LECTURE, "fac-prasenjit-bhavathankar")
    substitution = run(client, "edges", change)
    assert substitution["built_with"] == [absence["id"]]
    assert accept(client, substitution["id"]).status_code == 200
    built = apply_change(apply_change(edge_list, KURHADE_AFTERNOON), change)
    body = client.get(current).json()
    assert body == built and conforms("edge_list_v1", body)
    assert client.get("/instances/edges/edge-list").json() == edge_list  # unchanged

    def ran_on(job: dict[str, Any]) -> dict[str, Any]:
        response = client.get(f"/jobs/{job['id']}/edge-list")
        assert response.status_code == 200 and conforms("edge_list_v1", response.json())
        return response.json()

    assert ran_on(absence) == apply_change(edge_list, KURHADE_AFTERNOON)
    assert ran_on(substitution) == built
    room = run(client, "edges", ROOM_603_MONDAY)  # not accepted: its own change only
    assert room["status"] == "solved" and ran_on(room) == apply_change(built, ROOM_603_MONDAY)
    assert validate_solution(ran_on(room), room["solution"]) == []
    solved = solve(client, "edges", max_moves=0)
    assert ran_on(solved) == built and validate_solution(built, solved["solution"]) == []

    assert client.get("/instances/nope/edge-list/current").status_code == 404
    assert client.get("/jobs/nope/edge-list").status_code == 404
    for role in ("faculty", "student", "administrator"):
        assert client.get(current, headers=bearer(role)).status_code == 200
        assert client.get(f"/jobs/{room['id']}/edge-list", headers=bearer(role)).status_code == 200
    assert client.get(current, headers={"Authorization": ""}).status_code == 401


def test_qualified_but_not_in_the_instance(client: TestClient) -> None:
    """Listed in qualifications.json, without a faculty_availability entry: left out as
    not_in_instance, never a 500; and no substitute (422)."""
    response = client.get(f"/instances/outside/sessions/{LECTURE}/substitutes")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["faculty_id"] for c in body["candidates"]] == ["fac-sudhir-dhage"]
    assert [o["faculty_id"] for o in body["left_out"]] == [
        "fac-nataasha-raul", "fac-prasenjit-bhavathankar", OUTSIDE]
    assert body["left_out"][2] == {"faculty_id": OUTSIDE, "reasons": ["not_in_instance"],
                                   "violations": []}
    assert start(client, "outside", sub(LECTURE, OUTSIDE)).status_code == 422
