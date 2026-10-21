"""Tests for the S15b evaluation script (:mod:`bench.evaluate`)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from bench.evaluate import INSTANCE, algorithm_rows, main, real_vs_printed, room_use
from solver.benchmarks.synthetic import PRESETS, generate


def _load(name: str) -> dict[str, Any]:
    return json.loads((INSTANCE / name).read_text(encoding="utf-8"))


def test_algorithm_rows_small() -> None:
    rows = algorithm_rows("small", 1, generate(PRESETS["small"], 1), moves=500, runs=2)
    wp, bt, im = rows
    assert [r["algorithm"] for r in rows] == [
        "welsh-powell", "backtracking", "backtracking + improve(500, seed 0)"]
    assert (wp["outcome"], wp["placed"], wp["check"], wp["hard_violations"]) == (
        "complete", 12, "time-only", 0)
    assert (bt["outcome"], bt["check"], bt["hard_violations"]) == ("solved", "full", 0)
    assert (im["hard_violations"], im["moves"], im["nodes"]) == (0, 500, bt["nodes"])
    assert im["score"] >= bt["score"]
    for r in rows:
        assert r["score"] == 100 - sum(r[k] for k in ("S-GAP", "S-B2B", "S-LOAD16",
                                                      "FAC_LOAD_IMBALANCE"))
        assert r["runs"] == 2 and r["ms_median"] >= 0


def test_algorithm_rows_infeasible() -> None:
    _, bt, im = algorithm_rows("infeasible", 1, generate(PRESETS["infeasible"], 1),
                               moves=500, runs=1)
    assert bt["outcome"].startswith("infeasible (presolve")
    assert (bt["placed"], bt["score"], im["score"], im["ms_median"]) == (0, "", "", "")


def _mini() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """One day, periods 0, 1, 3 (0-1 adjacent); lab L split L-1/L-2, classroom C."""
    edge_list = {
        "slot_grid": {"days": 1, "periods_per_day": 4, "teaching_periods": [0, 1, 3],
                      "adjacency": [[0, 1]]},
        "rooms": [
            {"id": "L", "code": "L", "capacity": 40, "is_lab": True, "parent_room_id": None},
            {"id": "L-1", "code": "L-1", "capacity": 20, "is_lab": True, "parent_room_id": "L"},
            {"id": "L-2", "code": "L-2", "capacity": 20, "is_lab": True, "parent_room_id": "L"},
            {"id": "C", "code": "C", "capacity": 80, "is_lab": False, "parent_room_id": None},
        ],
        "sessions": [{"id": "lab", "duration_periods": 2}, {"id": "lec", "duration_periods": 1}],
        "pinned_occupancy": [
            {"day": 0, "period": 3, "faculty_ids": [], "cohort_ids": [], "room_ids": ["C"]},
            {"day": 0, "period": 1, "faculty_ids": [], "cohort_ids": [], "room_ids": ["L-2"]},
        ],
    }
    generated = {"lab": {"day": 0, "period": 0, "room_id": "L", "sub_room_id": "L-1"},
                 "lec": {"day": 0, "period": 0, "room_id": "C", "sub_room_id": None}}
    return edge_list, generated


def test_room_use_counts_sessions_pins_and_sub_rooms() -> None:
    edge_list, generated = _mini()
    printed = {"lab": {"day": 0, "period": 0, "room_id": "L", "sub_room_id": None},
               "lec": {"day": 0, "period": 0, "room_id": None, "sub_room_id": None}}
    rooms, free = room_use(edge_list, generated, printed)
    by_room = {r["room"]: r for r in rooms}
    assert [r["room"] for r in rooms] == ["L", "C"]  # labs first
    assert (by_room["L"]["generated used"], by_room["L"]["pinned"]) == (2, 1)
    assert (by_room["C"]["generated used"], by_room["C"]["printed used"]) == (2, 1)
    assert by_room["C"]["teaching_periods"] == 3
    cells = {(r["day"], r["period"]): r for r in free}
    # 0: L-2 is free, so L is listed; C holds the lecture
    assert (cells[0, 0]["generated free labs"], cells[0, 0]["generated free classrooms"]) == (1, 0)
    # a whole-room use locks the lab; a lecture with no printed room holds nothing
    assert (cells[0, 0]["printed free labs"], cells[0, 0]["printed free classrooms"]) == (0, 1)
    # 1: the lab's second period on L-1 and the pin on L-2 fill both sub-rooms
    assert (cells[0, 1]["generated free labs"], cells[0, 1]["generated free classrooms"]) == (0, 1)
    # 3: C is pinned
    assert (cells[0, 3]["generated free labs"], cells[0, 3]["generated free classrooms"]) == (1, 0)


def test_real_vs_printed() -> None:
    printed = _load("real_baseline.assignment.json")["assignment"]
    generated, baseline = real_vs_printed(_load("edge_list.json"), _load("solution.json"),
                                          printed)
    report = _load("real_baseline.report.json")
    assert baseline["score"] == report["quality"]["score"]
    assert (baseline["time_only_violations"], baseline["by_kind"]) == (
        36, "FACULTY_CLASH 26; PINNED_BLOCK 10")
    assert baseline["full_violations"] == "n/a"
    assert baseline["sessions_without_room"] == sum(
        p["room_id"] is None for p in printed.values())
    assert generated["score"] == _load("solution.json")["quality"]["score"]
    assert (generated["time_only_violations"], generated["full_violations"]) == (0, 0)


def test_main_writes_dated_csvs(tmp_path: Path) -> None:
    tables = main(["--preset", "small", "--seed", "1", "--runs", "1", "--moves", "100",
                   "--out-dir", str(tmp_path)])
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 5 and all("-eval-" in f for f in files)
    for name, rows in tables.items():
        (path,) = tmp_path.glob(f"*-eval-{name}.csv")
        with path.open(newline="", encoding="utf-8") as f:
            assert len(list(csv.DictReader(f))) == len(rows)
    assert [r["instance"] for r in tables["algorithms"]] == ["small"] * 3 + [
        "real even-2025-26"] * 3
    assert len(tables["repair"]) == 6
    assert len(tables["free-rooms"]) == 45
