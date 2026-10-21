"""Solve the real EVEN SE+TE instance (S12a, S12g) and record what happened.

Usage (repo root, venv active)::

    python -m solver.benchmarks.real_solve                 # 600 s safety cap
    python -m solver.benchmarks.real_solve --time-limit 900

Reads ``data/instances/even-2025-26/edge_list.json`` (the S9 export) and runs:

1. backtracking (:func:`solver.backtracking.backtrack_solve`) with the time
   budget: outcome, wall-clock runtime, search nodes, the pre-solve result
   (the failed check, or ``passed``) and the size of the deepest partial;
2. Welsh-Powell (:func:`solver.colouring.welsh_powell`): colours (distinct start
   slots) used, the sessions it could not colour, and the room-free half of the
   validator (:func:`solver.validate.validate_slot_placements`) on the sessions
   it did colour;
3. solved only: local search (:func:`solver.improve.improve`, :data:`MOVES`
   moves and seed 0, the time budget as its safety cap) from the backtracking
   timetable: score before and after, and the move counts.

Solved: both timetables must pass :func:`solver.validate.validate_solution`; the
improved one is written as ``solution.json`` (``solution.v2``). Infeasible, by
pre-solve or search: the v2 infeasible result goes to the same path. Timeout:
nothing is written (ROADMAP D33). The file depends only on the instance, except
``metadata.runtime_ms``, which is wall-clock time (both steps), unless the
local search hits its safety cap. Prints the record as JSON.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path
from typing import Any

from solver.backtracking import backtrack_solve
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.improve import SEED, improve
from solver.validate import validate_slot_placements, validate_solution

INSTANCE = Path(__file__).resolve().parents[2] / "data" / "instances" / "even-2025-26"
TIME_LIMIT_S = 600.0  # a safety cap only: both steps take about 2 min here
MOVES = 1_000_000  # the committed run's budget, chosen by score (docs/real-solve-even-2025-26.md)


def run(edge_list: dict[str, Any], time_limit_s: float = TIME_LIMIT_S
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(record, solution.v2 payload or None on a timeout) for one instance."""
    graph = build_conflict_graph(edge_list)
    started = time.perf_counter()
    result = backtrack_solve(graph, edge_list, time_limit_s=time_limit_s)
    runtime_ms = (time.perf_counter() - started) * 1000

    colours, uncoloured = welsh_powell(graph)
    coloured = set(colours)
    cut = {  # the instance cut down to what Welsh-Powell coloured; it colours blocks whole
        **edge_list,
        "sessions": [s for s in edge_list["sessions"] if s["id"] in coloured],
        "edges": [e for e in edge_list["edges"] if e["u"] in coloured and e["v"] in coloured],
        "lab_blocks": [b for b in edge_list["lab_blocks"] if set(b["session_ids"]) <= coloured],
    }
    time_violations = validate_slot_placements(
        cut, {sid: (slot.day, slot.period) for sid, slot in colours.items()}
    )

    cert = result.certificate
    record = {
        "machine": f"{platform.processor() or platform.machine()}, Python "
                   f"{platform.python_version()}, {platform.system()}",
        "sessions": len(graph.sessions),
        "lab_blocks": len(edge_list["lab_blocks"]),
        "conflict_pairs": graph.edge_count(),
        "rooms": len(edge_list["rooms"]),
        "pinned_occupancy": len(edge_list["pinned_occupancy"]),
        "time_limit_s": time_limit_s,
        "outcome": result.outcome,
        "runtime_ms": round(runtime_ms, 1),
        "search_nodes": result.nodes_explored,
        "presolve": "passed" if cert is None else f"{cert.check} on {cert.resource}",
        "deepest_partial": len(result.partial_assignment),
        "welsh_powell": {
            "colours": len(set(colours.values())),
            "unplaced": uncoloured,
            "time_violations": [v.to_dict() for v in time_violations],
        },
    }
    if result.outcome == "timeout":
        return record, None
    solution = result.to_solution_v2_dict(runtime_ms=runtime_ms)
    if result.solved:
        violations = validate_solution(edge_list, solution)
        if violations:
            raise AssertionError(f"solved but invalid: {[v.to_dict() for v in violations]}")
        record["score_backtracking"] = solution["quality"]["score"]
        stats: dict[str, Any] = {}
        solution = improve(edge_list, solution, max_moves=MOVES, seed=SEED,
                           time_limit_s=time_limit_s, stats=stats)
        record["score"] = solution["quality"]["score"]
        improve_ms = solution["metadata"]["runtime_ms"] - runtime_ms
        record["improve"] = {"runtime_ms": round(improve_ms, 1), "seed": SEED, **stats}
    return record, solution


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--time-limit", type=float, default=TIME_LIMIT_S)
    args = parser.parse_args(argv)
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    record, solution = run(edge_list, args.time_limit)
    print(json.dumps(record, indent=2))
    if solution is None:
        print("timeout: nothing written (ROADMAP D33)")
        return
    (INSTANCE / "solution.json").write_text(json.dumps(solution, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {INSTANCE / 'solution.json'}")


if __name__ == "__main__":
    main()
