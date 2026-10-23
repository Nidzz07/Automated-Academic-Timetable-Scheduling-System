"""Tests for the S15c evaluation: charts, size sweep, repair vs regeneration."""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from bench import repair_vs_regen, size_sweep
from bench.charts import chart
from bench.repair_vs_regen import HALF_DAYS, _read, changes, compare, mean_ci, summary, t975
from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph

SVG = "{http://www.w3.org/2000/svg}"


def _markers(svg: str) -> int:
    root = ET.fromstring(svg)
    return len(root.findall(f"{SVG}circle")) + len(root.findall(f"{SVG}rect")) - 1  # background


def test_chart_linear_and_log(tmp_path: Path) -> None:
    series = [("a", [(1, 5.0), (2, 50.0)]), ("b & c", [(1, 2000.0)])]
    svg = chart(tmp_path / "x.svg", "T", "x", "y", series, log_y=True)
    assert (tmp_path / "x.svg").read_text(encoding="utf-8") == svg
    assert _markers(svg) == 3 + 2  # one per point, one per legend entry
    assert "b &amp; c" in svg and ">1<" in svg and ">10,000<" in svg  # decade ticks
    svg = chart(tmp_path / "y.svg", "T", "x", "y", [("a", [(0, -480.0), (10, 70.0)])],
                lines=False)
    assert "polyline" not in svg and ">-600<" in svg and ">200<" in svg


def test_sweep_sizes() -> None:
    assert generate(size_sweep.config(10), 1) == generate(PRESETS["large"], 1)
    sizes = [len(generate(size_sweep.config(d), 1)["sessions"]) for d in size_sweep.DIVISIONS]
    assert sizes == sorted(sizes) and sizes[0] > 12 and sizes[-2] == 242 < sizes[-1]
    assert [size_sweep.config(d).faculty for d in (2, 5, 12)] == [8, 21, 49]


def test_sweep_main(tmp_path: Path) -> None:
    rows = size_sweep.main(["--divisions", "2", "--runs", "1", "--moves", "100",
                            "--out-dir", str(tmp_path), "--fig-dir", str(tmp_path)])
    assert [r["algorithm"] for r in rows] == [
        "welsh-powell", "backtracking", "backtracking + improve(100, seed 0)"]
    assert all(r["hard_violations"] == 0 for r in rows)
    (path,) = tmp_path.glob("*-eval-size-sweep.csv")
    with path.open(newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 3
    for name in ("runtime", "score"):
        assert _markers((tmp_path / f"{name}-vs-sessions.svg").read_text(encoding="utf-8")) == 4


def test_t975_and_mean_ci() -> None:
    assert [round(t975(df), 3) for df in (1, 4, 29)] == [12.706, 2.776, 2.045]
    assert mean_ci([]) == {"n": 0, "mean": "", "ci95_low": "", "ci95_high": ""}
    assert mean_ci([3.0])["ci95_low"] == ""
    assert mean_ci([1.0, 2.0, 3.0]) == {"n": 3, "mean": 2.0, "ci95_low": -0.48, "ci95_high": 4.48}


def test_changes_hit_the_committed_timetable() -> None:
    edge_list, solution = _read("edge_list.json"), _read("solution.json")
    drawn = changes(edge_list, solution)
    assert drawn == changes(edge_list, solution) and len(drawn) == 30
    assert [c["kind"] for _, c in drawn] == ["faculty_unavailable", "room_unavailable"] * 15
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    tops = {r["id"] for r in edge_list["rooms"] if r["parent_room_id"] is None}
    teaching = edge_list["slot_grid"]["teaching_periods"]
    for _, change in drawn:
        cells = {(s["day"], s["period"]) for s in change["slots"]}
        hit = []
        for a in solution["assignment"]:
            s = sessions[a["session_id"]]
            i = teaching.index(a["period"])
            mine = {(a["day"], p) for p in teaching[i:i + s["duration_periods"]]}
            if change["kind"] == "faculty_unavailable":
                hit += [a] if s["faculty_id"] == change["faculty_id"] and mine & cells else []
            else:
                hit += [a] if a["room_id"] == change["room_id"] and mine & cells else []
        assert hit
        if change["kind"] == "faculty_unavailable":
            assert 1 <= len(cells) <= 3
        else:
            assert change["room_id"] in tops
            assert sorted(p for _, p in cells) in [list(v) for v in HALF_DAYS.values()]


def _small() -> tuple[dict[str, Any], dict[str, Any]]:
    edge_list = generate(PRESETS["small"], 1)
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    return edge_list, result.to_solution_v2_dict(runtime_ms=0.0)


def test_compare_and_summary() -> None:
    edge_list, solution = _small()
    session = solution["assignment"][0]
    fid = next(s["faculty_id"] for s in edge_list["sessions"]
               if s["id"] == session["session_id"])
    change = {"kind": "faculty_unavailable", "faculty_id": fid,
              "slots": [{"day": session["day"], "period": session["period"]}]}
    rows = compare(edge_list, solution, change, moves=100)
    assert [r["method"] for r in rows] == [
        "repair", "regeneration (backtracking + improve(100, seed 0))"]
    repaired, regenerated = rows
    assert repaired["solved"] and regenerated["solved"]
    assert repaired["moved"] >= 1  # the change hits the session
    rows = [{"change": 1, **r} for r in rows] + [
        {"change": 2, "method": m, "solved": False, "moved": "", "score": "",
         "runtime_ms": 5.0} for m in (repaired["method"], regenerated["method"])]
    stats = {(s["method"], s["metric"]): s for s in summary(rows)}
    moved = stats["repair", "moved"]
    assert (moved["changes"], moved["solved"], moved["unsolved_both_ways"]) == (2, 1, 1)
    assert (moved["n"], moved["mean"]) == (1, repaired["moved"])
    assert stats["repair", "runtime_ms"]["n"] == 2  # unsolved changes are counted


def test_compare_keeps_a_repair_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError

    monkeypatch.setattr(repair_vs_regen, "repair", timeout)
    edge_list, solution = _small()
    change = {"kind": "room_unavailable", "room_id": edge_list["rooms"][0]["id"],
              "slots": [{"day": 0, "period": 0}]}
    repaired, regenerated = compare(edge_list, solution, change, moves=100)
    assert (repaired["solved"], repaired["outcome"], repaired["moved"]) == (False, "timeout", "")
    assert regenerated["solved"]


@pytest.mark.slow
def test_full_runs(tmp_path: Path) -> None:
    rows = size_sweep.main(["--out-dir", str(tmp_path), "--fig-dir", str(tmp_path)])
    assert all(r["hard_violations"] in (0, "") for r in rows)
    rows, stats = repair_vs_regen.main(["--out-dir", str(tmp_path), "--fig-dir", str(tmp_path)])
    assert len(rows) == 60 and {s["changes"] for s in stats} == {30}
