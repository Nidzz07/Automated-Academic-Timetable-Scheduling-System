"""Evaluation numbers for the report (S15b).

Usage (repo root, venv active)::

    python -m bench.evaluate                      # presets x seeds 1-5, real instance, 3 runs
    python -m bench.evaluate --preset small --seed 1 --runs 1 --moves 1000

Writes five CSVs to ``bench/results/<date>-eval-*.csv`` (``--out-dir`` overrides)
and prints them as Markdown tables for ``docs/evaluation-even-2025-26.md``:

1. ``algorithms``: Welsh-Powell (:func:`solver.colouring.welsh_powell`),
   backtracking (:func:`solver.backtracking.backtrack_solve`) and backtracking +
   :func:`solver.improve.improve` (``--moves``, seed 0) on every synthetic preset
   (:mod:`solver.benchmarks.synthetic`, D19) and seed, and on the real instance.
   Outcome, sessions placed, hard violations, score and the four rule penalties,
   search nodes, local-search moves, and the median wall-clock time of ``--runs``
   runs. Welsh-Powell assigns no rooms, so it is held to the time-only half of the
   validator (:func:`solver.validate.validate_slot_placements`), on the sessions
   it coloured; the other two to :func:`solver.validate.validate_solution`.
2. ``real-vs-printed``: the committed ``solution.json`` against the printed
   timetable (``real_baseline.assignment.json``), scored with
   :func:`solver.scoring.score` and validated.
3. ``rooms``: per top-level room, the teaching periods of the week in which it or
   one of its sub-rooms is held, by a session or by a pin, in each timetable.
4. ``free-rooms``: per teaching slot, free classrooms and free labs in each
   timetable, by the free-room view's rule (``frontend/src/adapters/rooms.ts``).
5. ``repair``: :func:`solver.benchmarks.real_repair.run`'s scenarios.

Every column is a pure function of the input except the ``*ms`` timings, which
are wall clock and machine-dependent; each CSV row of 1 and 5 names the machine.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from bench.run_bench import DEFAULT_TIMEOUT_S, REPO, SEEDS, write_csv
from solver.backtracking import backtrack_solve
from solver.benchmarks import real_repair
from solver.benchmarks.synthetic import PRESETS, generate
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.improve import SEED, improve
from solver.scoring import score
from solver.slots import SlotGrid, SlotId
from solver.validate import validate_slot_placements, validate_solution

INSTANCE = REPO / "data" / "instances" / "even-2025-26"
MOVES = 200_000
RUNS = 3
RULES = ("S-GAP", "S-B2B", "S-LOAD16", "FAC_LOAD_IMBALANCE")
MACHINE = (f"{platform.processor() or platform.machine()}, Python "
           f"{platform.python_version()}, {platform.system()}")


def _penalties(quality: dict[str, Any] | None) -> dict[str, Any]:
    by_rule = {b["rule_id"]: b for b in quality["breakdown"]} if quality else {}
    return {"score": quality["score"] if quality else "",
            **{r: by_rule[r]["penalty"] if quality else "" for r in RULES}}


def _by_kind(violations: list[Any]) -> str:
    return "; ".join(f"{k} {n}" for k, n in sorted(Counter(v.kind for v in violations).items()))


def _once(edge_list: dict[str, Any], moves: int) -> tuple[list[dict[str, Any]], list[float]]:
    """One run of the three algorithms: untimed facts per algorithm, and their timings."""
    graph = build_conflict_graph(edge_list)

    start = time.perf_counter()
    colours, unplaced = welsh_powell(graph)
    wp_ms = (time.perf_counter() - start) * 1000
    coloured = set(colours)
    cut = {  # Welsh-Powell colours lab blocks whole, so the cut keeps whole blocks
        **edge_list,
        "sessions": [s for s in edge_list["sessions"] if s["id"] in coloured],
        "edges": [e for e in edge_list["edges"] if e["u"] in coloured and e["v"] in coloured],
        "lab_blocks": [b for b in edge_list["lab_blocks"] if set(b["session_ids"]) <= coloured],
    }
    wp_violations = validate_slot_placements(
        cut, {sid: (s.day, s.period) for sid, s in colours.items()})
    wp = {"algorithm": "welsh-powell",
          "outcome": "complete" if not unplaced else f"{len(unplaced)} unplaced",
          "placed": len(colours), "check": "time-only",
          "hard_violations": len(wp_violations), "by_kind": _by_kind(wp_violations),
          **_penalties(score(edge_list, colours) if not unplaced else None),
          "nodes": "", "moves": ""}

    start = time.perf_counter()
    result = backtrack_solve(graph, edge_list, time_limit_s=DEFAULT_TIMEOUT_S)
    bt_ms = (time.perf_counter() - start) * 1000
    outcome = result.outcome
    if result.certificate is not None:
        outcome += f" (presolve: {result.certificate.check})"
    solution = result.to_solution_v2_dict(runtime_ms=bt_ms) if result.solved else None
    bt_violations = validate_solution(edge_list, solution) if solution else []
    bt = {"algorithm": "backtracking", "outcome": outcome,
          "placed": len(result.assignment) if result.solved else len(result.partial_assignment),
          "check": "full" if solution else "n/a",
          "hard_violations": len(bt_violations) if solution else "",
          "by_kind": _by_kind(bt_violations),
          **_penalties(solution["quality"] if solution else None),
          "nodes": result.nodes_explored, "moves": ""}

    improve_ms, stats = 0.0, {}
    improved = None
    if solution:
        start = time.perf_counter()
        improved = improve(edge_list, solution, max_moves=moves, seed=SEED, stats=stats)
        improve_ms = (time.perf_counter() - start) * 1000
    im_violations = validate_solution(edge_list, improved) if improved else []
    im = {**bt, "algorithm": f"backtracking + improve({moves}, seed {SEED})",
          "hard_violations": len(im_violations) if improved else "",
          "by_kind": _by_kind(im_violations),
          **_penalties(improved["quality"] if improved else None),
          "moves": stats.get("proposed", "")}
    return [wp, bt, im], [wp_ms, bt_ms, bt_ms + improve_ms if improved else ""]


def algorithm_rows(instance: str, seed: int | str, edge_list: dict[str, Any],
                   moves: int = MOVES, runs: int = RUNS) -> list[dict[str, Any]]:
    """Three CSV rows (one per algorithm), timings the median of *runs* runs."""
    facts, timings = _once(edge_list, moves)
    all_timings = [timings]
    for _ in range(runs - 1):
        again, timings = _once(edge_list, moves)
        if again != facts:  # everything but the clock is a pure function of the input
            raise AssertionError(f"{instance} seed {seed}: two runs disagree")
        all_timings.append(timings)
    rows = []
    for i, row in enumerate(facts):
        ms = [t[i] for t in all_timings if t[i] != ""]
        rows.append({"instance": instance, "seed": seed,
                     "sessions": len(edge_list["sessions"]), "edges": len(edge_list["edges"]),
                     **row, "ms_median": round(statistics.median(ms), 1) if ms else "",
                     "runs": runs, "machine": MACHINE})
    return rows


def _starts(placements: dict[str, dict[str, Any]]) -> dict[str, SlotId]:
    return {sid: SlotId(p["day"], p["period"]) for sid, p in placements.items()}


def real_vs_printed(edge_list: dict[str, Any], solution: dict[str, Any],
                    printed: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The committed generated timetable and the printed one: score, rules, violations."""
    generated = {a["session_id"]: a for a in solution["assignment"]}
    rows = []
    for name, placements, full in (("generated (solution.json)", generated, True),
                                   ("printed (real_baseline)", printed, False)):
        starts = _starts(placements)
        time_only = validate_slot_placements(
            edge_list, {sid: (s.day, s.period) for sid, s in starts.items()})
        quality = score(edge_list, starts)
        by_rule = {b["rule_id"]: b for b in quality["breakdown"]}
        rows.append({
            "timetable": name, "score": quality["score"],
            **{f"{r} {k}": by_rule[r][k] for r in RULES for k in ("raw", "penalty")},
            "time_only_violations": len(time_only), "by_kind": _by_kind(time_only),
            # the printed rooms are partly outside the edge list (null), so no room check
            "full_violations": len(validate_solution(edge_list, solution)) if full else "n/a",
            "sessions_without_room": sum(p["room_id"] is None for p in placements.values()),
        })
    return rows


def _held(edge_list: dict[str, Any], placements: dict[str, dict[str, Any]]
          ) -> dict[str, dict[tuple[int, int], set[str | None]]]:
    """Top-level room -> (day, period) -> what holds it: a sub-room id, or None (whole room)."""
    grid = SlotGrid.from_payload(edge_list["slot_grid"])
    parent = {r["id"]: r["parent_room_id"] for r in edge_list["rooms"]}
    duration = {s["id"]: s["duration_periods"] for s in edge_list["sessions"]}
    held: dict[str, dict[tuple[int, int], set[str | None]]] = {
        r["id"]: {} for r in edge_list["rooms"] if r["parent_room_id"] is None}

    def hold(room_id: str, day: int, period: int) -> None:
        top = parent[room_id] or room_id
        held[top].setdefault((day, period), set()).add(room_id if parent[room_id] else None)

    teaching = list(grid.teaching_periods)
    for sid, p in placements.items():
        if p["room_id"] is None:
            continue
        i = teaching.index(p["period"])
        for period in teaching[i:i + duration[sid]]:  # valid placements run on contiguously
            hold(p["sub_room_id"] or p["room_id"], p["day"], period)
    for pin in edge_list["pinned_occupancy"]:
        for room_id in pin["room_ids"]:
            hold(room_id, pin["day"], pin["period"])
    return held


def _free(cell: set[str | None], sub_rooms: list[str]) -> bool:
    """rooms.ts ``freeRoomsAt``: a whole-room use locks it; a split room is free while a
    sub-room is."""
    if None in cell:
        return False
    return any(s not in cell for s in sub_rooms) if sub_rooms else not cell


def room_use(edge_list: dict[str, Any], generated: dict[str, dict[str, Any]],
             printed: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]],
                                                          list[dict[str, Any]]]:
    """(per-room used periods, per-slot free rooms) for the two timetables."""
    grid = SlotGrid.from_payload(edge_list["slot_grid"])
    slots = [(s.day, s.period) for s in grid.all_slots()]
    tops = [r for r in edge_list["rooms"] if r["parent_room_id"] is None]
    subs = {r["id"]: sorted(s["id"] for s in edge_list["rooms"] if s["parent_room_id"] == r["id"])
            for r in tops}
    pins_only = _held(edge_list, {})
    held = {"generated": _held(edge_list, generated), "printed": _held(edge_list, printed)}

    rooms = []
    for r in sorted(tops, key=lambda r: (not r["is_lab"], r["code"])):
        rooms.append({
            "room": r["code"], "kind": "lab" if r["is_lab"] else "classroom",
            "sub_rooms": len(subs[r["id"]]), "teaching_periods": len(slots),
            "pinned": len(pins_only[r["id"]]),
            **{f"{t} used": len(h[r["id"]]) for t, h in held.items()},
            **{f"{t} %": round(100 * len(h[r["id"]]) / len(slots), 1) for t, h in held.items()},
        })
    free = []
    for day, period in slots:
        row: dict[str, Any] = {"day": day, "period": period}
        for t, h in held.items():
            for kind, is_lab in (("classrooms", False), ("labs", True)):
                row[f"{t} free {kind}"] = sum(
                    _free(h[r["id"]].get((day, period), set()), subs[r["id"]])
                    for r in tops if r["is_lab"] == is_lab)
        free.append(row)
    return rooms, free


def repair_rows(edge_list: dict[str, Any], solution: dict[str, Any]) -> list[dict[str, Any]]:
    """real_repair's scenarios, one CSV row each."""
    rows = []
    for r in real_repair.run(edge_list, solution):
        solved = r["status"] == "solved"
        rows.append({
            "scenario": r["scenario"],
            "result": "repaired" if solved else f"infeasible ({r['method']})",
            "moved": len(r["moved"]) if solved else "",
            "room_only": len(r["room_changed"]) if solved else "",
            "score_before": r["score_before"],
            "score_after": r["score_after"] if solved else "",
            "score_change": r["score_after"] - r["score_before"] if solved else "",
            "rings": "; ".join(f"{k}: {n} {o}" for k, n, o in r["rings"]),
            "runtime_ms": r["runtime_ms"], "machine": MACHINE,
        })
    return rows


def markdown(rows: list[dict[str, Any]]) -> str:
    cols = list(rows[0])
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
                      *("| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows)])


def _read(name: str) -> dict[str, Any]:
    return json.loads((INSTANCE / name).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preset", action="append", choices=list(PRESETS),
                        help="synthetic preset (repeatable); default: all")
    parser.add_argument("--seed", action="append", type=int,
                        help="synthetic seed (repeatable); default: 1-5")
    parser.add_argument("--runs", type=int, default=RUNS, help="timed runs per instance")
    parser.add_argument("--moves", type=int, default=MOVES, help="improve() move budget")
    parser.add_argument("--out-dir", type=Path, default=REPO / "bench" / "results")
    args = parser.parse_args(argv)

    edge_list, solution = _read("edge_list.json"), _read("solution.json")
    printed = _read("real_baseline.assignment.json")["assignment"]
    generated = {a["session_id"]: a for a in solution["assignment"]}

    algorithms = [row for name in args.preset or PRESETS for seed in args.seed or SEEDS
                  for row in algorithm_rows(name, seed, generate(PRESETS[name], seed),
                                            args.moves, args.runs)]
    algorithms += algorithm_rows("real even-2025-26", "", edge_list, args.moves, args.runs)
    rooms, free = room_use(edge_list, generated, printed)
    tables = {
        "algorithms": algorithms,
        "real-vs-printed": real_vs_printed(edge_list, solution, printed),
        "rooms": rooms,
        "free-rooms": free,
        "repair": repair_rows(edge_list, solution),
    }
    today = date.today().isoformat()
    print(f"machine: {MACHINE}")
    for name, rows in tables.items():
        write_csv(args.out_dir / f"{today}-eval-{name}.csv", rows, list(rows[0]))
        print(f"\n## {name}\n\n{markdown(rows)}", flush=True)
    return tables


if __name__ == "__main__":
    main(sys.argv[1:])
