"""Lab utilisation: the printed figures reproduced, and the same measure for solution.json (S15d).

Usage (repo root, venv active)::

    python -m bench.lab_utilisation

The EVEN lab timetable prints, above each lab's table, a line such as
``Lab Utilization in %= 24/30= 80.00 %`` (CONTEXT.md 3.6). This script reads the
parsed timetable from :func:`ingestion.lab_tt.parse_lab_timetable` (read-only: the
printed figures are its ``LabTable.printed``, the cells its ``LabEntry`` records)
and, per table:

* counts the occupied (day, period) cells again from the parsed cells, coffee break
  excluded, over the printed denominator, and checks the count against ingestion's own
  ``LabTable.occupied``;
* checks the printed percentage against the printed fraction (the file truncates:
  20/30 is printed 66.66);
* says match or mismatch, and for every table lists what the files show that could
  bear on a difference: exam blocks in the grid, ROADMAP section 5 periods with no row
  in the table, and cells of the class and faculty timetables that name the table's
  room at a period the table leaves empty. These are reported, never used to adjust a
  number (CONTEXT.md 3.5).

For the generated ``solution.json`` the same measure is given per lab unit of the
edge list (a lab without sub-rooms, or each sub-room of a split lab): the teaching
(day, period) cells in which a session or a pin holds the unit, or holds its whole
room (``sub_room_id`` null locks every sub-room, :func:`solver.validate.validate_solution`).

Writes ``bench/results/<date>-eval-lab-utilisation.csv`` (printed vs reproduced),
``...-lab-utilisation-generated.csv`` (per unit) and ``...-lab-utilisation-labs.csv``
(per lab, both timetables). Every column is a pure function of the committed files.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

from bench.evaluate import INSTANCE, _held, markdown
from bench.run_bench import REPO, write_csv
from ingestion.class_tt import (
    COFFEE_PERIOD,
    ClassTimetable,
    faculty_index,
    parse_class_timetable,
    time_rows,
)
from ingestion.docx_reader import logical_cells, open_document, walk_body
from ingestion.faculty import FACULTY_FILE, FacultyPage, parse_faculty_pages
from ingestion.lab_tt import LAB_FILE, LabTimetable, label_key, parse_lab_timetable
from solver.slots import SlotGrid

#: ROADMAP section 5: P0-P9.
PERIODS = tuple(range(10))
KINDS = ("practical", "elective", "mdm", "out_of_scope", "exam", "unparsed")


def _span(periods: list[int]) -> str:
    return f"P{periods[0]}" if len(periods) == 1 else f"P{periods[0]}-P{periods[-1]}"


def grid_periods(path: Path = LAB_FILE) -> list[set[int]]:
    """Per lab table, in document order, the ROADMAP periods that have a row in it."""
    out = []
    for kind, element in walk_body(open_document(path)):
        if kind == "table":
            cells, _, _ = logical_cells(element)
            out.append(set(time_rows(cells)[0].values()))
    return out


def _truncated(value: float) -> float:
    return math.floor(value * 100 + 1e-9) / 100


def _elsewhere(label: str, occupied: set[tuple[str, int]], class_tt: ClassTimetable,
               pages: list[FacultyPage]) -> list[str]:
    """Class- and faculty-timetable cells naming *label* at a teaching period the table
    leaves empty. A faculty-timetable cell names its room in its last field."""
    key = label_key(label)
    found = []
    for e in class_tt.entries:
        if e.room_raw and label_key(e.room_raw) == key and any(
                (e.day, p) not in occupied for p in e.periods if p != COFFEE_PERIOD):
            found.append(f"class timetable {e.division} {e.day[:3]} {_span(e.periods)} "
                         f"{e.raw!r}")
    for page in pages:
        for s in page.sessions:
            if label_key(s.raw.split("/")[-1]) == key and any(
                    (s.day, p) not in occupied for p in s.periods if p != COFFEE_PERIOD):
                found.append(f"faculty timetable {page.name_raw} {s.day[:3]} "
                             f"{_span(s.periods)} {s.raw!r}")
    return found


def printed_rows(lab: LabTimetable, class_tt: ClassTimetable, pages: list[FacultyPage],
                 rows_per_table: list[set[int]]) -> list[dict[str, Any]]:
    """One row per lab table: printed figure, our count, match, and the evidence."""
    exam_tables = sum(any(e.kind == "exam" for e in lab.entries if e.table == t.index)
                      for t in lab.tables)
    rows = []
    for t in lab.tables:
        entries = [e for e in lab.entries if e.table == t.index]
        occupied = {(e.day, p) for e in entries for p in e.teaching_periods}
        exam = {(e.day, p) for e in entries if e.kind == "exam" for p in e.teaching_periods}
        missing = [p for p in PERIODS if p not in rows_per_table[t.index]]
        elsewhere = _elsewhere(t.room_label or "", occupied, class_tt, pages)
        num, den, pct = t.printed if t.printed else ("", "", "")
        ours = len(occupied)
        match = t.printed is not None and ours == num
        evidence = []
        if exam:
            evidence.append(
                f"{len(exam)} exam periods in the grid; without them it holds "
                f"{len(occupied - exam)} ({exam_tables} of {len(lab.tables)} tables have an "
                "exam block)")
        if missing:
            evidence.append("no row for " + ", ".join(f"P{p}" for p in missing))
        if elsewhere:
            evidence.append(f"{len(elsewhere)} cell(s) elsewhere name this room at a period "
                            "the table leaves empty: " + "; ".join(elsewhere))
        rows.append({
            "table": t.index, "printed_room": t.room_label,
            "room": t.sub_room or t.room or "not used for generation",
            "printed": t.utilisation_raw,
            "printed_occupied": num, "denominator": den, "printed_percent": pct,
            "printed_arithmetic": (
                "consistent" if t.printed and pct in (_truncated(100 * num / den),
                                                      round(100 * num / den, 2))
                else "inconsistent"),
            "ours_occupied": ours,
            "ours_percent": round(100 * ours / den, 2) if t.printed else "",
            "difference": ours - num if t.printed else "",
            "result": "match" if match else "mismatch",
            "ingestion_occupied": t.occupied,
            "ingestion_result": "match" if t.matches_printed else "mismatch",
            **{f"{k} cells": sum(e.kind == k for e in entries) for k in KINDS},
            "evidence": " | ".join(evidence),
        })
    return rows


def _cells(held: dict[tuple[int, int], set[str | None]], sub_room: str | None,
           whole_only: bool = False) -> int:
    """Cells of one top-level room (``evaluate._held``) that hold *sub_room*: held whole
    (None), or that sub-room. ``sub_room`` None: a room without sub-rooms, any hold."""
    if whole_only:
        return sum(None in c for c in held.values())
    return sum(bool(c) and (sub_room is None or None in c or sub_room in c)
               for c in held.values())


def generated_rows(edge_list: dict[str, Any], solution: dict[str, Any], denominator: int,
                   printed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per lab unit of the edge list: cells held in solution.json, pins included."""
    grid = SlotGrid.from_payload(edge_list["slot_grid"])
    teaching = len(list(grid.all_slots()))
    placements = {a["session_id"]: a for a in solution["assignment"]}
    held, pins = _held(edge_list, placements), _held(edge_list, {})
    by_code = {r["id"]: r["code"] for r in edge_list["rooms"]}
    printed_for = {str(r["room"]): r for r in printed}
    rows = []
    for top in sorted((r for r in edge_list["rooms"]
                       if r["is_lab"] and r["parent_room_id"] is None), key=lambda r: r["code"]):
        subs = sorted(r["id"] for r in edge_list["rooms"] if r["parent_room_id"] == top["id"])
        for unit in subs or [top["id"]]:
            unit_of = unit if subs else None
            used = _cells(held[top["id"]], unit_of)
            match = printed_for.get(by_code[unit])
            rows.append({
                "lab": top["code"], "unit": by_code[unit],
                "printed_table": match["printed_room"] if match else "",
                "held": used,
                "of which pinned": _cells(pins[top["id"]], unit_of),
                "of which whole room": _cells(held[top["id"]], unit_of, whole_only=True)
                if subs else 0,
                f"percent of {denominator}": round(100 * used / denominator, 2),
                "teaching_cells": teaching,
                f"percent of {teaching}": round(100 * used / teaching, 2),
            })
    return rows


def lab_rows(printed: list[dict[str, Any]], generated: list[dict[str, Any]],
             lab: LabTimetable, edge_list: dict[str, Any],
             solution: dict[str, Any]) -> list[dict[str, Any]]:
    """Per lab: printed tables and their figures summed, generated units summed, and how
    many generated sessions sit in a split lab whole (sub_room_id null) or in a sub-room."""
    labs = list(dict.fromkeys([g["lab"] for g in generated]
                              + [t.room or f"{t.room_label} (not used)" for t in lab.tables]))
    code_of = {r["id"]: r["code"] for r in edge_list["rooms"]}
    split = {code_of[r["parent_room_id"]] for r in edge_list["rooms"] if r["parent_room_id"]}
    placed = [(code_of[a["room_id"]], a["sub_room_id"]) for a in solution["assignment"]]
    rows = []
    for code in labs:
        tables = [r for r, t in zip(printed, lab.tables, strict=True)
                  if (t.room or f"{t.room_label} (not used)") == code]
        units = [g for g in generated if g["lab"] == code]
        rows.append({
            "lab": code,
            "printed_tables": ", ".join(r["printed_room"] for r in tables),
            "printed_occupied": sum(r["printed_occupied"] for r in tables),
            "ours_from_print": sum(r["ours_occupied"] for r in tables),
            "printed_denominators": sum(r["denominator"] for r in tables),
            "generated_units": ", ".join(g["unit"] for g in units),
            "generated_held": sum(g["held"] for g in units),
            "generated_whole_room": sum(g["of which whole room"] for g in units),
            "sessions_in_whole_lab": sum(c == code and s is None for c, s in placed)
            if code in split else "",
            "sessions_in_sub_rooms": sum(c == code and s is not None for c, s in placed)
            if code in split else "",
        })
    return rows


def main(argv: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, default=REPO / "bench" / "results")
    args = parser.parse_args(argv)

    faculty = faculty_index()
    class_tt = parse_class_timetable(faculty=faculty)
    lab = parse_lab_timetable(class_tt=class_tt, faculty=faculty)
    pages, _ = parse_faculty_pages(FACULTY_FILE, faculty)
    printed = printed_rows(lab, class_tt, pages, grid_periods())
    denominators = {r["denominator"] for r in printed}
    if len(denominators) != 1:
        raise SystemExit(f"the tables print different denominators: {denominators}")
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    generated = generated_rows(edge_list, solution, denominators.pop(), printed)
    tables = {"lab-utilisation": printed, "lab-utilisation-generated": generated,
              "lab-utilisation-labs": lab_rows(printed, generated, lab, edge_list, solution)}
    today = date.today().isoformat()
    for name, rows in tables.items():
        write_csv(args.out_dir / f"{today}-eval-{name}.csv", rows, list(rows[0]))
        print(f"\n## {name}\n\n{markdown(rows)}", flush=True)
    return tables


if __name__ == "__main__":
    main(sys.argv[1:])
