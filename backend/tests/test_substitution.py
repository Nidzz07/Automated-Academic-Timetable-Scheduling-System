"""S14g: protected break pins, substitutes and substitutions through the API (ROADMAP D41,
D52, D53).

Runs on copies of the real EVEN instance (edge list, committed solution, display.json and
qualifications.json) in a scratch directory, as test_repair.py does.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.store import INSTANCES_DIR
from backend.tests.conftest import bearer
from backend.tests.test_api import REAL, client_for, conforms, solve, without_runtime
from backend.tests.test_repair import accept, audit, run, start
from solver.repair import apply_change, repair, substitute_candidates
from solver.validate import validate_solution

FILES = ("edge_list.json", "solution.json", "display.json", "qualifications.json")
LECTURE = "obs-t0-r1-c3-l0"  # CE207 lecture of SE-Comp A, Anant Nimkar, Thu P4, 605
PRACTICAL = "obs-t0-r4-c1-l0"  # CE206 practical of SE-Comp A batch A, Amey Ganesh Nile
# S14e's drag onto SE lunch, Wed P5 (display.json pins[5])
LUNCH_DRAG = {"kind": "move_session", "session_id": LECTURE, "day": 2, "period": 5,
              "room_id": "room-605"}


def sub(session_id: str, faculty_id: str) -> dict[str, str]:
    return {"kind": "substitute_faculty", "session_id": session_id, "faculty_id": faculty_id}


def read(name: str) -> Any:
    return json.loads((INSTANCES_DIR / REAL / name).read_text("utf-8"))


@pytest.fixture(scope="module")
def lunch() -> list[int]:
    return [i for i, pin in enumerate(read("display.json")["pins"]) if pin["kind"] == "lunch"]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory, database_url: str) -> Iterator[TestClient]:
    """``subs``, ``sub-accumulates``: the real instance with its sidecars; ``bare``: without
    display.json or qualifications.json; ``relabelled``: pins 0, 1 marked coffee and
    break, pin 5 (SE lunch) marked an activity, and Nataasha Raul listed for CE207
    practicals only; ``sub-unsolved``: the edge list and sidecars, no solution."""
    root = tmp_path_factory.mktemp("substitution")
    for name, files in (("subs", FILES), ("sub-accumulates", FILES), ("bare", FILES[:2]),
                        ("relabelled", FILES), ("sub-unsolved", FILES[:1] + FILES[2:])):
        (root / name).mkdir()
        for file in files:
            shutil.copy(INSTANCES_DIR / REAL / file, root / name / file)
    display, sheet = read("display.json"), read("qualifications.json")
    for i, kind in ((0, "coffee"), (1, "break"), (5, "activity")):
        display["pins"][i]["kind"] = kind
    for listed in sheet["subjects"]["subj-ce207"]["faculty"]:
        if listed["faculty_id"] == "fac-nataasha-raul":
            listed["session_type"] = "lab"
    (root / "relabelled" / "display.json").write_text(json.dumps(display), encoding="utf-8")
    (root / "relabelled" / "qualifications.json").write_text(json.dumps(sheet),
                                                             encoding="utf-8")
    with client_for(root, database_url) as c:
        yield c


class TestProtected:
    def test_break_pins_by_kind(self, client: TestClient, lunch: list[int]) -> None:
        service, edge_list = client.app.state.service, read("edge_list.json")
        assert len(lunch) == 10 and 5 in lunch
        assert service.protected("subs", edge_list) == lunch
        assert service.protected("bare", edge_list) == []
        # by the kind display.json gives, never by the pin's shape (D41)
        assert service.protected("relabelled", edge_list) == [0, 1] + [
            i for i in lunch if i not in (0, 1, 5)]

    def test_repair_never_suggests_relaxing_a_break(
        self, client: TestClient, lunch: list[int]
    ) -> None:
        """S14e's lunch drag: freeing SE-Comp A from its lunch is suggested only where
        display.json does not mark that pin as a break."""
        edge_list, committed = read("edge_list.json"), read("solution.json")
        protected = run(client, "subs", LUNCH_DRAG)["solution"]
        assert protected["status"] == "infeasible" and conforms("solution_v2", protected)
        assert without_runtime(protected) == without_runtime(
            repair(edge_list, committed, LUNCH_DRAG, time_limit_s=60, protected=lunch))
        diagnosis = protected["diagnosis"]
        assert {m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]} == {
            "pin.5", "change"}
        assert diagnosis["suggested_relaxation"]["action"]["action_type"] == "MANUAL"

        for instance in ("bare", "relabelled"):
            relaxation = run(client, instance, LUNCH_DRAG)["solution"]["diagnosis"][
                "suggested_relaxation"]
            assert relaxation["action"]["action_type"] == "RELAX_PINNED_BLOCK", instance


class TestSubstitutes:
    def get(self, client: TestClient, session_id: str, instance: str = "subs", **kw: Any):
        return client.get(f"/instances/{instance}/sessions/{session_id}/substitutes", **kw)

    def test_lecture(self, client: TestClient) -> None:
        body = self.get(client, LECTURE).json()
        assert body["faculty_id"] == "fac-anant-nimkar"
        assert body["candidates"] == [
            {"faculty_id": "fac-prasenjit-bhavathankar", "score_change": 0.0},
            {"faculty_id": "fac-nataasha-raul", "score_change": -2.0},
        ]
        [dhage] = body["left_out"]
        assert (dhage["faculty_id"], dhage["reasons"]) == ("fac-sudhir-dhage", ["busy"])
        assert [(v["kind"], v["session_ids"]) for v in dhage["violations"]] == [
            ("FACULTY_CLASH", [LECTURE, "obs-t6-r4-c4-l1"])]

    def test_practical(self, client: TestClient) -> None:
        body = self.get(client, PRACTICAL).json()
        assert body["faculty_id"] == "fac-amey-ganesh-nile"
        assert body["candidates"] == [
            {"faculty_id": "fac-aishwarya-nalawade", "score_change": -1.0}]
        assert [(o["faculty_id"], o["reasons"]) for o in body["left_out"]] == [
            ("fac-kailas-devadkar", ["busy"]), ("fac-swapnali-kurhade", ["unavailable"])]

    def test_is_the_solver_on_the_qualified_faculty(self, client: TestClient) -> None:
        sheet = read("qualifications.json")["subjects"]["subj-ce207"]["faculty"]
        qualified = [f["faculty_id"] for f in sheet]
        expected = substitute_candidates(read("edge_list.json"), read("solution.json"),
                                         LECTURE, qualified)
        assert self.get(client, LECTURE).json()["candidates"] == expected

    def test_session_type(self, client: TestClient) -> None:
        """Listed for CE207 practicals only, Nataasha Raul is no lecture substitute."""
        body = self.get(client, LECTURE, "relabelled").json()
        listed = [c["faculty_id"] for c in body["candidates"] + body["left_out"]]
        assert listed == ["fac-prasenjit-bhavathankar", "fac-sudhir-dhage"]

    def test_no_qualifications_no_substitutes(self, client: TestClient) -> None:
        body = self.get(client, LECTURE, "bare").json()
        assert body["candidates"] == body["left_out"] == []

    def test_refused(self, client: TestClient) -> None:
        assert self.get(client, "no-such-session").status_code == 404
        assert self.get(client, LECTURE, "nope").status_code == 404
        assert self.get(client, LECTURE, "sub-unsolved").status_code == 409
        for role in ("faculty", "student"):
            assert self.get(client, LECTURE, headers=bearer(role)).status_code == 403
        assert self.get(client, LECTURE, headers=bearer("administrator")).status_code == 200


class TestSubstitution:
    @pytest.mark.parametrize("change", [
        sub(LECTURE, "fac-kailas-devadkar"),  # teaches CE206, not CE207
        sub(LECTURE, "fac-anant-nimkar"),  # already teaches it
        sub("no-such-session", "fac-sudhir-dhage"),
        sub(LECTURE, "fac-nobody"),
        {"kind": "substitute_faculty", "session_id": LECTURE},
    ], ids=["not-qualified", "same-teacher", "session", "faculty", "no-faculty"])
    def test_refused_and_not_queued(
        self, client: TestClient, database_url: str, change: dict[str, str]
    ) -> None:
        response = client.post("/instances/subs/repair", headers=bearer("coordinator", "s422"),
                               json={"change": change})
        assert response.status_code == 422, response.text
        assert audit(database_url, "s422", "repair") == []

    def test_type_mismatch_is_not_qualified(self, client: TestClient) -> None:
        assert start(client, "relabelled", sub(LECTURE, "fac-nataasha-raul")).status_code == 422

    def test_accepted_substitutions_accumulate(
        self, client: TestClient, database_url: str, lunch: list[int]
    ) -> None:
        """D52: an accepted substitution stays in every later repair, substitutes list and
        solve, until an administrator clears it; it is audited."""
        edge_list, committed = read("edge_list.json"), read("solution.json")
        change = sub(LECTURE, "fac-prasenjit-bhavathankar")
        first = run(client, "sub-accumulates", change)
        assert (first["status"], first["change"], first["built_with"]) == (
            "solved", change, [])
        assert without_runtime(first["solution"]) == without_runtime(
            repair(edge_list, committed, change, time_limit_s=60, protected=lunch))
        assert first["solution"]["displaced"] == []  # he is free there: nothing moves
        assert accept(client, first["id"], "coordinator", "substituter").status_code == 200
        assert [c["change"] for c in client.get("/instances/sub-accumulates/changes").json()] == [
            change]

        subbed = apply_change(edge_list, change)
        listed = client.get(f"/instances/sub-accumulates/sessions/{LECTURE}/substitutes").json()
        assert listed["faculty_id"] == "fac-prasenjit-bhavathankar"
        assert listed["candidates"] == substitute_candidates(
            subbed, first["solution"], LECTURE, ["fac-anant-nimkar", "fac-nataasha-raul",
                                                 "fac-prasenjit-bhavathankar",
                                                 "fac-sudhir-dhage"])

        # a later repair is built with it, and may undo it
        back = run(client, "sub-accumulates", sub(LECTURE, "fac-anant-nimkar"))
        assert (back["status"], back["base"], back["built_with"]) == (
            "solved", first["id"], [first["id"]])
        again = start(client, "sub-accumulates", change)
        assert again.status_code == 422  # he already teaches it

        solved = solve(client, "sub-accumulates", max_moves=0)
        assert solved["status"] == "solved" and solved["built_with"] == [first["id"]]
        assert validate_solution(subbed, solved["solution"]) == []

        assert [json.loads(r.detail)["job_id"]
                for r in audit(database_url, "substituter", "accept")] == [first["id"]]
        [row] = [r for r in audit(database_url, "test-coordinator", "repair")
                 if json.loads(r.detail)["job_id"] == first["id"]]
        assert json.loads(row.detail)["change"] == change

        cleared = client.delete("/instances/sub-accumulates/changes",
                                headers=bearer("administrator"))
        assert [c["job_id"] for c in cleared.json()] == [first["id"]]
        assert client.get(f"/instances/sub-accumulates/sessions/{LECTURE}/substitutes").json()[
            "faculty_id"] == "fac-anant-nimkar"
