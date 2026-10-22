"""S12g: :func:`solver.improve.improve`, the local search after backtracking.

On the seeded property instances, the synthetic presets and the D6 grid example:
the result always passes ``validate_solution`` and ``solution.v2``, never scores below
its input, is the same for the same seed and budget, leaves pins and fixed sessions
where they are, and never moves a lab block onto its year's lunch. The instances are
test data (D19), not SPIT facts.
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.improve import _exp, improve
from solver.slots import SlotGrid, SlotId
from solver.tests.test_d6_grid import TE_BLOCK, TE_LUNCH, _d6, _with_te_block
from solver.tests.test_property_solved_is_valid import SEED, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

MOVES = 600  # per property instance: enough to move, small enough for 400 instances


def _solved(edge_list: dict[str, Any]) -> dict[str, Any] | None:
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    return result.to_solution_v2_dict() if result.solved else None


def _starts(solution: dict[str, Any]) -> dict[str, tuple[int, int]]:
    return {p["session_id"]: (p["day"], p["period"]) for p in solution["assignment"]}


def _property_cases() -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    cases = []
    for index in range(400):
        edge_list = generate_instance(random.Random(SEED + index))
        solution = _solved(edge_list)
        if solution is not None:
            cases.append((index, edge_list, solution))
    return cases


@pytest.fixture(scope="module")
def property_cases() -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    return _property_cases()


def _check(edge_list: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> None:
    """Valid, schema-conforming, no worse, and every fixed session where it was."""
    assert validate_solution(edge_list, after) == []
    SOLUTION_V2.validate(after)
    assert after["quality"]["score"] >= before["quality"]["score"]
    starts, was = _starts(after), _starts(before)
    for s in edge_list["sessions"]:
        if s["fixed_slot"] is not None:
            assert starts[s["id"]] == was[s["id"]] == (s["fixed_slot"]["day"],
                                                         s["fixed_slot"]["period"])


class TestPropertyInstances:
    def test_valid_no_worse_and_pins_untouched(self, property_cases: list[Any]) -> None:
        assert len(property_cases) == 172  # the S12d verdicts: 172 of 400 solved
        moved = 0
        for index, edge_list, solution in property_cases:
            frozen_input = copy.deepcopy((edge_list, solution))
            after = improve(edge_list, solution, max_moves=MOVES, seed=index)
            assert (edge_list, solution) == frozen_input, f"instance {index}: input modified"
            _check(edge_list, solution, after)
            moved += _starts(after) != _starts(solution)
        assert moved > 0  # the search does move timetables, it is not a no-op

    def test_same_seed_same_timetable(self, property_cases: list[Any]) -> None:
        for index, edge_list, solution in property_cases[:40]:
            first = improve(edge_list, solution, max_moves=MOVES, seed=7)
            second = improve(edge_list, solution, max_moves=MOVES, seed=7)
            for payload in (first, second):
                payload["metadata"].pop("runtime_ms")
            assert first == second, f"instance {index}"


class TestPresets:
    @pytest.mark.parametrize("name", ["small", "medium"])
    def test_preset_improves_validly(self, name: str) -> None:
        edge_list = generate(PRESETS[name], 1)
        solution = _solved(edge_list)
        assert solution is not None
        stats: dict[str, Any] = {}
        after = improve(edge_list, solution, max_moves=3000, seed=0, stats=stats)
        _check(edge_list, solution, after)
        assert stats["proposals"] == 3000 and not stats["timed_out"]
        assert stats["penalty_after"] == pytest.approx(100.0 - after["quality"]["score"])
        assert after["metadata"]["algorithm"] == (
            "backtracking(forward-checking, mrv) + local-search(simulated-annealing, "
            "seed=0, moves=3000)")
        assert after["metadata"]["backtracks"] == solution["metadata"]["backtracks"]


class TestD6Grid:
    def test_lab_block_never_moves_onto_its_lunch(self) -> None:
        edge_list = _with_te_block(_d6())
        solution = _solved(edge_list)
        assert solution is not None
        grid = SlotGrid.from_payload(edge_list["slot_grid"])
        for seed in range(10):
            after = improve(edge_list, solution, max_moves=500, seed=seed)
            _check(edge_list, solution, after)
            starts = _starts(after)
            assert starts[TE_BLOCK[0]] == starts[TE_BLOCK[1]]
            day, period = starts[TE_BLOCK[0]]
            nxt = grid.teaching_periods[grid.teaching_periods.index(period) + 1]
            assert TE_LUNCH not in (period, nxt) and grid.is_adjacent(
                SlotId(day, period), SlotId(day, nxt))


class TestInput:
    def test_refuses_an_invalid_timetable(self) -> None:
        edge_list = generate(PRESETS["small"], 1)
        solution = _solved(edge_list)
        assert solution is not None
        bad = copy.deepcopy(solution)
        bad["assignment"][1].update(day=bad["assignment"][0]["day"],
                                    period=bad["assignment"][0]["period"],
                                    room_id=bad["assignment"][0]["room_id"],
                                    sub_room_id=bad["assignment"][0]["sub_room_id"])
        assert validate_solution(edge_list, bad)
        with pytest.raises(ValueError, match="not valid"):
            improve(edge_list, bad, max_moves=10)

    def test_refuses_an_unsolved_result(self) -> None:
        with pytest.raises(ValueError, match="solved"):
            improve({}, {"status": "infeasible"}, max_moves=10)

    def test_zero_moves_returns_the_input_timetable(self) -> None:
        edge_list = generate(PRESETS["small"], 2)
        solution = _solved(edge_list)
        assert solution is not None
        after = improve(edge_list, solution, max_moves=0)
        assert after["assignment"] == solution["assignment"]
        assert after["quality"] == solution["quality"]


def test_exp_matches_the_library() -> None:
    for x in [0.0, -1e-9, -0.25, -0.5, -0.51, -1.0, -3.3, -10.0, -59.0]:
        assert _exp(x) == pytest.approx(math.exp(x), rel=1e-13)
    assert _exp(-61.0) == 0.0
