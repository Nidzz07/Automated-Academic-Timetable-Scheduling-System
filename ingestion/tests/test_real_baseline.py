"""Tests for the real EVEN timetable as printed (S12b). No database is touched."""

from __future__ import annotations

import copy
import json

import pytest

from ingestion.emit_v2 import Instance, build, dumps
from ingestion.real_baseline import (
    ASSIGNMENT_JSON,
    DISPLAY_JSON,
    EDGE_LIST_JSON,
    REPORT_MD,
    assignment_file,
    map_sessions,
    report,
)
from solver.validate import validate_slot_placements


@pytest.fixture(scope="module")
def inst() -> Instance:
    return build()


@pytest.fixture(scope="module")
def edge_list() -> dict:
    return json.loads(EDGE_LIST_JSON.read_text(encoding="utf-8"))


def test_committed_files_are_current(inst: Instance, edge_list: dict) -> None:
    b = map_sessions(edge_list, inst)
    display = json.loads(DISPLAY_JSON.read_text(encoding="utf-8"))
    assert ASSIGNMENT_JSON.read_text(encoding="utf-8") == dumps(assignment_file(b))
    assert REPORT_MD.read_text(encoding="utf-8") == report(b, edge_list, display)


def test_every_session_mapped_or_listed(inst: Instance, edge_list: dict) -> None:
    b = map_sessions(edge_list, inst)
    ids = {s["id"] for s in edge_list["sessions"]}
    assert set(b.assignment) | set(b.unmapped) == ids
    assert not set(b.assignment) & set(b.unmapped)


def test_rooms_are_in_the_room_set_or_null(inst: Instance, edge_list: dict) -> None:
    b = map_sessions(edge_list, inst)
    parent = {r["id"]: r["parent_room_id"] for r in edge_list["rooms"]}
    for sid, a in b.assignment.items():
        if a["room_id"] is None:
            assert a["sub_room_id"] is None and sid in b.no_room
        else:
            assert parent[a["room_id"]] is None and sid not in b.no_room
            assert a["sub_room_id"] is None or parent[a["sub_room_id"]] == a["room_id"]
    # D10 rooms printed in the timetable (002, 508) are not in the room set.
    assert any(decision == "D10" for _, decision in b.no_room.values())


def test_violations_are_the_validators_unfiltered(inst: Instance, edge_list: dict) -> None:
    b = map_sessions(edge_list, inst)
    assert not b.unmapped
    starts = {sid: (a["day"], a["period"]) for sid, a in b.assignment.items()}
    assert b.violations == validate_slot_placements(edge_list, starts)


def test_unmappable_sessions_are_listed_and_left_out(inst: Instance, edge_list: dict) -> None:
    changed = copy.deepcopy(edge_list)
    lecture = next(s for s in changed["sessions"] if s["duration_periods"] == 1)
    lecture["duration_periods"] = 2
    changed["sessions"].append({**lecture, "id": "obs-not-printed", "duration_periods": 1})
    b = map_sessions(changed, inst)
    assert b.unmapped == {
        lecture["id"]: "printed for 1 periods; the edge list needs 2",
        "obs-not-printed": "not in the parsed timetables",
    }
    assert all(sid not in b.unmapped for v in b.violations for sid in v.session_ids)
