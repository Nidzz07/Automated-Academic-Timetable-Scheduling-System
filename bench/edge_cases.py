"""Edge cases through the solver's public functions (S15d).

Usage (repo root, venv active)::

    python -m bench.edge_cases                     # the cases, and the real substitute count

Each case runs through the public functions the backend uses -
:func:`solver.graph.build_conflict_graph`, :func:`solver.backtracking.backtrack_solve`,
:meth:`~solver.backtracking.BacktrackResult.to_solution_v2_dict`,
:func:`solver.mus.explain`, :func:`solver.repair.substitute_candidates`,
:func:`solver.repair.repair` and :func:`solver.validate.validate_solution` - and ends
in its documented outcome: solved (and valid), infeasible with a diagnosis, or a
timeout, which is a status and never a contract payload (D33).

The hand-built instances are test instances, not SPIT data: their only real part is the
slot grid, read from the committed ``edge_list.json`` (D6). ``infeasible`` and
``timeout`` use the synthetic presets (D19).

* ``empty``: no sessions.
* ``single``: one lecture.
* ``no free substitute``: the only other qualified teacher teaches elsewhere at that
  slot, so :func:`~solver.repair.substitute_candidates` is empty; a
  ``substitute_faculty`` repair then moves the session.
* ``infeasible (pre-solve)``: the synthetic ``infeasible`` preset, seed 1.
* ``infeasible (search)``: three lectures, one room, two periods all three teachers can
  teach in; pre-solve has no check for this, the search proves it.
* ``over-subscribed division``: one division with one more one-period lecture than the
  grid has teaching periods; with exactly as many, it solves.
* ``timeout``: the synthetic ``small`` preset, seed 1, with a one-node budget.

The real-data part: for every session of the committed ``solution.json``,
:func:`~solver.repair.substitute_candidates` with the faculty ``qualifications.json``
lists for its subject (D53). Writes ``bench/results/<date>-eval-edge-cases.csv`` and
``...-no-substitute.csv``. Every column is a pure function of the input.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from bench.evaluate import INSTANCE, markdown
from bench.run_bench import REPO, write_csv
from solver.backtracking import BacktrackResult, backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.mus import explain
from solver.repair import apply_change, repair, substitute_candidates
from solver.validate import validate_solution


def _read(name: str) -> dict[str, Any]:
    return json.loads((INSTANCE / name).read_text(encoding="utf-8"))


def slot_grid() -> dict[str, Any]:
    """The D6 grid of the real instance."""
    return _read("edge_list.json")["slot_grid"]


def teaching_cells(grid: dict[str, Any]) -> list[tuple[int, int]]:
    return [(d, p) for d in range(grid["days"]) for p in grid["teaching_periods"]]


def lecture(sid: str, faculty: str, cohort: str) -> dict[str, Any]:
    return {"id": sid, "subject_id": "subj-edge", "faculty_id": faculty, "cohort_id": cohort,
            "session_type": "theory", "duration_periods": 1, "cohort_size": 80,
            "requires_lab": False, "fixed_slot": None}


def instance(sessions: list[dict[str, Any]], *, rooms: int = 1,
             edges: list[tuple[str, str, str]] | None = None,
             open_cells: list[tuple[int, int]] | None = None) -> dict[str, Any]:
    """An edge_list.v1 payload on the real grid: *rooms* classrooms seating 80, and
    every teacher available only in *open_cells* (``None``: everywhere)."""
    grid = slot_grid()
    closed = [] if open_cells is None else [
        c for c in teaching_cells(grid) if c not in open_cells]
    return {
        "schema_version": "edge_list.v1", "slot_grid": grid, "sessions": sessions,
        "edges": [{"u": u, "v": v, "reason": r} for u, v, r in edges or []],
        "rooms": [{"id": f"room-{i}", "code": f"R{i}", "capacity": 80, "is_lab": False,
                   "parent_room_id": None} for i in range(1, rooms + 1)],
        "faculty_availability": [
            {"faculty_id": f, "unavailable_slots": [{"day": d, "period": p} for d, p in closed]}
            for f in sorted({s["faculty_id"] for s in sessions})],
        "lab_blocks": [], "pinned_occupancy": [],
    }


def one_division(lectures: int) -> dict[str, Any]:
    """*lectures* one-period lectures of one division, each by its own teacher, so only
    the division limits them."""
    ids = [f"s{i:02d}" for i in range(lectures)]
    return instance([lecture(sid, f"fac-{sid}", "div") for sid in ids], rooms=2,
                    edges=[(u, v, "COHORT") for i, u in enumerate(ids) for v in ids[i + 1:]])


def solve(payload: dict[str, Any], **limits: Any) -> BacktrackResult:
    return backtrack_solve(build_conflict_graph(payload), payload, **limits)


def _diagnosis(solution: dict[str, Any]) -> dict[str, Any]:
    d = solution["diagnosis"]
    relaxation = d.get("suggested_relaxation") or {}
    return {
        "method": d["method"],
        "conflicting_set": "; ".join(m["constraint_id"] for m in d["minimal_conflicting_set"]),
        "relaxation": (relaxation.get("action") or {}).get("action_type", ""),
        "verification": (relaxation.get("verification") or {}).get("status", ""),
    }


def _row(case: str, payload: dict[str, Any], result: BacktrackResult) -> dict[str, Any]:
    row = {"case": case, "sessions": len(payload["sessions"]), "outcome": result.outcome,
           "nodes": result.nodes_explored, "placed": "", "hard_violations": "",
           "method": "", "conflicting_set": "", "relaxation": "", "verification": "",
           "explained_method": "", "explained_set": "", "explained_relaxation": "",
           "explained_verification": "", "note": ""}
    if result.outcome == "timeout":
        try:
            result.to_solution_v2_dict()
        except ValueError as err:
            row["note"] = f"to_solution_v2_dict raises ValueError: {err}"
        return row
    solution = result.to_solution_v2_dict()
    if result.solved:
        row.update(placed=len(solution["assignment"]),
                   hard_violations=len(validate_solution(payload, solution)))
        return row
    row.update(_diagnosis(solution))
    explained = _diagnosis(explain(payload, solution))
    row.update({f"explained_{k if k != 'conflicting_set' else 'set'}": v
                for k, v in explained.items()})
    return row


def no_free_substitute() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(instance, its solution, the substitution): fac-b, the only other qualified
    teacher, teaches its own division at the same period."""
    payload = instance([lecture("a", "fac-a", "div-a"), lecture("b", "fac-b", "div-b")],
                       rooms=2)
    day, period = teaching_cells(payload["slot_grid"])[0]
    pinned = {**payload, "sessions": [{**s, "fixed_slot": {"day": day, "period": period}}
                                      for s in payload["sessions"]]}
    solution = solve(pinned).to_solution_v2_dict()  # both at the first teaching period
    return payload, solution, {"kind": "substitute_faculty", "session_id": "a",
                               "faculty_id": "fac-b"}


def cases() -> list[dict[str, Any]]:
    """One row per case, in the module docstring's order."""
    rows = [_row("empty", p := instance([]), solve(p)),
            _row("single", p := instance([lecture("s00", "fac-a", "div")]), solve(p))]

    payload, solution, change = no_free_substitute()
    candidates = substitute_candidates(payload, solution, "a", ["fac-a", "fac-b"])
    repaired = repair(payload, solution, change)
    rows.append({**_row("no free substitute", payload, solve(payload)),
                 "outcome": f"{len(candidates)} candidates; repair {repaired['status']}",
                 "nodes": "", "placed": len(repaired.get("assignment", [])),
                 "hard_violations": len(validate_solution(apply_change(payload, change),
                                                          repaired)),
                 "note": "repair displaced " + ", ".join(repaired.get("displaced", []))})

    rows.append(_row("infeasible (pre-solve)", p := generate(PRESETS["infeasible"], 1),
                     solve(p)))
    first = teaching_cells(slot_grid())[:2]
    rows.append(_row("infeasible (search)",
                     p := instance([lecture(f"s{i}", f"fac-{i}", f"div-{i}") for i in range(3)],
                                   open_cells=first), solve(p)))
    cells = len(teaching_cells(slot_grid()))
    rows.append(_row(f"division with {cells} lectures", p := one_division(cells), solve(p)))
    rows.append(_row(f"over-subscribed division ({cells + 1} lectures)",
                     p := one_division(cells + 1), solve(p)))
    timeout = _row("timeout (node_limit=1)", p := generate(PRESETS["small"], 1),
                   solve(p, node_limit=1))
    rows.append({**timeout, "note": f"{timeout['note']}; without the limit: {solve(p).outcome}"})
    return rows


def qualified_for(qualifications: dict[str, Any], session: dict[str, Any]) -> list[str]:
    """The faculty qualifications.json lists for the session's subject, with its type or
    none given (D53, as the backend's substitutes route reads it)."""
    listed = qualifications["subjects"].get(session["subject_id"], {}).get("faculty", [])
    return [f["faculty_id"] for f in listed
            if f["session_type"] in (None, session["session_type"])]


def no_substitute_rows(edge_list: dict[str, Any], solution: dict[str, Any],
                       qualifications: dict[str, Any],
                       session_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Per placed session (all, or *session_ids*): its qualified others and candidates."""
    placed = {a["session_id"] for a in solution["assignment"]}
    rows = []
    for s in edge_list["sessions"]:
        if s["id"] not in placed or (session_ids is not None and s["id"] not in session_ids):
            continue
        qualified = qualified_for(qualifications, s)
        found = substitute_candidates(edge_list, solution, s["id"], qualified)
        rows.append({
            "session_id": s["id"], "subject_id": s["subject_id"],
            "session_type": s["session_type"], "cohort_id": s["cohort_id"],
            "teacher": s["faculty_id"],
            "qualified_others": len(set(qualified) - {s["faculty_id"]}),
            "candidates": len(found),
            "best": f"{found[0]['faculty_id']} ({found[0]['score_change']:+.1f})" if found else "",
        })
    return rows


def main(argv: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, default=REPO / "bench" / "results")
    args = parser.parse_args(argv)
    tables = {"edge-cases": cases(),
              "no-substitute": no_substitute_rows(_read("edge_list.json"),
                                                  _read("solution.json"),
                                                  _read("qualifications.json"))}
    today = date.today().isoformat()
    for name, rows in tables.items():
        write_csv(args.out_dir / f"{today}-eval-{name}.csv", rows, list(rows[0]))
        print(f"\n## {name}\n\n{markdown(rows)}", flush=True)
    rows = tables["no-substitute"]
    print(f"\n{sum(r['candidates'] == 0 for r in rows)} of {len(rows)} sessions have no "
          "free qualified substitute")
    return tables


if __name__ == "__main__":
    main(sys.argv[1:])
