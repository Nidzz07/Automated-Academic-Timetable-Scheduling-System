"""Evaluation harness (S15a): Welsh-Powell vs backtracking, for the final report.

Usage (repo root, venv active)::

    python -m bench.run_bench                       # synthetic presets x seeds 1-5
    python -m bench.run_bench --preset small --seed 1
    python -m bench.run_bench data/instances/even-2025-26/edge_list.json

With no file arguments every synthetic preset (:mod:`solver.benchmarks.synthetic`,
D19) is run for seeds 1-5 and the results go to ``bench/results/<date>.csv`` and
``docs/bench-<date>.md``. With ``edge_list_v1`` file arguments each file is
checked against ``contracts/edge_list_v1.schema.json`` and run once; the
outputs default to ``bench/results/<date>-instances.csv`` and
``docs/bench-<date>-instances.md``. ``--csv`` / ``--md`` override either.

Per instance: Welsh-Powell (:func:`solver.colouring.welsh_powell`, checked with
:func:`solver.validate.validate_slot_placements` when complete) and backtracking
(:func:`solver.backtracking.backtrack_solve` with ``time_limit_s``, checked with
:func:`solver.validate.validate_solution` when solved). Every column is a pure
function of the input except the ``*_ms`` timings, which are wall clock and
machine-dependent - and so, at the limit, is a ``timeout`` outcome.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.validate import validate_slot_placements, validate_solution

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "contracts" / "edge_list_v1.schema.json"
SEEDS = (1, 2, 3, 4, 5)
DEFAULT_TIMEOUT_S = 300.0
COLUMNS = (
    "instance", "seed", "sessions", "edges", "solved", "outcome",
    "bt_ms", "bt_nodes", "bt_validator",
    "wp_ms", "wp_colours", "wp_unplaced", "wp_validator",
)


def _verdict(violations: list[Any]) -> str:
    return "valid" if not violations else f"{len(violations)} violations"


def bench_one(instance: str, seed: int | str, edge_list: dict[str, Any],
              timeout_s: float) -> dict[str, Any]:
    """One CSV row: both algorithms on one edge list."""
    graph = build_conflict_graph(edge_list)

    start = time.perf_counter()
    colouring, unplaced = welsh_powell(graph)
    wp_ms = (time.perf_counter() - start) * 1000
    if unplaced:
        wp_validator = "n/a (incomplete)"
    else:
        starts = {sid: (slot.day, slot.period) for sid, slot in colouring.items()}
        wp_validator = _verdict(validate_slot_placements(edge_list, starts))

    start = time.perf_counter()
    try:
        result = backtrack_solve(graph, edge_list, time_limit_s=timeout_s)
    except RecursionError:  # reported, not hidden; the row still carries Welsh-Powell
        result = None
    bt_ms = (time.perf_counter() - start) * 1000
    if result is None:
        outcome, nodes, bt_validator = "error: RecursionError", "", "n/a"
    else:
        outcome, nodes = result.outcome, result.nodes_explored
        if result.certificate is not None:
            outcome += f" (presolve: {result.certificate.check})"
        bt_validator = (
            _verdict(validate_solution(edge_list, result.to_solution_dict(runtime_ms=bt_ms)))
            if result.solved else "n/a (not solved)"
        )

    return {
        "instance": instance,
        "seed": seed,
        "sessions": len(edge_list["sessions"]),
        "edges": len(edge_list["edges"]),
        "solved": result is not None and result.solved,
        "outcome": outcome,
        "bt_ms": round(bt_ms, 3),
        "bt_nodes": nodes,
        "bt_validator": bt_validator,
        "wp_ms": round(wp_ms, 3),
        "wp_colours": len(set(colouring.values())),  # distinct start slots
        "wp_unplaced": len(unplaced),
        "wp_validator": wp_validator,
    }


def load_edge_list(path: Path) -> dict[str, Any]:
    """Read an ``edge_list_v1`` file; raises ``ValidationError`` if it does not conform."""
    edge_list = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(edge_list)
    return edge_list


def write_csv(path: Path, rows: list[dict[str, Any]],
              columns: tuple[str, ...] | list[str] = COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]], label: str, command: str) -> None:
    lines = [
        f"# Solver benchmark - {date.today().isoformat()}",
        "",
        f"**{label}**",
        "",
        f"- **Reproduce:** `{command}` (repo root, venv active).",
        f"- **Machine:** {platform.platform()} | {platform.processor() or 'unknown cpu'} | "
        f"Python {sys.version.split()[0]}.",
        "- **Timings (`bt_ms`, `wp_ms`) are wall clock and machine-dependent.** Every other "
        "column is a pure function of the input, except that a `timeout` depends on the machine.",
        "- `bt_*`: backtracking; `bt_nodes` is `nodes_explored`; `bt_validator` is "
        "`validate_solution` on a solved result.",
        "- `wp_*`: Welsh-Powell; `wp_colours` is the number of distinct start slots; "
        "`wp_validator` is `validate_slot_placements` (no rooms) on a complete colouring.",
        "- `edges`: entries in the edge list's `edges` array.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
        *("| " + " | ".join(str(row[c]) for c in COLUMNS) + " |" for row in rows),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> list[dict[str, Any]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("edge_list", nargs="*", type=Path,
                        help="edge_list_v1 JSON file(s); default: the synthetic presets")
    parser.add_argument("--preset", action="append", choices=list(PRESETS),
                        help="synthetic preset (repeatable); default: all")
    parser.add_argument("--seed", action="append", type=int,
                        help="synthetic seed (repeatable); default: 1-5")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="backtracking time budget per instance, seconds")
    parser.add_argument("--csv", type=Path, help="CSV output path")
    parser.add_argument("--md", type=Path, help="markdown output path")
    args = parser.parse_args(argv)
    today = date.today().isoformat()

    if args.edge_list:
        rows = [bench_one(p.as_posix(), "", load_edge_list(p), args.timeout)
                for p in args.edge_list]
        tag = f"{today}-instances"
        label = "edge_list_v1 file input: " + ", ".join(f"`{p.as_posix()}`" for p in args.edge_list)
    else:
        rows = [bench_one(name, seed, generate(PRESETS[name], seed), args.timeout)
                for name in args.preset or PRESETS for seed in args.seed or SEEDS]
        tag = today
        label = "Synthetic data only (D19) - none of these instances is SPIT data."

    command = "python -m bench.run_bench " + " ".join(argv if argv is not None else sys.argv[1:])
    write_csv(args.csv or REPO / "bench" / "results" / f"{tag}.csv", rows)
    write_markdown(args.md or REPO / "docs" / f"bench-{tag}.md", rows, label, command.strip())
    return rows


if __name__ == "__main__":
    main()
