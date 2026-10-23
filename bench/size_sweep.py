"""Runtime and score vs instance size, synthetic data only (S15c).

Usage (repo root, venv active)::

    python -m bench.size_sweep                    # 10 sizes, seed 1, 3 runs (about 7 min)
    python -m bench.size_sweep --divisions 2 --runs 1 --moves 1000

Every instance is the synthetic ``large`` preset (:mod:`solver.benchmarks.synthetic`,
D19) with only ``divisions`` changed and ``faculty`` scaled with it (41 per 10
divisions, rounded, at least one per batch), seed 1: 2-9 divisions lie between the
``small`` (12 sessions) and ``large`` (242) presets, 10 divisions *is* ``large``, and 12
is above it. Each runs through :func:`bench.evaluate.algorithm_rows` (Welsh-Powell,
backtracking, backtracking + :func:`solver.improve.improve` with ``--moves`` moves, seed
0; median of ``--runs`` runs; stops if two runs differ apart from time). Writes
``bench/results/<date>-eval-size-sweep.csv`` and two charts,
``docs/figures/runtime-vs-sessions.svg`` and ``docs/figures/score-vs-sessions.svg``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from bench.charts import chart
from bench.evaluate import MACHINE, MOVES, RUNS, algorithm_rows, markdown
from bench.run_bench import REPO, write_csv
from solver.benchmarks.synthetic import PRESETS, InstanceConfig, generate

DIVISIONS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12)
SEED = 1
FIGURES = REPO / "docs" / "figures"


def config(divisions: int) -> InstanceConfig:
    """``large`` with *divisions* divisions and faculty in proportion."""
    large = PRESETS["large"]
    faculty = (large.faculty * divisions + large.divisions // 2) // large.divisions
    return replace(large, name=f"large-shape-{divisions}", divisions=divisions,
                   faculty=max(large.batches_per_division, faculty))


def _points(rows: list[dict[str, Any]], improved: bool, column: str
            ) -> list[tuple[float, float]]:
    return [(r["sessions"], r[column]) for r in rows if r[column] != ""
            and (r["algorithm"].startswith("backtracking + improve") if improved
                 else r["algorithm"] == "backtracking")]


def charts(rows: list[dict[str, Any]], fig_dir: Path) -> None:
    """Runtime and score vs sessions, backtracking with and without improve()."""
    for column, name, label, log_y in (("ms_median", "runtime", "ms, median (log scale)", True),
                                       ("score", "score", "score (rules v1)", False)):
        chart(fig_dir / f"{name}-vs-sessions.svg",
              f"{name.capitalize()} vs sessions, synthetic large-shape instances, seed {SEED}",
              "sessions", label,
              [("backtracking", _points(rows, False, column)),
               ("backtracking + improve", _points(rows, True, column))],
              log_y=log_y)


def main(argv: list[str] | None = None) -> list[dict[str, Any]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--divisions", action="append", type=int,
                        help="divisions (repeatable); default: 2-10 and 12")
    parser.add_argument("--runs", type=int, default=RUNS, help="timed runs per instance")
    parser.add_argument("--moves", type=int, default=MOVES, help="improve() move budget")
    parser.add_argument("--out-dir", type=Path, default=REPO / "bench" / "results")
    parser.add_argument("--fig-dir", type=Path, default=FIGURES)
    args = parser.parse_args(argv)

    rows = [row for d in args.divisions or DIVISIONS
            for row in algorithm_rows(f"large-shape d={d}", SEED, generate(config(d), SEED),
                                      args.moves, args.runs)]
    write_csv(args.out_dir / f"{date.today().isoformat()}-eval-size-sweep.csv", rows,
              list(rows[0]))
    charts(rows, args.fig_dir)
    print(f"machine: {MACHINE}\n\n{markdown(rows)}")
    return rows


if __name__ == "__main__":
    main(sys.argv[1:])
