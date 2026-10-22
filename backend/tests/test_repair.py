"""S14c: repair jobs through the API and accepting a repair (ROADMAP D49).

Runs on copies of the real EVEN instance (edge list and committed solution) in a scratch
directory, as test_api.py's S13d tests do, so the committed files are never the ones
changed. The changes are S14a's real scenarios (solver/benchmarks/real_repair.py).
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from backend.app.store import INSTANCES_DIR
from backend.tests.conftest import bearer
from backend.tests.test_api import REAL, client_for, conforms, solve, without_runtime
from db.models import AuditEntry
from solver.benchmarks.real_repair import SCENARIOS
from solver.benchmarks.synthetic import PRESETS, generate
from solver.repair import apply_change, repair
from solver.validate import validate_solution

KURHADE_TUESDAY = SCENARIOS[0][1]  # pre-solve proves it impossible; explaining it is slow
ROOM_603_MONDAY = SCENARIOS[1][1]
FREE_DRAG = SCENARIOS[2][1]
PIN_DRAG = SCENARIOS[3][1]  # infeasible, explained at once from the pin (S14b)
KURHADE_AFTERNOON = SCENARIOS[4][1]


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return json.loads((INSTANCES_DIR / REAL / "solution.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def real_edge_list() -> dict[str, Any]:
    return json.loads((INSTANCES_DIR / REAL / "edge_list.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory, database_url: str) -> Iterator[TestClient]:
    """``changes`` and ``accepts``: the real instance with its committed solution;
    ``unsolved``: its edge list only; ``infeasible``: a synthetic preset (D19)."""
    root = tmp_path_factory.mktemp("repair")
    for name in ("changes", "accepts", "accumulates", "unsolved"):
        (root / name).mkdir()
        files = ["edge_list.json"] if name == "unsolved" else ["edge_list.json", "solution.json"]
        for file in files:
            shutil.copy(INSTANCES_DIR / REAL / file, root / name / file)
    (root / "infeasible").mkdir()
    (root / "infeasible" / "edge_list.json").write_text(
        json.dumps(generate(PRESETS["infeasible"], 1)), encoding="utf-8"
    )
    with client_for(root, database_url) as c:
        yield c


def sent(change: dict[str, Any]) -> dict[str, Any]:
    """The change as the API stores it: no null sub-room."""
    return {k: v for k, v in change.items() if v is not None}


def start(client: TestClient, instance: str, change: dict[str, Any], **body: Any):
    return client.post(f"/instances/{instance}/repair",
                       json={"change": change, "time_limit_s": 60, **body})


def wait(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    while (job := client.get(f"/jobs/{job_id}").json())["status"] in ("queued", "running"):
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
    return job


def run(client: TestClient, instance: str, change: dict[str, Any], **body: Any) -> dict[str, Any]:
    accepted = start(client, instance, change, **body)
    assert accepted.status_code == 202, accepted.text
    return wait(client, accepted.json()["job_id"])


def accept(client: TestClient, job_id: str, role: str = "coordinator", user: str | None = None):
    return client.post(f"/jobs/{job_id}/accept", headers=bearer(role, user))


class TestChanges:
    @pytest.mark.parametrize("change, outcome", [
        (ROOM_603_MONDAY, "solved"),
        (FREE_DRAG, "solved"),
        (KURHADE_AFTERNOON, "solved"),
        (PIN_DRAG, "infeasible"),
        # about two minutes: the full explanation, run here and again for `expected`
        pytest.param(KURHADE_TUESDAY, "infeasible", marks=pytest.mark.slow),
    ], ids=["room-unavailable", "move-session", "faculty-unavailable", "infeasible",
            "infeasible-explained"])
    def test_each_change_type(
        self, client: TestClient, real_edge_list: dict[str, Any], committed: dict[str, Any],
        change: dict[str, Any], outcome: str,
    ) -> None:
        job = run(client, "changes", change)
        assert (job["kind"], job["base"], job["change"]) == ("repair", "committed", sent(change))
        assert job["status"] == outcome and "accepted_at" not in job
        assert conforms("solution_v2", job["solution"])
        # the API runs solver.repair on the official solution, nothing else
        expected = repair(real_edge_list, committed, change, time_limit_s=60)
        assert without_runtime(job["solution"]) == without_runtime(expected)
        if outcome == "solved":
            changed = apply_change(real_edge_list, change)
            assert validate_solution(changed, job["solution"]) == []
        # not official until accepted (D49)
        assert client.get("/instances/changes/solution").json() == committed

    def test_timeout_is_a_status_not_infeasible(self, client: TestClient) -> None:
        job = run(client, "changes", ROOM_603_MONDAY, time_limit_s=1e-9)
        assert job["status"] == "timeout" and "solution" not in job  # D33

    def test_first_status_and_defaults(self, client: TestClient) -> None:
        body = client.post("/instances/changes/repair", json={"change": FREE_DRAG}).json()
        assert body["status"] in ("queued", "running")
        job = wait(client, body["job_id"])
        assert (job["time_limit_s"], job["max_moves"]) == (300.0, 20_000)

    def test_audited_with_its_change_and_base(
        self, client: TestClient, database_url: str
    ) -> None:
        user = "repair-auditor"
        accepted = client.post("/instances/changes/repair", headers=bearer("administrator", user),
                               json={"change": KURHADE_AFTERNOON, "time_limit_s": 60})
        job = wait(client, accepted.json()["job_id"])
        detail = json.loads(audit(database_url, user, "repair")[0].detail)
        assert detail.pop("started_at") <= detail.pop("ended_at")
        assert detail == {
            "instance_id": "changes", "time_limit_s": 60, "job_id": job["id"],
            "base": "committed", "status": "solved",
            "change": {"kind": "faculty_unavailable", "faculty_id": "fac-swapnali-kurhade",
                       "slots": [[1, p] for p in (5, 6, 7, 8, 9)]},
        }


def audit(database_url: str, actor: str, action: str) -> list[AuditEntry]:
    engine = create_engine(database_url)
    try:
        with OrmSession(engine) as db:
            return list(db.scalars(select(AuditEntry).where(
                AuditEntry.actor == actor, AuditEntry.action == action).order_by(AuditEntry.id)))
    finally:
        engine.dispose()


ONE_SLOT = [{"day": 0, "period": 0}]


class TestRefused:
    @pytest.mark.parametrize("change", [
        {"kind": "faculty_unavailable", "faculty_id": "fac-nobody", "slots": ONE_SLOT},
        {"kind": "room_unavailable", "room_id": "room-nowhere", "slots": ONE_SLOT},
        {**FREE_DRAG, "session_id": "no-such-session"},
        {**FREE_DRAG, "room_id": "room-nowhere"},
        {**FREE_DRAG, "sub_room_id": "room-nowhere"},
        {**KURHADE_AFTERNOON, "slots": [{"day": 5, "period": 0}]},
        {**KURHADE_AFTERNOON, "slots": [{"day": 0, "period": 10}]},
        {**FREE_DRAG, "day": -1},
        {**KURHADE_AFTERNOON, "slots": []},
        {"kind": "teacher_sick", "faculty_id": "fac-swapnali-kurhade", "slots": ONE_SLOT},
        None,
    ], ids=["faculty", "room", "session", "move-room", "move-sub-room", "day-off-grid",
            "period-off-grid", "negative-day", "no-slots", "unknown-kind", "no-change"])
    def test_unknown_ids_or_slots_are_422_and_not_queued(
        self, client: TestClient, database_url: str, change: dict[str, Any] | None
    ) -> None:
        response = client.post("/instances/changes/repair", headers=bearer("coordinator", "r422"),
                               json={"change": change} if change else {})
        assert response.status_code == 422, response.text
        assert audit(database_url, "r422", "repair") == []

    def test_unknown_instance(self, client: TestClient) -> None:
        assert start(client, "nope", FREE_DRAG).status_code == 404

    @pytest.mark.parametrize("role", ["faculty", "student"])
    def test_faculty_and_student_may_not_repair_or_accept(
        self, client: TestClient, role: str
    ) -> None:
        response = client.post("/instances/changes/repair", headers=bearer(role),
                               json={"change": FREE_DRAG})
        assert response.status_code == 403
        assert accept(client, "any-job", role).status_code == 403

    def test_no_token(self, client: TestClient) -> None:
        response = client.post("/instances/changes/repair", headers={"Authorization": ""},
                               json={"change": FREE_DRAG})
        assert response.status_code == 401

    def test_nothing_official_to_repair(self, client: TestClient) -> None:
        assert client.get("/instances/unsolved/solution").status_code == 404
        response = start(client, "unsolved", FREE_DRAG)
        assert response.status_code == 409

    def test_an_infeasible_official_is_not_repaired(self, client: TestClient) -> None:
        assert solve(client, "infeasible")["status"] == "infeasible"
        edge_list = client.get("/instances/infeasible/edge-list").json()
        change = {"kind": "faculty_unavailable",
                  "faculty_id": edge_list["faculty_availability"][0]["faculty_id"],
                  "slots": ONE_SLOT}
        assert start(client, "infeasible", change).status_code == 409


def test_accept_rules(
    client: TestClient, committed: dict[str, Any], database_url: str
) -> None:
    """D49 in order: accepted repairs become official, each repair at most once, and only
    while its base is still the official solution; a finished solve becomes official."""
    def official() -> dict[str, Any]:
        return client.get("/instances/accepts/solution").json()

    first = run(client, "accepts", ROOM_603_MONDAY)
    assert first["base"] == "committed" and official() == committed
    assert accept(client, "no-such-job").status_code == 404

    response = accept(client, first["id"], "administrator", "accepter")
    assert response.status_code == 200, response.text
    assert response.json()["accepted_at"] and response.json()["status"] == "solved"
    assert client.get(f"/jobs/{first['id']}").json() == response.json()
    assert official() == first["solution"]
    assert accept(client, first["id"]).status_code == 409  # its base is no longer official

    # two repairs of the same official solution: only the first accepted wins
    second = run(client, "accepts", FREE_DRAG)
    third = run(client, "accepts", KURHADE_AFTERNOON)
    assert second["base"] == third["base"] == first["id"]
    assert second["built_with"] == third["built_with"] == [first["id"]]  # D52
    assert accept(client, second["id"], "coordinator", "accepter").status_code == 200
    assert official() == second["solution"]
    assert accept(client, third["id"]).status_code == 409
    assert official() == second["solution"]

    # only a solved repair
    infeasible = run(client, "accepts", PIN_DRAG)
    timed_out = run(client, "accepts", ROOM_603_MONDAY, time_limit_s=1e-9)
    assert (infeasible["status"], timed_out["status"]) == ("infeasible", "timeout")
    assert infeasible["base"] == second["id"]
    for job in (infeasible, timed_out):
        assert accept(client, job["id"]).status_code == 409

    # a finished solve becomes official; a repair of the solution before it is refused
    pending = run(client, "accepts", KURHADE_AFTERNOON)
    solved = solve(client, "accepts", max_moves=0)
    assert solved["kind"] == "solve" and "base" not in solved
    assert official() == solved["solution"]
    assert accept(client, solved["id"]).status_code == 409  # not a repair
    assert accept(client, pending["id"]).status_code == 409
    assert run(client, "accepts", FREE_DRAG)["base"] == solved["id"]

    rows = audit(database_url, "accepter", "accept")
    assert [json.loads(r.detail) for r in rows] == [
        {"instance_id": "accepts", "job_id": first["id"], "base": "committed"},
        {"instance_id": "accepts", "job_id": second["id"], "base": first["id"]},
    ]


def test_official_survives_a_new_app(
    tmp_path: Path, database_url: str, committed: dict[str, Any]
) -> None:
    (tmp_path / "persisted").mkdir()
    for file in ("edge_list.json", "solution.json"):
        shutil.copy(INSTANCES_DIR / REAL / file, tmp_path / "persisted" / file)
    with client_for(tmp_path, database_url) as first:
        job = run(first, "persisted", FREE_DRAG)
        assert accept(first, job["id"]).status_code == 200
    with client_for(tmp_path, database_url) as second:
        assert second.get("/instances/persisted/solution").json() == job["solution"]
        assert second.get(f"/jobs/{job['id']}").json()["accepted_at"]


def test_accepted_changes_accumulate(
    client: TestClient, real_edge_list: dict[str, Any], committed: dict[str, Any],
    database_url: str,
) -> None:
    """D52: once "Kurhade unavailable Tue P5-P9" is accepted, no later repair or solve
    places her there, until an administrator clears it. A move is not re-applied."""
    kurhade = apply_change(real_edge_list, KURHADE_AFTERNOON)
    hers = {s["id"] for s in real_edge_list["sessions"]
            if s["faculty_id"] == KURHADE_AFTERNOON["faculty_id"]}
    afternoon = {(s["day"], s["period"]) for s in KURHADE_AFTERNOON["slots"]}

    def respects_her(solution: dict[str, Any], edge_list: dict[str, Any]) -> bool:
        starts = {(a["day"], a["period"]) for a in solution["assignment"]
                  if a["session_id"] in hers}
        return not starts & afternoon and validate_solution(edge_list, solution) == []

    def changes() -> list[dict[str, Any]]:
        return client.get("/instances/accumulates/changes").json()

    assert changes() == []
    first = run(client, "accumulates", KURHADE_AFTERNOON)
    assert first["built_with"] == []
    assert client.get(f"/jobs/{first['id']}/base-solution").json() == committed
    assert accept(client, first["id"], "coordinator", "accumulator").status_code == 200
    [listed] = changes()
    assert listed.pop("accepted_at")
    assert listed == {"job_id": first["id"], "change": KURHADE_AFTERNOON,
                      "requested_by": "test-coordinator", "accepted_by": "accumulator"}

    # a later repair (of another change) keeps her out of Tuesday afternoon
    drag = run(client, "accumulates", FREE_DRAG)
    assert (drag["status"], drag["base"], drag["built_with"]) == (
        "solved", first["id"], [first["id"]])
    assert client.get(f"/jobs/{drag['id']}/base-solution").json() == first["solution"]
    assert respects_her(drag["solution"], apply_change(kurhade, FREE_DRAG))
    assert accept(client, drag["id"]).status_code == 200
    assert [c["job_id"] for c in changes()] == [first["id"]]  # a move is not a change

    # and so does a fresh solve
    solved = solve(client, "accumulates", max_moves=0)
    assert solved["status"] == "solved" and solved["built_with"] == [first["id"]]
    assert respects_her(solved["solution"], kurhade)
    assert client.get(f"/jobs/{solved['id']}/base-solution").status_code == 404  # a solve
    assert client.get("/jobs/no-such-job/base-solution").status_code == 404

    # only an administrator clears them; audited; later jobs are built without them
    delete = "/instances/accumulates/changes"
    assert client.delete(delete).status_code == 403  # coordinator
    cleared = client.delete(delete, headers=bearer("administrator", "clearer"))
    assert cleared.status_code == 200
    assert [c["job_id"] for c in cleared.json()] == [first["id"]]
    assert changes() == []
    assert client.delete("/instances/nope/changes",
                         headers=bearer("administrator")).status_code == 404
    [row] = audit(database_url, "clearer", "clear_changes")
    assert json.loads(row.detail) == {"instance_id": "accumulates", "cleared": 1}
    assert run(client, "accumulates", ROOM_603_MONDAY)["built_with"] == []
