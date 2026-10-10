"""Baseline: run the current solver on every synthetic preset, as it is.

Usage (repo root, venv active)::

    python -m solver.benchmarks.baseline                 # all presets, seed 1, 300 s limit
    python -m solver.benchmarks.baseline --preset small --preset medium --timeout 60

For each preset this generates the instance (:mod:`solver.benchmarks.synthetic`),
then runs, in a child process so a runaway search can be stopped:

1. Welsh-Powell (:func:`solver.colouring.welsh_powell`) - complete or not, time,
   and :func:`solver.validate.validate_slot_placements` on a complete colouring
   (colouring assigns no rooms, so the room-free half of the validator);
2. backtracking (:func:`solver.backtracking.backtrack_solve`) - solved or not,
   time, search nodes (``nodes_explored``), and
   :func:`solver.validate.validate_solution` on a solved result.

Nothing is tuned: the solver runs with its defaults. A run that exceeds the
time limit is reported as a timeout, with no node count (the child is killed).
Times are wall-clock and machine-dependent; everything else is a pure function
of (preset, seed).

Not part of the solver's public API.
"""

from __future__ import annotations

import argparse
import multiprocessing
import platform
import queue
import sys
import time
from typing import Any

from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.validate import validate_slot_placements, validate_solution

DEFAULT_SEED = 1
DEFAULT_TIMEOUT_S = 300.0


def instance_facts(preset: str, seed: int) -> dict[str, Any]:
    """Machine-independent size of one generated instance."""
    edge_list = generate(PRESETS[preset], seed)
    graph = build_conflict_graph(edge_list)
    return {
        "sessions": len(edge_list["sessions"]),
        "lab_blocks": len(edge_list["lab_blocks"]),
        "rooms": len(edge_list["rooms"]),
        "faculty": len(edge_list["faculty_availability"]),
        "conflict_pairs": graph.edge_count(),
        "pinned": len(edge_list["pinned_occupancy"]),
    }


def _worker(preset: str, seed: int, out: Any) -> None:
    edge_list = generate(PRESETS[preset], seed)
    graph = build_conflict_graph(edge_list)

    start = time.perf_counter()
    assignment, unplaced = welsh_powell(graph)
    greedy_ms = (time.perf_counter() - start) * 1000
    if unplaced:
        greedy_check = "n/a (incomplete)"
    else:
        starts = {sid: (slot.day, slot.period) for sid, slot in assignment.items()}
        violations = validate_slot_placements(edge_list, starts)
        greedy_check = "valid" if not violations else f"{len(violations)} violations"
    out.put(("greedy", {"complete": not unplaced, "unplaced": len(unplaced),
                        "ms": greedy_ms, "validator": greedy_check}))

    start = time.perf_counter()
    try:
        result = backtrack_solve(graph, edge_list)
    except RecursionError:
        out.put(("backtracking", {"outcome": "RecursionError",
                                  "ms": (time.perf_counter() - start) * 1000}))
        return
    search_ms = (time.perf_counter() - start) * 1000
    solution = result.to_solution_dict(runtime_ms=search_ms)
    if result.solved:
        violations = validate_solution(edge_list, solution)
        check = "valid" if not violations else f"{len(violations)} violations"
    else:
        check = "n/a (not solved)"
    out.put(("backtracking", {"outcome": "solved" if result.solved else "infeasible",
                              "ms": search_ms, "nodes": result.nodes_explored,
                              "validator": check}))


def run(preset: str, seed: int, timeout_s: float) -> dict[str, Any]:
    """Run one preset in a child process; never waits longer than *timeout_s*."""
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    child = ctx.Process(target=_worker, args=(preset, seed, out), daemon=True)
    started = time.perf_counter()
    child.start()
    results: dict[str, Any] = {}
    while len(results) < 2:
        remaining = timeout_s - (time.perf_counter() - started)
        if remaining <= 0:
            break
        try:
            key, value = out.get(timeout=remaining)
        except queue.Empty:
            break
        results[key] = value
    if child.is_alive():
        child.terminate()
    child.join()
    results.setdefault("greedy", {"complete": None, "ms": None, "validator": "timeout"})
    results.setdefault("backtracking", {"outcome": f"timeout (> {timeout_s:g} s)",
                                        "ms": None, "nodes": None, "validator": "n/a"})
    return results


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "-"
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.1f} ms"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", action="append", choices=sorted(PRESETS),
                        help="preset to run (repeatable); default: all")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="wall-clock limit per preset, seconds")
    args = parser.parse_args(argv)
    presets = args.preset or list(PRESETS)

    print(f"# Solver baseline - seed {args.seed}, limit {args.timeout:g} s per preset")
    print(f"# machine: {platform.platform()} | {platform.processor() or 'unknown cpu'} | "
          f"Python {sys.version.split()[0]}")
    print()
    print("| preset | sessions | lab blocks | rooms | faculty | conflict pairs | "
          "greedy | greedy time | greedy validator | backtracking | search time | "
          "nodes | validator |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for preset in presets:
        facts = instance_facts(preset, args.seed)
        r = run(preset, args.seed, args.timeout)
        g, b = r["greedy"], r["backtracking"]
        if g["complete"] is None:
            greedy = "timeout"
        elif g["complete"]:
            greedy = "complete"
        else:
            greedy = f"{g['unplaced']} unplaced"
        nodes = b.get("nodes")
        print(f"| {preset} | {facts['sessions']} | {facts['lab_blocks']} | {facts['rooms']} | "
              f"{facts['faculty']} | {facts['conflict_pairs']} | {greedy} | {_fmt_ms(g['ms'])} | "
              f"{g['validator']} | {b['outcome']} | {_fmt_ms(b['ms'])} | "
              f"{'-' if nodes is None else nodes} | {b['validator']} |", flush=True)


if __name__ == "__main__":
    main()
