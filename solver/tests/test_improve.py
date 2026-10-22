"""improve() (S12g): local search only ever trades a valid timetable for a no-worse valid one.

Run on the real EVEN instance and on the seeded property instances that
backtracking solves (those carry fixed slots, lab blocks, sub-rooms and pins).
improve() itself re-checks its incremental penalty against
:func:`solver.scoring.score` and its result with the validator, so every run
here also exercises those checks.

S12h: with ``extended_moves`` off (the default) every result and every count is
the one recorded from ``solver/improve.py`` before S12h (commit 748993e); with
it on, the same checks hold and the extended moves are used.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.real_solve import INSTANCE
from solver.graph import build_conflict_graph
from solver.improve import improve
from solver.tests.test_property_solved_is_valid import SEED, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

MOVES = 2_000
# sha256 of improve()'s results (metadata.runtime_ms dropped) and stats, recorded at commit
# 748993e, before S12h, and identical under PYTHONHASHSEED 1 and 12345
OFF_DIGESTS = {
    "real": "66e046f5985cd7fe120c72d354d4d4c08245e3bd47a942eebcf6d6345fb95fd9",
    "property": "2953714860b2139920bee35f287b3c37f00bd97ddb7f708b81a1b78f02de7854",
}
REAL_RUNS = ((0, 5_000), (1, 5_000), (2, 5_000), (0, 20_000))  # (seed, moves)


def _solved(edge_list: dict) -> dict | None:
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    return result.to_solution_v2_dict() if result.solved else None


def _without_runtime(solution: dict) -> dict:
    out = copy.deepcopy(solution)
    out["metadata"].pop("runtime_ms")
    return out


def _check(edge_list: dict, solution: dict, moves: int = MOVES, extended: bool = False,
           stats: dict | None = None) -> dict:
    """improve() on a copy; assert valid, no worse, pins and fixed slots untouched."""
    payload = copy.deepcopy(edge_list)
    improved = improve(payload, copy.deepcopy(solution), max_moves=moves, seed=7,
                       extended_moves=extended, stats=stats)
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


# --- S12h: extended moves (Kempe chains, moves aimed at gaps) -------------------------------


def _fingerprint(result: dict, stats: dict) -> dict:
    return {"result": _without_runtime(result), "stats": stats}


def _digest(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()


def test_extended_moves_are_off_by_default() -> None:
    assert inspect.signature(improve).parameters["extended_moves"].default is False


def test_option_off_reproduces_the_pre_s12h_results(real: tuple[dict, dict]) -> None:
    """Off, every result and every move count is the one recorded before S12h, on the real
    instance and on the property instances; solution.json itself is re-derived by the slow
    test in test_real_solve.py."""
    edge_list, solution = real
    runs = []
    for seed, moves in REAL_RUNS:
        stats: dict = {}
        result = improve(edge_list, solution, max_moves=moves, seed=seed, extended_moves=False,
                         stats=stats)
        runs.append(_fingerprint(result, stats))
    instances = []
    for i in range(60):
        instance = generate_instance(random.Random(SEED + i))
        start = _solved(instance)
        if start is None:
            continue
        stats = {}
        result = improve(instance, start, max_moves=300, seed=7, extended_moves=False, stats=stats)
        instances.append(_fingerprint(result, stats))
    assert len(instances) == 31
    assert {"real": _digest(runs), "property": _digest(instances)} == OFF_DIGESTS


def test_extended_real_instance_stays_valid_and_uses_the_new_moves(
        real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    stats: dict = {}
    improved = _check(edge_list, solution, moves=5_000, extended=True, stats=stats)
    assert improved["quality"]["score"] > solution["quality"]["score"]
    assert "extended-moves" in improved["metadata"]["algorithm"]
    assert stats["accepted_by_kind"]["kempe"] > 0 and stats["accepted_by_kind"]["gap"] > 0


def test_extended_property_instances_never_worse_never_invalid() -> None:
    checked = fixed = 0
    for i in range(120):
        edge_list = generate_instance(random.Random(SEED + i))
        solution = _solved(edge_list)
        if solution is None:
            continue
        _check(edge_list, solution, moves=300, extended=True)
        checked += 1
        fixed += any(s["fixed_slot"] for s in edge_list["sessions"])
    assert checked >= 30 and fixed >= 5


def test_extended_never_moves_a_fixed_session() -> None:
    """Every session fixed where backtracking put it: no unit may move, so no chain or
    gap move starts and the timetable comes back as it went in."""
    checked = 0
    for i in range(60):
        edge_list = generate_instance(random.Random(SEED + i))
        solution = _solved(edge_list)
        if solution is None:
            continue
        placed = {p["session_id"]: p for p in solution["assignment"]}
        for session in edge_list["sessions"]:
            p = placed[session["id"]]
            session["fixed_slot"] = {"day": p["day"], "period": p["period"]}
        stats: dict = {}
        improved = improve(edge_list, solution, max_moves=300, seed=7, extended_moves=True,
                           stats=stats)
        assert improved["assignment"] == solution["assignment"] and stats["accepted"] == 0
        checked += 1
    assert checked >= 20


_CHILD = """
import hashlib, json
from solver.backtracking import backtrack_solve
from solver.benchmarks.real_solve import INSTANCE
from solver.graph import build_conflict_graph
from solver.improve import improve
edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
start = backtrack_solve(build_conflict_graph(edge_list), edge_list).to_solution_v2_dict()
result = improve(edge_list, start, max_moves={moves}, seed=3, extended_moves=True)
result["metadata"].pop("runtime_ms")
print(hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest())
"""


def test_extended_deterministic_for_a_fixed_seed(real: tuple[dict, dict]) -> None:
    """Same seed, same result and counts, also in fresh processes with other string hash
    seeds (set iteration order changes with them); another seed, another timetable."""
    edge_list, solution = real
    runs = []
    for _ in range(2):
        stats: dict = {}
        result = improve(edge_list, solution, max_moves=MOVES, seed=3, extended_moves=True,
                         stats=stats)
        runs.append(_fingerprint(result, stats))
    assert runs[0] == runs[1]
    repo = Path(__file__).resolve().parents[2]
    for hash_seed in ("1", "12345"):
        child = subprocess.run([sys.executable, "-c", _CHILD.format(moves=MOVES)], cwd=repo,
                               check=True,
                               capture_output=True, text=True,
                               env={**os.environ, "PYTHONHASHSEED": hash_seed})
        assert child.stdout.strip() == _digest(runs[0]["result"])
    other = improve(edge_list, solution, max_moves=MOVES, seed=4, extended_moves=True)
    assert other["assignment"] != runs[0]["result"]["assignment"]
