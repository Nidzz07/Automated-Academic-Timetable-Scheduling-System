"""repair() (S14a): a changed timetable stays valid and moves as little as it can.

Run on the committed real EVEN timetable (``solution.json``) with the changes of
``solver/benchmarks/real_repair.py`` and on the seeded property instances that
backtracking solves (fixed slots, lab blocks, sub-rooms, pins). repair() checks
its own result with the validator; these tests check it again against
:func:`solver.repair.apply_change`, and against the ``solution.v2`` schema.
"""

from __future__ import annotations

import copy
import json
import random

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.real_repair import CE207, INSTANCE, SCENARIOS, TEACHING
from solver.graph import build_conflict_graph
from solver.repair import apply_change, repair
from solver.slots import SlotId
from solver.tests.test_property_solved_is_valid import SEED, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

CHANGES = dict(SCENARIOS)
KURHADE_TUESDAY = CHANGES["Swapnali Kurhade unavailable all Tuesday"]
LAB_603_MONDAY = CHANGES["Lab 603 unavailable all Monday"]
FREE_DRAG = CHANGES["CE207 lecture dragged to a free slot (Wed 09.00, 601)"]
FROZEN_DRAG = CHANGES["CE207 lecture dragged onto SE-Comp A's frozen MDM-I lab (Mon 09.00, 605)"]
BUSY_DRAG = CHANGES["CE207 lecture dragged onto an occupied slot (Mon 17.15, 605)"]


@pytest.fixture(scope="module")
def real() -> tuple[dict, dict]:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    return edge_list, solution


def _by_id(solution: dict) -> dict[str, dict]:
    return {p["session_id"]: p for p in solution["assignment"]}


def _check(edge_list: dict, solution: dict, change: dict, stats: dict | None = None) -> dict:
    """repair() on copies; inputs untouched, result schema-valid, valid if solved,
    ``displaced`` exactly the sessions whose slot changed."""
    payload, before = copy.deepcopy(edge_list), copy.deepcopy(solution)
    result = repair(payload, before, change, stats=stats)
    assert payload == edge_list and before == solution
    SOLUTION_V2.validate(result)
    if result["status"] == "solved":
        assert validate_solution(apply_change(edge_list, change), result) == []
        old, new = _by_id(solution), _by_id(result)
        assert result["displaced"] == sorted(
            sid for sid in new
            if (new[sid]["day"], new[sid]["period"]) != (old[sid]["day"], old[sid]["period"])
        )
    return result


def test_free_drag_moves_only_the_dragged_lecture(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    result = _check(edge_list, solution, FREE_DRAG)
    assert result["displaced"] == [CE207]
    new, old = _by_id(result), _by_id(solution)
    assert new.pop(CE207) == {"session_id": CE207, "day": 2, "period": 0,
                              "room_id": "room-601", "sub_room_id": None}
    assert all(new[sid] == old[sid] for sid in new)  # nothing else moved, not even a room
    assert result["metadata"]["algorithm"].startswith("freeze-and-expand")


def test_busy_drag_moves_what_is_in_the_way_and_keeps_the_rest(
        real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    stats: dict = {}
    result = _check(edge_list, solution, BUSY_DRAG, stats)
    assert {CE207, "obs-t0-r4-c5-l0", "obs-t2-r5-c5-l0", "obs-t6-r5-c1-l0"} <= set(stats["hit"])
    assert _by_id(result)[CE207]["day"] == 0 and _by_id(result)[CE207]["period"] == 9
    old, new = _by_id(solution), _by_id(result)
    kept = [sid for sid in old if new[sid] == old[sid]]
    assert len(kept) >= len(old) - 10


def test_lab_603_monday_empties_603_and_moves_few(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    stats: dict = {}
    result = _check(edge_list, solution, LAB_603_MONDAY, stats)
    assert stats["hit"]  # 603 was in use on Monday
    assert not any(p["room_id"] == "room-603" and p["day"] == 0 for p in result["assignment"])
    old, new = _by_id(solution), _by_id(result)
    assert sum(new[sid] != old[sid] for sid in old) <= 10  # 156 sessions, 7 hit


def test_infeasible_changes_return_the_presolve_diagnosis(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    for change in (KURHADE_TUESDAY, FROZEN_DRAG):
        stats: dict = {}
        result = _check(edge_list, solution, change, stats)
        assert result["status"] == "infeasible"
        assert result["diagnosis"]["method"] == "presolve"
        assert result["diagnosis"]["minimal_conflicting_set"]
        assert stats["rings"][-1][0] == "all"  # only the run with everything free decides
    kurhade = repair(edge_list, solution, KURHADE_TUESDAY)
    assert "fac-swapnali-kurhade" in kurhade["diagnosis"]["minimal_conflicting_set"][0][
        "entity_ids"]


def test_a_change_that_hits_nothing_keeps_the_timetable(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    used = {(p["day"], p["period"]) for p in solution["assignment"]
            if p["room_id"] == "room-603"}
    idle = next((d, p) for d in range(5) for p in TEACHING if (d, p) not in used)
    change = {"kind": "room_unavailable", "room_id": "room-603",
              "slots": [{"day": idle[0], "period": idle[1]}]}
    result = _check(edge_list, solution, change)
    assert result["assignment"] == solution["assignment"]
    assert result["displaced"] == []
    assert result["quality"] == solution["quality"]


def test_deterministic(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    for change in (LAB_603_MONDAY, BUSY_DRAG, KURHADE_TUESDAY):
        runs = [repair(edge_list, solution, change) for _ in range(2)]
        for run in runs:
            run["metadata"].pop("runtime_ms")
        assert runs[0] == runs[1]


def test_a_timeout_is_never_infeasible(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    with pytest.raises(TimeoutError):
        repair(edge_list, solution, LAB_603_MONDAY, time_limit_s=0.0)


def test_rejects_bad_input(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    for change in (
        {"kind": "teacher_sick"},
        {"kind": "faculty_unavailable", "faculty_id": "fac-nobody", "slots": [{"day": 0,
                                                                               "period": 0}]},
        {"kind": "room_unavailable", "room_id": "room-603", "slots": []},
        {"kind": "room_unavailable", "room_id": "room-603", "slots": [{"day": 7, "period": 0}]},
        {**FREE_DRAG, "session_id": "obs-nothing"},
        {**FREE_DRAG, "room_id": "room-nowhere"},
    ):
        with pytest.raises(ValueError):
            repair(edge_list, solution, change)
    with pytest.raises(ValueError, match="solved timetable"):
        repair(edge_list, {**solution, "status": "infeasible"}, FREE_DRAG)


def test_preferred_values_reproduce_a_valid_timetable(real: tuple[dict, dict]) -> None:
    """backtrack_solve(prefer=...) tries the old place first, so a still-valid
    timetable comes back unchanged."""
    edge_list, solution = real
    old = {p["session_id"]: (SlotId(p["day"], p["period"]), p["sub_room_id"] or p["room_id"])
           for p in solution["assignment"]}
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, prefer=old)
    assert result.solved
    assert {sid: (result.assignment[sid], result.room_assignment[sid]) for sid in old} == old


def test_property_instances() -> None:
    """Random changes on solved property instances: valid or diagnosed, and when the
    hit sessions alone could be re-placed, nothing else moved."""
    solved = infeasible = frozen_only = 0
    for i in range(120):
        rng = random.Random(SEED + i)
        edge_list = generate_instance(rng)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        if not result.solved:
            continue
        solution = result.to_solution_v2_dict()
        target = rng.choice(solution["assignment"])
        session = next(s for s in edge_list["sessions"] if s["id"] == target["session_id"])
        cell = [{"day": target["day"], "period": target["period"]}]
        grid = edge_list["slot_grid"]
        change = [
            {"kind": "faculty_unavailable", "faculty_id": session["faculty_id"], "slots": cell},
            {"kind": "room_unavailable", "room_id": target["sub_room_id"] or target["room_id"],
             "slots": cell},
            {"kind": "move_session", "session_id": session["id"],
             "day": rng.randrange(grid["days"]), "period": rng.choice(grid["teaching_periods"]),
             "room_id": target["room_id"], "sub_room_id": target["sub_room_id"]},
        ][i % 3]
        stats: dict = {}
        repaired = _check(edge_list, solution, change, stats)
        if repaired["status"] == "infeasible":
            infeasible += 1
            assert stats["rings"][-1][0] == "all"
            continue
        solved += 1
        if stats["rings"][-1][0] == 0:
            frozen_only += 1
            assert set(repaired["displaced"]) <= set(stats["hit"])
    assert solved >= 20 and infeasible >= 1 and frozen_only >= 5
