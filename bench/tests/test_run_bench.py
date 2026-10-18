"""Tests for the evaluation harness (:mod:`bench.run_bench`)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from bench.run_bench import COLUMNS, REPO, main

D6_EXAMPLE = REPO / "contracts" / "examples" / "edge_list_v1.d6_grid.example.json"
TIMINGS = {"bt_ms", "wp_ms"}


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _run(tmp_path: Path, *args: str) -> tuple[list[str], list[dict[str, str]], str]:
    out_csv, out_md = tmp_path / "out.csv", tmp_path / "out.md"
    main([*args, "--csv", str(out_csv), "--md", str(out_md)])
    header, rows = _read(out_csv)
    return header, rows, out_md.read_text(encoding="utf-8")


def test_synthetic_csv_shape(tmp_path: Path) -> None:
    header, rows, md = _run(tmp_path, "--preset", "small", "--preset", "infeasible",
                            "--seed", "1", "--seed", "2")
    assert header == list(COLUMNS)
    assert [(r["instance"], r["seed"]) for r in rows] == [
        ("small", "1"), ("small", "2"), ("infeasible", "1"), ("infeasible", "2"),
    ]
    small, infeasible = rows[0], rows[2]
    assert (small["solved"], small["outcome"], small["bt_validator"]) == ("True", "solved", "valid")
    assert infeasible["solved"] == "False"
    assert infeasible["outcome"].startswith("infeasible")
    assert "Synthetic data only (D19)" in md
    assert "machine-dependent" in md
    assert md.count("\n| small |") == 2


def test_deterministic_apart_from_timings(tmp_path: Path) -> None:
    def untimed(sub: str) -> list[dict[str, str]]:
        (tmp_path / sub).mkdir()
        _, rows, _ = _run(tmp_path / sub, "--preset", "small", "--seed", "3")
        return [{k: v for k, v in r.items() if k not in TIMINGS} for r in rows]

    assert untimed("a") == untimed("b")


def test_file_path_mode(tmp_path: Path) -> None:
    header, rows, md = _run(tmp_path, str(D6_EXAMPLE))
    edge_list = json.loads(D6_EXAMPLE.read_text(encoding="utf-8"))
    assert header == list(COLUMNS)
    assert len(rows) == 1
    row = rows[0]
    assert row["instance"] == D6_EXAMPLE.as_posix()
    assert row["seed"] == ""
    assert int(row["sessions"]) == len(edge_list["sessions"])
    assert int(row["edges"]) == len(edge_list["edges"])
    assert (row["solved"], row["outcome"], row["bt_validator"]) == ("True", "solved", "valid")
    assert (row["wp_unplaced"], row["wp_validator"]) == ("0", "valid")
    assert "synthetic" not in md.lower()
    assert "edge_list_v1.d6_grid.example.json" in md


def test_file_path_mode_rejects_non_contract_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"sessions": []}), encoding="utf-8")
    with pytest.raises(ValidationError):
        main([str(bad), "--csv", str(tmp_path / "o.csv"), "--md", str(tmp_path / "o.md")])
