"""Tests for S15d: lab utilisation reproduced, and the solver's edge cases."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from bench import edge_cases, lab_utilisation
from bench.edge_cases import (
    instance,
    lecture,
    no_free_substitute,
    no_substitute_rows,
    one_division,
    solve,
    teaching_cells,
)
from bench.evaluate import INSTANCE
from bench.lab_utilisation import generated_rows, printed_rows
from ingestion.class_tt import ClassTimetable
from ingestion.faculty import FacultyPage, FacultySession
from ingestion.lab_tt import LabEntry, LabTable, LabTimetable
from solver.benchmarks.synthetic import PRESETS, generate
from solver.mus import apply_action, explain
from solver.repair import apply_change, repair, substitute_candidates
from solver.validate import validate_solution

ALL_PERIODS = set(range(10))


def _read(name: str) -> dict[str, Any]:
    return json.loads((INSTANCE / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Lab utilisation
# --------------------------------------------------------------------------- #


def _cell(table: int, day: str, periods: list[int], kind: str = "practical",
          raw: str = "X / A / AB | SE COMP A") -> LabEntry:
    return LabEntry(table, 1, 1, "t", day, periods, raw, kind)


def test_counting_rules_on_a_hand_built_table() -> None:
    """Coffee excluded, a slot counted once, exams and missing rows reported, not removed."""
    lab = LabTimetable("test", tables=[
        LabTable(0, "603-2", "603", "603-2", "24/30", (4, 30, 13.33)),
        LabTable(1, "702-A", "702", "702-A", "x", (2, 30, 6.66)),
    ], entries=[
        _cell(0, "Monday", [1, 2, 3]),  # spans the coffee break: P1 and P3
        _cell(0, "Monday", [3]),  # the same slot again
        _cell(0, "Tuesday", [0, 1], "exam", "DAA | LAB EXAM ESE"),
        _cell(1, "Friday", [0, 1]),
    ])
    pages = [FacultyPage(9, "Someone", "Someone", sessions=[
        FacultySession(9, 1, 1, "Friday", [6, 7], "ML /D /702-A", "ML")])]
    rows = printed_rows(lab, ClassTimetable("test"), pages, [ALL_PERIODS, ALL_PERIODS - {9}])
    first, second = rows
    assert (first["ours_occupied"], first["result"], first["difference"]) == (4, "match", 0)
    assert first["exam cells"] == 1 and "without them it holds 2" in first["evidence"]
    assert first["printed_arithmetic"] == "consistent"  # 400/30 = 13.333, truncated
    assert (second["ours_occupied"], second["result"]) == (2, "match")
    assert "no row for P9" in second["evidence"]
    assert "Someone Fri P6-P7 'ML /D /702-A'" in second["evidence"]


def test_printed_figures_reproduced_from_the_real_parse(tmp_path: Path) -> None:
    tables = lab_utilisation.main(["--out-dir", str(tmp_path)])
    rows = tables["lab-utilisation"]
    assert len(rows) == 15 and {r["denominator"] for r in rows} == {30}
    # our count is ingestion's, and every printed fraction agrees with its percentage
    assert all(r["ours_occupied"] == r["ingestion_occupied"] for r in rows)
    assert all(r["result"] == r["ingestion_result"] for r in rows)
    assert all(r["printed_arithmetic"] == "consistent" for r in rows)
    # the mismatches are the ones ingestion's anomaly report lists, never adjusted
    report = {a["location"] for a in _read("anomalies.json")["anomalies"]
              if a["category"] == "utilisation_mismatch"}
    mismatched = {f"t{r['table']} {r['printed_room']}" for r in rows if r["result"] == "mismatch"}
    assert mismatched == report and all(
        r["difference"] != 0 for r in rows if r["result"] == "mismatch")
    edge_list, solution = _read("edge_list.json"), _read("solution.json")
    split = {r["parent_room_id"] for r in edge_list["rooms"] if r["parent_room_id"]}
    in_split = sum(a["room_id"] in split for a in solution["assignment"])
    labs = tables["lab-utilisation-labs"]
    assert sum(r["sessions_in_whole_lab"] + r["sessions_in_sub_rooms"]
               for r in labs if r["sessions_in_whole_lab"] != "") == in_split
    for name in tables:
        (path,) = tmp_path.glob(f"*-eval-{name}.csv")
        with path.open(newline="", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == len(tables[name])


def _lab_edge_list() -> dict[str, Any]:
    room = {"capacity": 20, "is_lab": True}
    return {
        "slot_grid": edge_cases.slot_grid(),
        "sessions": [{"id": i, "duration_periods": 2} for i in ("whole", "sub", "plain")],
        "rooms": [{"id": "room-l", "code": "L", "parent_room_id": None, **room},
                  {"id": "sub-l-1", "code": "L-1", "parent_room_id": "room-l", **room},
                  {"id": "sub-l-2", "code": "L-2", "parent_room_id": "room-l", **room},
                  {"id": "room-m", "code": "M", "parent_room_id": None, **room},
                  {"id": "room-c", "code": "C", "parent_room_id": None, "capacity": 80,
                   "is_lab": False}],
        "pinned_occupancy": [{"day": 1, "period": 0, "faculty_ids": [], "cohort_ids": [],
                              "room_ids": ["sub-l-2"]}],
    }


def test_generated_measure_counts_whole_room_holds_for_every_sub_room() -> None:
    solution = {"assignment": [
        {"session_id": "whole", "day": 0, "period": 0, "room_id": "room-l", "sub_room_id": None},
        {"session_id": "sub", "day": 0, "period": 3, "room_id": "room-l",
         "sub_room_id": "sub-l-1"},
        {"session_id": "plain", "day": 2, "period": 6, "room_id": "room-m", "sub_room_id": None},
    ]}
    rows = {r["unit"]: r for r in generated_rows(_lab_edge_list(), solution, 30, [])}
    assert set(rows) == {"L-1", "L-2", "M"}  # labs only, a split lab per sub-room
    assert (rows["L-1"]["held"], rows["L-1"]["of which whole room"]) == (4, 2)
    assert (rows["L-2"]["held"], rows["L-2"]["of which pinned"]) == (3, 1)
    assert (rows["M"]["held"], rows["M"]["percent of 30"]) == (2, 6.67)


# --------------------------------------------------------------------------- #
# Edge cases (documented outcomes)
# --------------------------------------------------------------------------- #


def _solved(payload: dict[str, Any]) -> dict[str, Any]:
    result = solve(payload)
    assert result.outcome == "solved"
    solution = result.to_solution_v2_dict()
    assert validate_solution(payload, solution) == []
    return solution


def test_empty_instance_is_solved() -> None:
    solution = _solved(instance([]))
    assert solution["status"] == "solved" and solution["assignment"] == []
    assert solution["metadata"]["sessions_total"] == 0


def test_single_session_is_solved() -> None:
    solution = _solved(instance([lecture("s00", "fac-a", "div")]))
    assert [a["session_id"] for a in solution["assignment"]] == ["s00"]


def test_no_free_substitute_then_repair_moves_the_session() -> None:
    payload, solution, change = no_free_substitute()
    starts = {(a["day"], a["period"]) for a in solution["assignment"]}
    assert len(starts) == 1  # both lectures at one slot
    assert substitute_candidates(payload, solution, "a", ["fac-a", "fac-b"]) == []
    repaired = repair(payload, solution, change)
    assert repaired["status"] == "solved" and repaired["displaced"] == ["a"]
    assert validate_solution(apply_change(payload, change), repaired) == []


def _explained_and_relaxable(payload: dict[str, Any], solution: dict[str, Any]) -> None:
    explained = explain(payload, solution)["diagnosis"]
    assert explained["method"] == "mus" and explained["minimal_conflicting_set"]
    relaxation = explained["suggested_relaxation"]
    assert relaxation["verification"]["status"] == "restored"
    relaxed = apply_action(payload, relaxation["action"])
    assert solve(relaxed).outcome == "solved"  # checked again, outside explain()


def test_infeasible_by_presolve_has_a_diagnosis() -> None:
    payload = generate(PRESETS["infeasible"], 1)
    result = solve(payload)
    assert result.outcome == "infeasible" and result.certificate is not None
    solution = result.to_solution_v2_dict()
    assert solution["diagnosis"]["method"] == "presolve"
    _explained_and_relaxable(payload, solution)


def test_infeasible_by_search_has_a_diagnosis() -> None:
    two = teaching_cells(edge_cases.slot_grid())[:2]
    payload = instance([lecture(f"s{i}", f"fac-{i}", f"div-{i}") for i in range(3)],
                       open_cells=two)
    result = solve(payload)
    assert result.outcome == "infeasible" and result.certificate is None
    solution = result.to_solution_v2_dict()
    assert solution["diagnosis"]["method"] == "search_exhaustion"
    assert len(solution["diagnosis"]["unplaced_session_ids"]) == 1
    _explained_and_relaxable(payload, solution)


def test_over_subscribed_division() -> None:
    cells = len(teaching_cells(edge_cases.slot_grid()))
    _solved(one_division(cells))  # exactly as many lectures as teaching periods
    payload = one_division(cells + 1)
    result = solve(payload)
    assert result.outcome == "infeasible"
    assert (result.certificate.check, result.certificate.resource) == ("cohort_load", "div")
    solution = result.to_solution_v2_dict()
    (entry,) = solution["diagnosis"]["minimal_conflicting_set"]
    assert entry["kind"] == "COHORT_CLASH" and len(entry["slots"]) == cells
    explained = explain(payload, solution)["diagnosis"]
    assert explained["method"] == "mus"
    assert [m["constraint_id"] for m in explained["minimal_conflicting_set"]] == [
        "cohort_clash.div"]


def test_timeout_is_a_status_not_infeasible() -> None:
    payload = generate(PRESETS["small"], 1)
    result = solve(payload, node_limit=1)
    assert result.outcome == "timeout" and not result.solved
    with pytest.raises(ValueError, match="D33"):
        result.to_solution_v2_dict()
    assert solve(payload).outcome == "solved"


def test_cases_rows() -> None:
    rows = {r["case"]: r for r in edge_cases.cases()}
    assert [r["outcome"] for r in rows.values()] == [
        "solved", "solved", "0 candidates; repair solved", "infeasible", "infeasible",
        "solved", "infeasible", "timeout"]
    assert all(r["hard_violations"] == 0 for r in rows.values() if r["placed"] != "")
    assert all(r["explained_method"] == "mus" for r in rows.values()
               if r["outcome"] == "infeasible")


def test_no_substitute_rows_on_real_sessions() -> None:
    edge_list, solution = _read("edge_list.json"), _read("solution.json")
    ids = [s["id"] for s in edge_list["sessions"]][:20]
    rows = no_substitute_rows(edge_list, solution, _read("qualifications.json"), ids)
    assert [r["session_id"] for r in rows] == ids
    assert all(r["candidates"] <= r["qualified_others"] for r in rows)
    assert all(r["teacher"] not in r["best"] for r in rows)
    # nobody free, though others are listed for the subject (D53)
    assert any(r["candidates"] == 0 < r["qualified_others"] for r in rows)
