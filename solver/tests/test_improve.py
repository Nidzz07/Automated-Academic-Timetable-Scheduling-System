"""improve() (S12g): local search only ever trades a valid timetable for a no-worse valid one.

Run on the real EVEN instance and on the seeded property instances that
backtracking solves (those carry fixed slots, lab blocks, sub-rooms and pins).
improve() itself re-checks its incremental penalty against
:func:`solver.scoring.score` and its result with the validator, so every run
here also exercises those checks.
"""

from __future__ import annotations

import copy
import json
import random

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.real_solve import INSTANCE
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.tests.test_property_solved_is_valid import SEED, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

MOVES = 2_000


def _solved(edge_list: dict) -> dict | None:
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    return result.to_solution_v2_dict() if result.solved else None


def _without_runtime(solution: dict) -> dict:
    out = copy.deepcopy(solution)
    out["metadata"].pop("runtime_ms")
    return out


def _check(edge_list: dict, solution: dict, moves: int = MOVES) -> dict:
    """improve() on a copy; assert valid, no worse, pins and fixed slots untouched."""
    payload = copy.deepcopy(edge_list)
    improved = improve(payload, copy.deepcopy(solution), max_moves=moves, seed=7)
    assert payload == edge_list  # pinned_occupancy and every other input untouched
    SOLUTION_V2.validate(improved)
    assert validate_solution(edge_list, improved) == []
    assert improved["quality"]["score"] >= solution["quality"]["score"]
    before = {p["session_id"]: p for p in solution["assignment"]}
    for session in edge_list["sessions"]:
        if session["fixed_slot"] is not None:
            after = next(p for p in improved["assignment"] if p["session_id"] == session["id"])
            assert after == before[session["id"]]
    return improved


@pytest.fixture(scope="module")
def real() -> tuple[dict, dict]:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = _solved(edge_list)
    assert solution is not None
    return edge_list, solution


def test_real_instance_improves_and_stays_valid(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    improved = _check(edge_list, solution)
    assert improved["quality"]["score"] > solution["quality"]["score"]
    assert "backtracking" in improved["metadata"]["algorithm"]
    assert "simulated-annealing" in improved["metadata"]["algorithm"]


def test_deterministic_for_a_fixed_seed(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    runs = [improve(edge_list, solution, max_moves=MOVES, seed=3) for _ in range(2)]
    assert _without_runtime(runs[0]) == _without_runtime(runs[1])
    other = improve(edge_list, solution, max_moves=MOVES, seed=4)
    assert other["assignment"] != runs[0]["assignment"]


def test_zero_moves_returns_the_input_timetable(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    same = improve(edge_list, solution, max_moves=0)
    assert same["assignment"] == solution["assignment"]
    assert same["quality"] == solution["quality"]


def test_property_instances_never_worse_never_invalid() -> None:
    checked = fixed = 0
    for i in range(120):
        edge_list = generate_instance(random.Random(SEED + i))
        solution = _solved(edge_list)
        if solution is None:
            continue
        _check(edge_list, solution, moves=300)
        checked += 1
        fixed += any(s["fixed_slot"] for s in edge_list["sessions"])
    assert checked >= 30 and fixed >= 5  # the sample covers fixed slots


def test_rejects_an_invalid_or_unsolved_input(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    broken = copy.deepcopy(solution)
    first, second = broken["assignment"][0], broken["assignment"][1]
    second.update(day=first["day"], period=first["period"], room_id=first["room_id"],
                  sub_room_id=first["sub_room_id"])
    with pytest.raises(ValueError, match="valid timetable"):
        improve(edge_list, broken, max_moves=10)
    with pytest.raises(ValueError, match="solved timetable"):
        improve(edge_list, {**solution, "status": "infeasible"}, max_moves=10)
