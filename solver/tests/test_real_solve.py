"""The real EVEN SE+TE instance (S12a, S12d): the committed result is reproducible.

Re-solving ``data/instances/even-2025-26/edge_list.json`` must give the
committed ``solution.json`` (all but its wall-clock ``metadata.runtime_ms``), or,
when the search runs out of time, no ``solution.json`` at all (ROADMAP D33).
Since S12d the search solves it in under a second; the test stays ``slow`` so
that a search regression back to a timeout spends its 300 s only under -m slow.
"""

from __future__ import annotations

import json

import pytest

from solver.benchmarks.real_solve import INSTANCE, run
from solver.tests.test_solution_v2 import SOLUTION_V2


@pytest.mark.slow
def test_real_instance_reproduces_the_committed_result() -> None:
    record, solution = run(json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8")))
    committed = INSTANCE / "solution.json"
    if solution is None:
        assert record["outcome"] == "timeout" and record["presolve"] == "passed"
        assert not committed.exists()
        return
    SOLUTION_V2.validate(solution)
    expected = json.loads(committed.read_text(encoding="utf-8"))
    for payload in (solution, expected):
        payload["metadata"].pop("runtime_ms")
    assert solution == expected
