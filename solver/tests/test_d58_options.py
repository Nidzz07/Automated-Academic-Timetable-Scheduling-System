"""D58 options (S14s): sub-rooms first, and the last-ring portfolio of repair.

Both are on by default since S14u (D58). Off, every result is the pre-S14u one:
the solution.json committed before S14u (score -15.0) is re-derived with the
options passed explicitly as False and checked by its digest (slow); the
committed ``solution.json`` itself is re-derived with the defaults by
``test_real_solve.py`` (slow). On, every timetable is valid on the seeded
property instances, and the search keeps its verdict.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import random
import time

import pytest

from solver.backtracking import SUB_ROOM_NODES, backtrack_solve
from solver.benchmarks.real_repair import CE207, SCENARIOS
from solver.benchmarks.real_solve import INSTANCE, MOVES
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.repair import RING_NODES, apply_change, repair
from solver.tests.test_property_solved_is_valid import SEED, _instances, generate_instance
from solver.tests.test_search_equivalence import _odd_cycle
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

SPLIT_LABS = {"room-509", "room-603", "room-606", "room-702", "room-703"}  # rooms with sub-rooms
# sha256 of json.dumps(assignment, sort_keys=True) of solution.json as committed before S14u
PRE_S14U_SHA256 = "70040ba1869cbabdf6dd53ce293c9502cc17782fc75c7b88552b1cebab52a17d"


def test_options_are_on_by_default() -> None:
    for function, names in ((backtrack_solve, ["prefer_sub_rooms"]),
                            (improve, ["prefer_sub_rooms"]),
                            (repair, ["prefer_sub_rooms", "last_ring_portfolio"])):
        for name in names:
            assert inspect.signature(function).parameters[name].default is True


@pytest.mark.slow
def test_options_off_reproduce_the_pre_s14u_solution() -> None:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    start = backtrack_solve(build_conflict_graph(edge_list), edge_list,
                            prefer_sub_rooms=False).to_solution_v2_dict()
    result = improve(edge_list, start, max_moves=MOVES, seed=0, prefer_sub_rooms=False)
    assert result["quality"]["score"] == -15.0
    digest = hashlib.sha256(json.dumps(result["assignment"], sort_keys=True).encode())
    assert digest.hexdigest() == PRE_S14U_SHA256


def test_sub_rooms_first_on_the_real_instance() -> None:
    """Same search effort, valid, and no batch practical in a whole split lab."""
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    stats: dict = {}
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, prefer_sub_rooms=True,
                             stats=stats)
    assert result.solved and result.nodes_explored == 92 and not result.rooms_by_id_fallback
    assert stats["attempts"] == [["sub-rooms first", 92, "solved"]]  # solution.json: one attempt
    solution = result.to_solution_v2_dict()
    assert validate_solution(edge_list, solution) == []
    assert not [p for p in solution["assignment"]
                if p["room_id"] in SPLIT_LABS and p["sub_room_id"] is None]


# The SE-Comp A CE207 lecture given to Sudhir Dhage, free at its slot: feasible, but sub-rooms
# first alone did not finish a fresh solve at 30 s or 120 s, where rooms by id take 92 nodes (S14u)
DHAGE = {"kind": "substitute_faculty", "session_id": CE207, "faculty_id": "fac-sudhir-dhage"}


def test_the_first_attempt_gets_repairs_ring_budget() -> None:
    assert SUB_ROOM_NODES == RING_NODES  # the rule that fixes it: never chosen by a score


def test_a_fresh_solve_falls_back_to_rooms_by_id() -> None:
    """As the backend's solve job calls it (30 s): the sub-rooms-first attempt runs out of its
    nodes, rooms by id solve it; stats and the metadata say which attempt solved."""
    edge_list = apply_change(
        json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8")), DHAGE)
    stats: dict = {}
    began = time.perf_counter()
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, time_limit_s=30.0,
                             stats=stats)
    assert result.solved and result.rooms_by_id_fallback
    assert time.perf_counter() - began < 15.0  # about 1.8 s here
    assert stats["attempts"] == [["sub-rooms first", SUB_ROOM_NODES + 1, "timeout"],
                                 ["rooms by id", 92, "solved"]]
    assert result.nodes_explored == SUB_ROOM_NODES + 1 + 92
    solution = result.to_solution_v2_dict()
    SOLUTION_V2.validate(solution)
    assert validate_solution(edge_list, solution) == []
    assert solution["metadata"]["algorithm"] == (
        f"backtracking(forward-checking, mrv), rooms by id after {SUB_ROOM_NODES} nodes")

    alone = backtrack_solve(build_conflict_graph(edge_list), edge_list, time_limit_s=3.0,
                            sub_room_nodes=None)
    assert alone.outcome == "timeout"  # the regression: one attempt, never infeasible (D33)


@pytest.mark.parametrize("instance", [generate(PRESETS["infeasible"], 1), _odd_cycle()],
                         ids=["presolve", "search"])
def test_a_verdict_of_the_first_attempt_stands(instance: dict) -> None:
    """Infeasible, proven by pre-solve or by search within the budget: no second attempt."""
    stats: dict = {}
    result = backtrack_solve(build_conflict_graph(instance), instance, time_limit_s=60.0,
                             stats=stats)
    assert result.outcome == "infeasible" and not result.rooms_by_id_fallback
    assert [a[0] for a in stats["attempts"]] == ["sub-rooms first"]


def test_sub_rooms_first_keeps_the_verdict_and_validity_on_property_instances() -> None:
    """The room order changes which timetable is found first, never whether one exists."""
    solved = 0
    for index, edge_list in enumerate(_instances()):
        default = backtrack_solve(build_conflict_graph(edge_list), edge_list,
                                  prefer_sub_rooms=False)
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
    """S14l's accumulated sequence, from the S14u solution.json with the defaults (the drag
    timed out before S14u). The capped every-session-free ring runs out and the fallback
    repairs it."""
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
