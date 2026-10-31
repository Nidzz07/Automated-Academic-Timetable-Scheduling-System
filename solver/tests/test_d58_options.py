"""D58 options (S14s): sub-rooms first, and the last-ring portfolio of repair.

Both are off by default (like D54). Off, every result is today's: the committed
``solution.json`` is re-derived with the options passed explicitly as False
(slow), and every other existing test runs unchanged. On, every timetable is
valid on the seeded property instances, and the search keeps its verdict.
"""

from __future__ import annotations

import copy
import inspect
import json
import random

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.real_repair import CE207, SCENARIOS
from solver.benchmarks.real_solve import INSTANCE, MOVES
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.repair import apply_change, repair
from solver.tests.test_property_solved_is_valid import SEED, _instances, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

SPLIT_LABS = {"room-509", "room-603", "room-606", "room-702", "room-703"}  # rooms with sub-rooms


def _without_runtime(solution: dict) -> dict:
    out = copy.deepcopy(solution)
    out["metadata"].pop("runtime_ms")
    return out


def test_options_are_off_by_default() -> None:
    for function, names in ((backtrack_solve, ["prefer_sub_rooms"]),
                            (improve, ["prefer_sub_rooms"]),
                            (repair, ["prefer_sub_rooms", "last_ring_portfolio"])):
        for name in names:
            assert inspect.signature(function).parameters[name].default is False


@pytest.mark.slow
def test_options_off_reproduce_the_committed_solution() -> None:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    start = backtrack_solve(build_conflict_graph(edge_list), edge_list,
                            prefer_sub_rooms=False).to_solution_v2_dict()
    result = improve(edge_list, start, max_moves=MOVES, seed=0, prefer_sub_rooms=False)
    committed = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    assert _without_runtime(result) == _without_runtime(committed)


def test_sub_rooms_first_on_the_real_instance() -> None:
    """Same search effort, valid, and no batch practical in a whole split lab."""
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, prefer_sub_rooms=True)
    assert result.solved and result.nodes_explored == 92
    solution = result.to_solution_v2_dict()
    assert validate_solution(edge_list, solution) == []
    assert not [p for p in solution["assignment"]
                if p["room_id"] in SPLIT_LABS and p["sub_room_id"] is None]


def test_sub_rooms_first_keeps_the_verdict_and_validity_on_property_instances() -> None:
    """The room order changes which timetable is found first, never whether one exists."""
    solved = 0
    for index, edge_list in enumerate(_instances()):
        default = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list,
                                 prefer_sub_rooms=True)
        assert result.outcome == default.outcome, index
        if result.solved:
            solved += 1
            solution = result.to_solution_v2_dict()
            assert validate_solution(edge_list, solution) == [], index
            if index < 60:
                improved = improve(edge_list, solution, max_moves=300, seed=7,
                                   prefer_sub_rooms=True)
                assert validate_solution(edge_list, improved) == [], index
                assert improved["quality"]["score"] >= solution["quality"]["score"]
    assert solved >= 100


def test_repair_with_both_options_on_property_instances() -> None:
    """Random changes, as test_repair's property test: valid if solved, a schema-valid
    diagnosis if not, and nothing left unanswered."""
    solved = infeasible = 0
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
        out = repair(edge_list, solution, change, prefer_sub_rooms=True,
                     last_ring_portfolio=True)
        SOLUTION_V2.validate(out)
        if out["status"] == "solved":
            solved += 1
            assert validate_solution(apply_change(edge_list, change), out) == [], i
        else:
            infeasible += 1
    assert solved >= 20 and infeasible >= 1


@pytest.mark.slow
def test_the_portfolio_repairs_the_s14l_drag() -> None:
    """S14l's accumulated sequence (test_repair.py: the drag times out today). With the
    portfolio the capped every-session-free ring runs out and the fallback repairs it."""
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    for change in (
        SCENARIOS[4][1],  # Swapnali Kurhade unavailable Tue P5-P9, accepted
        {"kind": "substitute_faculty", "session_id": CE207,
         "faculty_id": "fac-prasenjit-bhavathankar"},  # accepted
    ):
        solution = repair(edge_list, solution, change, time_limit_s=60.0)
        edge_list = apply_change(edge_list, change)
    drag = {"kind": "move_session", "session_id": CE207, "day": 2, "period": 0,
            "room_id": "room-601", "sub_room_id": None}
    stats: dict = {}
    out = repair(edge_list, solution, drag, time_limit_s=60.0, last_ring_portfolio=True,
                 stats=stats)
    assert out["status"] == "solved"
    assert stats["rings"][-2][0] == "all" and stats["rings"][-2][2] == "timeout"
    assert stats["rings"][-1] == ["fallback", 156, "solved"]
    assert validate_solution(apply_change(edge_list, drag), out) == []
