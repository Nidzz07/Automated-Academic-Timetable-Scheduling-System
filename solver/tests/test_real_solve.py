"""The real EVEN SE+TE instance (S12a, S12d, S12g).

The committed ``data/instances/even-2025-26/solution.json`` is backtracking
followed by :func:`solver.improve.improve` with
:data:`solver.benchmarks.real_solve.MOVES` moves and seed 0, about 2 min of
work, so re-running all of it and comparing with the file is ``slow``. No test
here depends on wall-clock speed: CI checks that backtracking solves the
instance, that the committed file is valid and carries its own score, and that
a small local-search budget gives a valid, no-worse, reproducible timetable.
``CAP_S`` is only a safety net, far above what any of them needs. S12h: the
documented ``extended_moves`` run is re-run under ``slow`` too, checked by score
and assignment digest.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.real_solve import INSTANCE, run
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.scoring import score
from solver.slots import SlotId
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

CAP_S = 600.0
MOVES = 5_000
# S12h: the documented extended run (docs/real-solve-even-2025-26.md): from the backtracking
# timetable, seed 0, D58 defaults (S14u); its score and the sha256 of its assignment, for a second
# machine to confirm
EXTENDED_MOVES = 1_000_000
EXTENDED_SCORE = 26.0
EXTENDED_SHA256 = "035a6cedb05998551f9549a2f1ec714176c0eeddd8f547060055cffef07c53c2"


def _without_runtime(solution: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(solution)
    out["metadata"].pop("runtime_ms")
    return out


@pytest.fixture(scope="module")
def edge_list() -> dict[str, Any]:
    return json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def solved(edge_list: dict[str, Any]) -> dict[str, Any]:
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, time_limit_s=CAP_S)
    assert result.outcome == "solved"
    return result.to_solution_v2_dict()


def test_backtracking_solves_the_real_instance(
    edge_list: dict[str, Any], solved: dict[str, Any]
) -> None:
    SOLUTION_V2.validate(solved)
    assert validate_solution(edge_list, solved) == []


def test_committed_solution_is_valid_and_scored(edge_list: dict[str, Any]) -> None:
    committed = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    SOLUTION_V2.validate(committed)
    assert committed["status"] == "solved"
    assert validate_solution(edge_list, committed) == []
    starts = {p["session_id"]: SlotId(p["day"], p["period"]) for p in committed["assignment"]}
    assert committed["quality"] == score(edge_list, starts)


def test_small_local_search_is_valid_never_worse_and_reproducible(
    edge_list: dict[str, Any], solved: dict[str, Any]
) -> None:
    runs = []
    for _ in range(2):
        stats: dict[str, Any] = {}
        improved = improve(edge_list, copy.deepcopy(solved), max_moves=MOVES,
                           time_limit_s=CAP_S, stats=stats)
        assert not stats["stopped_by_time"] and stats["proposed"] == MOVES
        SOLUTION_V2.validate(improved)
        assert validate_solution(edge_list, improved) == []
        assert improved["quality"]["score"] >= solved["quality"]["score"]
        runs.append(_without_runtime(improved))
    assert runs[0] == runs[1]


@pytest.mark.slow
def test_real_instance_reproduces_the_committed_result(edge_list: dict[str, Any]) -> None:
    record, solution = run(copy.deepcopy(edge_list))
    assert record["outcome"] == "solved" and solution is not None
    assert not record["improve"]["stopped_by_time"]
    SOLUTION_V2.validate(solution)
    expected = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    assert _without_runtime(solution) == _without_runtime(expected)


@pytest.mark.slow
def test_extended_run_reproduces_the_documented_result(
    edge_list: dict[str, Any], solved: dict[str, Any]
) -> None:
    stats: dict[str, Any] = {}
    result = improve(edge_list, solved, max_moves=EXTENDED_MOVES, seed=0, extended_moves=True,
                     time_limit_s=CAP_S, stats=stats)
    assert not stats["stopped_by_time"] and stats["proposed"] == EXTENDED_MOVES
    assert validate_solution(edge_list, result) == []
    assert result["quality"]["score"] == EXTENDED_SCORE
    digest = hashlib.sha256(json.dumps(result["assignment"], sort_keys=True).encode())
    assert digest.hexdigest() == EXTENDED_SHA256
