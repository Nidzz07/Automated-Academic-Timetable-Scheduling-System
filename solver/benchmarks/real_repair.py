"""Repair the committed real EVEN timetable after real changes (S14a).

Usage (repo root, venv active)::

    python -m solver.benchmarks.real_repair

Reads ``data/instances/even-2025-26/edge_list.json`` and ``solution.json`` and
runs :func:`solver.repair.repair` (seed 0, default budgets) once per scenario in
:data:`SCENARIOS`. Every id comes from the instance; names are in
``display.json``. Per scenario it prints the outcome, the moved sessions
(``displaced``), sessions only re-roomed, the rings searched, the score before
(``solution.json``) and after (against the changed payload), and the wall-clock
runtime, as a Markdown table and then as JSON; an infeasible scenario also
records its explanation (:func:`solver.mus.explain`: the set, whether it is
proven minimal, the relaxations tried). Results feed
``docs/repair-even-2025-26.md``. Everything but the runtime is the same on
every run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from solver.repair import apply_change, repair
from solver.validate import validate_solution

INSTANCE = Path(__file__).resolve().parents[2] / "data" / "instances" / "even-2025-26"
TEACHING = [0, 1, 3, 4, 5, 6, 7, 8, 9]  # ROADMAP section 5; checked against the payload in main
CE207 = "obs-t0-r1-c3-l0"  # first CE207 lecture by id: SE-Comp A, Anant Nimkar, Thu 12.15, 605

SCENARIOS: list[tuple[str, dict[str, Any]]] = [
    ("Swapnali Kurhade unavailable all Tuesday",
     {"kind": "faculty_unavailable", "faculty_id": "fac-swapnali-kurhade",
      "slots": [{"day": 1, "period": p} for p in TEACHING]}),
    ("Lab 603 unavailable all Monday",
     {"kind": "room_unavailable", "room_id": "room-603",
      "slots": [{"day": 0, "period": p} for p in TEACHING]}),
    ("CE207 lecture dragged to a free slot (Wed 09.00, 601)",
     {"kind": "move_session", "session_id": CE207, "day": 2, "period": 0,
      "room_id": "room-601", "sub_room_id": None}),
    ("CE207 lecture dragged onto SE-Comp A's frozen MDM-I lab (Mon 09.00, 605)",
     {"kind": "move_session", "session_id": CE207, "day": 0, "period": 0,
      "room_id": "room-605", "sub_room_id": None}),
    ("Swapnali Kurhade unavailable Tuesday afternoon (P5-P9)",
     {"kind": "faculty_unavailable", "faculty_id": "fac-swapnali-kurhade",
      "slots": [{"day": 1, "period": p} for p in (5, 6, 7, 8, 9)]}),
    ("CE207 lecture dragged onto an occupied slot (Mon 17.15, 605)",
     {"kind": "move_session", "session_id": CE207, "day": 0, "period": 9,
      "room_id": "room-605", "sub_room_id": None}),
]


def run(edge_list: dict[str, Any], solution: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per scenario."""
    records = []
    for name, change in SCENARIOS:
        stats: dict[str, Any] = {}
        started = time.perf_counter()
        result = repair(edge_list, solution, change, stats=stats)
        runtime_ms = (time.perf_counter() - started) * 1000
        record: dict[str, Any] = {
            "scenario": name, "change": change, "status": result["status"],
            "hit": stats["hit"], "rings": stats["rings"], "runtime_ms": round(runtime_ms),
            "score_before": solution["quality"]["score"],
        }
        if result["status"] == "solved":
            if validate_solution(apply_change(edge_list, change), result):
                raise AssertionError(f"{name}: repaired timetable is not valid")
            record.update(moved=result["displaced"], room_changed=stats["room_changed"],
                          score_after=result["quality"]["score"])
        else:
            diagnosis, mus = result["diagnosis"], stats["mus"]
            record.update(
                method=diagnosis["method"],
                constraints=[f"{c['constraint_id']} ({c['kind']})"
                             for c in diagnosis["minimal_conflicting_set"]],
                proven_minimal=mus["proven_minimal"], unknown=mus["unknown"],
                checks=mus["checks"], groups=mus["groups"], start=mus["start"],
                relaxation=diagnosis["suggested_relaxation"],
                tried=[[a["constraint_id"], a["action"]["action_type"],
                        a["verification"]["status"]] for a in mus["relaxations"]],
            )
        records.append(record)
    return records


def main() -> None:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    if edge_list["slot_grid"]["teaching_periods"] != TEACHING:
        raise SystemExit("the instance's teaching periods are not ROADMAP section 5's")
    records = run(edge_list, solution)
    print("| Scenario | Result | Moved | Re-roomed only | Rings (freed, outcome) "
          "| Score before → after | Runtime |")
    print("|---|---|---|---|---|---|---|")
    for r in records:
        rings = "; ".join(f"{k}: {n} {o}" for k, n, o in r["rings"])
        if r["status"] == "solved":
            print(f"| {r['scenario']} | repaired | {len(r['moved'])} | {len(r['room_changed'])} "
                  f"| {rings} | {r['score_before']} → {r['score_after']} "
                  f"| {r['runtime_ms'] / 1000:.2f} s |")
        else:
            print(f"| {r['scenario']} | infeasible ({r['method']}) | n/a | n/a | {rings} "
                  f"| {r['score_before']} → n/a | {r['runtime_ms'] / 1000:.2f} s |")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
