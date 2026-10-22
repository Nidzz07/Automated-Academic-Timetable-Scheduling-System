"""The real EVEN SE+TE instance (S12a, S12d, S12g): the committed result is reproducible.

Re-solving ``data/instances/even-2025-26/edge_list.json`` - backtracking, then the
S12g local search with its committed seed and budget - must give the committed
``solution.json`` (all but its wall-clock ``metadata.runtime_ms``), or, when the
search runs out of time, no ``solution.json`` at all (ROADMAP D33). It runs in
about 20 s, so it is no longer ``slow``: CI guards the real solve on every push,
and a run over 60 s fails.
"""

from __future__ import annotations

import json
import time

from solver.benchmarks.real_solve import INSTANCE, run
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

CAP_S = 60.0


def test_real_instance_reproduces_the_committed_result() -> None:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    record, solution = run(edge_list, time_limit_s=CAP_S)
    elapsed = time.perf_counter() - started
    assert elapsed < CAP_S, f"the real solve took {elapsed:.1f} s, over the {CAP_S:g} s cap"
    committed = INSTANCE / "solution.json"
    if solution is None:
        assert record["outcome"] == "timeout" and record["presolve"] == "passed"
        assert not committed.exists()
        return
    SOLUTION_V2.validate(solution)
    assert validate_solution(edge_list, solution) == []
    assert not record["local_search"]["timed_out"]
    assert record["score"] >= record["score_backtracking"]
    expected = json.loads(committed.read_text(encoding="utf-8"))
    for payload in (solution, expected):
        payload["metadata"].pop("runtime_ms")
    assert solution == expected
