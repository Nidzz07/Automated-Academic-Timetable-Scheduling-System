"""Repair vs regeneration on the real EVEN 2025-26 instance (S15c).

Usage (repo root, venv active)::

    python -m bench.repair_vs_regen               # 30 changes, seed 0 (about 30 min)
    python -m bench.repair_vs_regen --changes 2 --moves 1000

:func:`changes` draws ``--changes`` seeded random changes to the committed
``solution.json``, alternating two kinds; each one hits at least one session:

* changes 1, 3, 5, ...: a faculty member who teaches (uniform) is unavailable at 1-3
  (uniform) of the periods they teach in ``solution.json``;
* changes 2, 4, 6, ...: a top-level room is unavailable for a half-day, drawn uniformly from
  the (room, day, half-day) triples in which ``solution.json`` holds it or one of its
  sub-rooms. Morning is P0, P1, P3, P4 (09:00-13:15) and afternoon P5-P9
  (13:15-18:15), ROADMAP section 5.

Each change is handled two ways from ``solution.json``:

* **repair**: :func:`solver.repair.repair` (seed 0, default budgets) with two
  settings for the benchmark: ``time_limit_s=300``, the same budget as
  regeneration, since its last ring (every session free) otherwise has no limit and
  ran for over 2 minutes on one change here without an answer; and ``mus_nodes=0``,
  so an unsolvable change keeps its pre-solve or search diagnosis and skips the
  minimal-conflicting-set search, which is diagnosis, not repair, and which ran for
  over 20 minutes on one change here without finishing;
* **regeneration**: :func:`solver.backtracking.backtrack_solve` on the changed edge
  list (:func:`solver.repair.apply_change`, 300 s budget) then
  :func:`solver.improve.improve` (``--moves``, seed 0).

Per change and method: solved or not, outcome (``timeout`` is not a proof of
infeasibility, D33), sessions moved (start slot differs from ``solution.json``),
sessions only re-roomed, score against the changed edge list, and the wall-clock
runtime of one run. Every solved result must pass
:func:`solver.validate.validate_solution` against the changed edge list. Unsolved
changes are kept as rows, never dropped. The summary gives the mean and 95%
Student-t confidence interval (Statistical Methods) of moved sessions and score over
the changes both methods solved, and of runtime over all changes. Writes
``bench/results/<date>-eval-repair-vs-regen.csv``, ``...-summary.csv`` and
``docs/figures/repair-vs-regen-moved.svg``.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from bench.charts import chart
from bench.evaluate import MACHINE, MOVES, _read, markdown
from bench.run_bench import DEFAULT_TIMEOUT_S, REPO, write_csv
from solver.backtracking import backtrack_solve
from solver.graph import build_conflict_graph
from solver.improve import SEED, improve
from solver.repair import apply_change, repair
from solver.validate import validate_solution

CHANGES = 30
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri")
HALF_DAYS = {"morning": (0, 1, 3, 4), "afternoon": (5, 6, 7, 8, 9)}  # ROADMAP section 5
FIGURES = REPO / "docs" / "figures"

Placements = dict[str, tuple[tuple[int, int], str]]


def _placements(assignment: list[dict[str, Any]]) -> Placements:
    return {a["session_id"]: ((a["day"], a["period"]), a["sub_room_id"] or a["room_id"])
            for a in assignment}


def changes(edge_list: dict[str, Any], solution: dict[str, Any], n: int = CHANGES,
            seed: int = SEED) -> list[tuple[str, dict[str, Any]]]:
    """*n* (description, change) pairs, seeded; see the module docstring."""
    rng = random.Random(seed)
    teaching = edge_list["slot_grid"]["teaching_periods"]
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    top = {r["id"]: r["parent_room_id"] or r["id"] for r in edge_list["rooms"]}
    taught: dict[str, set[tuple[int, int]]] = {}
    held: set[tuple[str, int, str]] = set()
    for a in solution["assignment"]:
        s = sessions[a["session_id"]]
        i = teaching.index(a["period"])
        for period in teaching[i:i + s["duration_periods"]]:
            taught.setdefault(s["faculty_id"], set()).add((a["day"], period))
            held |= {(top[a["room_id"]], a["day"], half)
                     for half, periods in HALF_DAYS.items() if period in periods}
    faculty, halves = sorted(taught), sorted(held)

    out = []
    for k in range(n):
        if k % 2 == 0:
            fid = rng.choice(faculty)
            cells = sorted(rng.sample(sorted(taught[fid]), min(rng.randint(1, 3),
                                                               len(taught[fid]))))
            out.append((f"{fid} unavailable "
                        + ", ".join(f"{DAY_NAMES[d]} P{p}" for d, p in cells),
                        {"kind": "faculty_unavailable", "faculty_id": fid,
                         "slots": [{"day": d, "period": p} for d, p in cells]}))
        else:
            room, day, half = rng.choice(halves)
            out.append((f"{room} unavailable {DAY_NAMES[day]} {half}",
                        {"kind": "room_unavailable", "room_id": room,
                         "slots": [{"day": day, "period": p} for p in HALF_DAYS[half]]}))
    return out


def compare(edge_list: dict[str, Any], solution: dict[str, Any], change: dict[str, Any],
            moves: int = MOVES) -> list[dict[str, Any]]:
    """Two rows for one change: repair, then regeneration."""
    committed = _placements(solution["assignment"])
    changed = apply_change(edge_list, change)

    start = time.perf_counter()
    try:
        repaired: dict[str, Any] | None = repair(edge_list, solution, change, mus_nodes=0,
                                                 time_limit_s=DEFAULT_TIMEOUT_S)
        repair_outcome = repaired["status"]
        if repaired["status"] != "solved":
            repair_outcome += f" ({repaired['diagnosis']['method']})"
            repaired = None
    except TimeoutError:
        repaired, repair_outcome = None, "timeout"
    repair_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    result = backtrack_solve(build_conflict_graph(changed), changed,
                             time_limit_s=DEFAULT_TIMEOUT_S)
    regenerated = (improve(changed, result.to_solution_v2_dict(runtime_ms=0.0),
                           max_moves=moves, seed=SEED) if result.solved else None)
    regen_ms = (time.perf_counter() - start) * 1000
    regen_outcome = result.outcome
    if result.certificate is not None:
        regen_outcome += f" (presolve: {result.certificate.check})"

    rows = []
    for method, timetable, outcome, ms in (
            ("repair", repaired, repair_outcome, repair_ms),
            (f"regeneration (backtracking + improve({moves}, seed {SEED}))", regenerated,
             regen_outcome, regen_ms)):
        row: dict[str, Any] = {"method": method, "solved": timetable is not None,
                               "outcome": outcome, "moved": "", "room_only": "", "score": ""}
        if timetable is not None:
            violations = validate_solution(changed, timetable)
            if violations:
                raise AssertionError(f"{method}: {[v.to_dict() for v in violations]}")
            now = _placements(timetable["assignment"])
            row.update(
                moved=sum(now[s][0] != committed[s][0] for s in committed),
                room_only=sum(now[s][0] == committed[s][0] and now[s][1] != committed[s][1]
                              for s in committed),
                score=timetable["quality"]["score"])
        rows.append({**row, "runtime_ms": round(ms, 1)})
    return rows


def t975(df: int) -> float:
    """The two-sided 95% Student-t critical value: bisection on the CDF, the density
    integrated from 0 by Simpson's rule (Statistical Methods)."""
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)

    def density(x: float) -> float:
        return c * (1 + x * x / df) ** (-(df + 1) / 2)

    def area(t: float, n: int = 2000) -> float:
        h = t / n
        return h / 3 * (density(0) + density(t)
                        + sum((4 if i % 2 else 2) * density(i * h) for i in range(1, n)))

    lo, hi = 0.0, 100.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if area(mid) < 0.475 else (lo, mid)
    return (lo + hi) / 2


def mean_ci(values: list[float]) -> dict[str, Any]:
    """n, mean and the 95% t interval of the mean ('' where undefined)."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": "", "ci95_low": "", "ci95_high": ""}
    mean = statistics.fmean(values)
    if n == 1:
        return {"n": 1, "mean": round(mean, 2), "ci95_low": "", "ci95_high": ""}
    half = t975(n - 1) * statistics.stdev(values) / math.sqrt(n)
    return {"n": n, "mean": round(mean, 2), "ci95_low": round(mean - half, 2),
            "ci95_high": round(mean + half, 2)}


def summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per method: counts, then mean and 95% CI of moved and score (changes both methods
    solved) and runtime (all changes)."""
    solved: dict[int, list[bool]] = {}
    for r in rows:
        solved.setdefault(r["change"], []).append(r["solved"])
    both = {c for c, f in solved.items() if all(f)}
    neither = sum(not any(f) for f in solved.values())
    out = []
    for method in dict.fromkeys(r["method"] for r in rows):
        mine = [r for r in rows if r["method"] == method]
        counts = {"method": method, "changes": len(mine),
                  "solved": sum(r["solved"] for r in mine), "unsolved_both_ways": neither}
        for metric, over in (("moved", both), ("score", both), ("runtime_ms", None)):
            values = [r[metric] for r in mine if over is None or r["change"] in over]
            out.append({**counts, "metric": metric,
                        "over": "all changes" if over is None else "solved both ways",
                        **mean_ci(values), "machine": MACHINE})
    return out


def main(argv: list[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--changes", type=int, default=CHANGES, help="number of changes")
    parser.add_argument("--seed", type=int, default=SEED, help="seed of the change draw")
    parser.add_argument("--moves", type=int, default=MOVES, help="improve() move budget")
    parser.add_argument("--out-dir", type=Path, default=REPO / "bench" / "results")
    parser.add_argument("--fig-dir", type=Path, default=FIGURES)
    args = parser.parse_args(argv)

    edge_list, solution = _read("edge_list.json"), _read("solution.json")
    rows = []
    for k, (description, change) in enumerate(changes(edge_list, solution, args.changes,
                                                      args.seed), start=1):
        for row in compare(edge_list, solution, change, args.moves):
            rows.append({"change": k, "kind": change["kind"], "description": description,
                         **row, "machine": MACHINE})
        print(f"{k}/{args.changes} {description}", flush=True)
    stats = summary(rows)
    today = date.today().isoformat()
    write_csv(args.out_dir / f"{today}-eval-repair-vs-regen.csv", rows, list(rows[0]))
    write_csv(args.out_dir / f"{today}-eval-repair-vs-regen-summary.csv", stats, list(stats[0]))
    chart(args.fig_dir / "repair-vs-regen-moved.svg",
          "Sessions moved per change, real EVEN 2025-26 instance",
          "change", "sessions moved vs solution.json",
          [("repair" if i == 0 else "regeneration",
            [(r["change"], r["moved"]) for r in rows
             if r["method"].startswith(prefix) and r["solved"]])
           for i, prefix in enumerate(("repair", "regeneration"))],
          lines=False)
    print(f"machine: {MACHINE}\n\n{markdown(rows)}\n\n{markdown(stats)}")
    return rows, stats


if __name__ == "__main__":
    main(sys.argv[1:])
