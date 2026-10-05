"""Tests for :mod:`solver.validate` — the independent hard-constraint checker.

Each test hand-builds an edge list and a solution whose verdict is known by
inspection: one clean timetable, then one timetable per violation kind, then
the malformed inputs that must raise rather than report.  The committed
contract examples are validated too.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from solver.slots import SlotId
from solver.validate import KINDS, Violation, validate_slot_placements, validate_solution

REPO = Path(__file__).resolve().parents[2]


# ======================================================================
# Builders
# ======================================================================


def _session(
    sid: str,
    faculty: str = "f1",
    cohort: str = "c1",
    *,
    duration: int = 1,
    size: int = 20,
    lab: bool = False,
    fixed: tuple[int, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": sid,
        "subject_id": "subj",
        "faculty_id": faculty,
        "cohort_id": cohort,
        "session_type": "lab" if lab else "theory",
        "duration_periods": duration,
        "cohort_size": size,
        "requires_lab": lab,
        "fixed_slot": None if fixed is None else {"day": fixed[0], "period": fixed[1]},
    }


def _room(
    rid: str, capacity: int = 30, *, lab: bool = False, parent: str | None = None
) -> dict[str, Any]:
    return {"id": rid, "code": rid, "capacity": capacity, "is_lab": lab,
            "parent_room_id": parent}


def _edge_list(
    sessions: list[dict[str, Any]],
    *,
    edges: Sequence[tuple[str, str, str]] = (),
    rooms: list[dict[str, Any]] | None = None,
    unavailable: dict[str, list[tuple[int, int]]] | None = None,
    blocks: Sequence[tuple[str, list[str], int]] = (),
    pins: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    unavailable = unavailable or {}
    faculty = sorted({s["faculty_id"] for s in sessions} | set(unavailable))
    return {
        "schema_version": "edge_list.v1",
        "slot_grid": {
            "days": 5, "periods_per_day": 10,
            "teaching_periods": [0, 1, 3, 4, 6, 7, 8, 9],
            "adjacency": [[0, 1], [1, 3], [3, 4], [4, 6], [6, 7], [7, 8], [8, 9]],
        },
        "sessions": sessions,
        "edges": [{"u": u, "v": v, "reason": r} for u, v, r in edges],
        "rooms": rooms if rooms is not None else [_room("r1"), _room("r2"), _room("r3")],
        "faculty_availability": [
            {"faculty_id": f,
             "unavailable_slots": [{"day": d, "period": p} for d, p in unavailable.get(f, [])]}
            for f in faculty
        ],
        "lab_blocks": [
            {"id": bid, "session_ids": sids, "duration_periods": dur,
             "must_be_contiguous": True}
            for bid, sids, dur in blocks
        ],
        "pinned_occupancy": list(pins),
    }


def _pin(
    day: int,
    period: int,
    *,
    faculty: Sequence[str] = (),
    rooms: Sequence[str] = (),
    cohorts: Sequence[str] = (),
) -> dict[str, Any]:
    return {"day": day, "period": period, "faculty_ids": list(faculty),
            "room_ids": list(rooms), "cohort_ids": list(cohorts)}


def _solution(*placements: tuple[str, int, int, str] | tuple[str, int, int, str, str]
              ) -> dict[str, Any]:
    """(sid, day, period, room[, sub_room])"""
    items = []
    for p in placements:
        sid, day, period, room = p[:4]
        sub = p[4] if len(p) == 5 else None
        items.append({"session_id": sid, "day": day, "period": period,
                      "room_id": room, "sub_room_id": sub})
    return {
        "schema_version": "solution.v1",
        "status": "solved",
        "assignment": items,
        "quality": {"score": 0.0, "breakdown": []},
        "displaced": [],
        "metadata": {"algorithm": "hand", "runtime_ms": 0.0, "sessions_total": len(items),
                     "sessions_assigned": len(items), "slots_used": None, "backtracks": None},
    }


def _kinds(violations: list[Violation]) -> list[str]:
    return [v.kind for v in violations]


# ======================================================================
# Clean timetable
# ======================================================================


class TestClean:
    def test_conflict_free_timetable_has_no_violations(self) -> None:
        el = _edge_list(
            [_session("a", "f1", "c1"), _session("b", "f1", "c2"),
             _session("lab", "f2", "c1", duration=2, lab=True)],
            edges=[("a", "b", "FACULTY"), ("a", "lab", "COHORT")],
            rooms=[_room("r1"), _room("L", lab=True)],
        )
        sol = _solution(("a", 0, 0, "r1"), ("b", 0, 1, "r1"), ("lab", 0, 1, "L"))
        assert validate_solution(el, sol) == []

    def test_infeasible_solution_claims_nothing(self) -> None:
        el = _edge_list([_session("a")])
        assert validate_solution(el, {"status": "infeasible"}) == []

    def test_kinds_are_the_reconciled_enum(self) -> None:
        assert KINDS == (
            "FACULTY_CLASH", "COHORT_CLASH", "ROOM_CLASH", "ROOM_OCCUPANCY",
            "ROOM_CAPACITY", "ROOM_TYPE", "FACULTY_UNAVAILABLE", "PINNED_BLOCK",
            "LAB_CONTIGUITY", "FIXED_SLOT",
        )


# ======================================================================
# Edge clashes — every occupied period counts
# ======================================================================


class TestEdgeClashes:
    @pytest.mark.parametrize(
        ("reason", "kind"),
        [("FACULTY", "FACULTY_CLASH"), ("COHORT", "COHORT_CLASH"), ("ROOM", "ROOM_CLASH")],
    )
    def test_same_slot_on_an_edge(self, reason: str, kind: str) -> None:
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")],
                        edges=[("a", "b", reason)])
        [v] = validate_solution(el, _solution(("a", 1, 4, "r1"), ("b", 1, 4, "r2")))
        assert (v.kind, v.session_ids, v.slots) == (kind, ("a", "b"), (SlotId(1, 4),))

    def test_second_period_of_a_double_counts(self) -> None:
        """A 2-period session at Mon 10.00 also occupies Mon 11.15."""
        el = _edge_list([_session("lab", "f1", "c1", duration=2),
                         _session("thy", "f2", "c1")],
                        edges=[("lab", "thy", "COHORT")])
        [v] = validate_solution(el, _solution(("lab", 0, 1, "r1"), ("thy", 0, 3, "r2")))
        assert (v.kind, v.slots) == ("COHORT_CLASH", (SlotId(0, 3),))

    def test_double_period_spanning_lunch(self) -> None:
        el = _edge_list([_session("lab", "f1", "c1", duration=2),
                         _session("thy", "f1", "c2")],
                        edges=[("lab", "thy", "FACULTY")])
        [v] = validate_solution(el, _solution(("lab", 0, 4, "r1"), ("thy", 0, 6, "r2")))
        assert (v.kind, v.slots) == ("FACULTY_CLASH", (SlotId(0, 6),))

    def test_no_edge_no_clash(self) -> None:
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")])
        assert validate_solution(el, _solution(("a", 0, 0, "r1"), ("b", 0, 0, "r2"))) == []


# ======================================================================
# Rooms
# ======================================================================


class TestRooms:
    def test_same_room_same_slot(self) -> None:
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")])
        [v] = validate_solution(el, _solution(("a", 0, 0, "r1"), ("b", 0, 0, "r1")))
        assert (v.kind, v.session_ids, v.entity_ids) == ("ROOM_OCCUPANCY", ("a", "b"), ("r1",))

    def test_room_held_for_every_period(self) -> None:
        el = _edge_list([_session("a", "f1", "c1", duration=2),
                         _session("b", "f2", "c2")])
        [v] = validate_solution(el, _solution(("a", 0, 0, "r1"), ("b", 0, 1, "r1")))
        assert (v.kind, v.slots) == ("ROOM_OCCUPANCY", (SlotId(0, 1),))

    def test_different_sub_rooms_are_legal(self) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P"), _room("P-B", 20, parent="P")]
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")], rooms=rooms)
        sol = _solution(("a", 0, 0, "P", "P-A"), ("b", 0, 0, "P", "P-B"))
        assert validate_solution(el, sol) == []

    def test_same_sub_room_is_a_clash(self) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P")]
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")], rooms=rooms)
        sol = _solution(("a", 0, 0, "P", "P-A"), ("b", 0, 0, "P", "P-A"))
        assert _kinds(validate_solution(el, sol)) == ["ROOM_OCCUPANCY"]

    def test_whole_room_locks_out_its_sub_rooms(self) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P")]
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f2", "c2")], rooms=rooms)
        sol = _solution(("a", 0, 0, "P"), ("b", 0, 0, "P", "P-A"))
        [v] = validate_solution(el, sol)
        assert (v.kind, v.entity_ids) == ("ROOM_OCCUPANCY", ("P", "P-A"))

    def test_capacity(self) -> None:
        el = _edge_list([_session("a", size=31)])
        [v] = validate_solution(el, _solution(("a", 0, 0, "r1")))
        assert (v.kind, v.entity_ids) == ("ROOM_CAPACITY", ("r1",))

    def test_sub_room_capacity_is_the_sub_rooms(self) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P")]
        el = _edge_list([_session("a", size=25)], rooms=rooms)
        assert _kinds(validate_solution(el, _solution(("a", 0, 0, "P", "P-A")))) == [
            "ROOM_CAPACITY"
        ]

    def test_lab_session_in_a_classroom(self) -> None:
        el = _edge_list([_session("a", lab=True)])
        [v] = validate_solution(el, _solution(("a", 0, 0, "r1")))
        assert (v.kind, v.entity_ids) == ("ROOM_TYPE", ("r1",))


# ======================================================================
# Availability, pins, contiguity, fixed slots
# ======================================================================


class TestAvailabilityAndPins:
    def test_faculty_unavailable_in_second_period(self) -> None:
        el = _edge_list([_session("a", "f1", duration=2)], unavailable={"f1": [(0, 3)]})
        [v] = validate_solution(el, _solution(("a", 0, 1, "r1")))
        assert (v.kind, v.slots, v.entity_ids) == (
            "FACULTY_UNAVAILABLE", (SlotId(0, 3),), ("f1",)
        )

    @pytest.mark.parametrize("who", ["faculty", "cohorts"])
    def test_pinned_faculty_or_cohort(self, who: str) -> None:
        pin = _pin(2, 7, **{who: ["f1" if who == "faculty" else "c1"]})
        el = _edge_list([_session("a", "f1", "c1")], pins=[pin])
        [v] = validate_solution(el, _solution(("a", 2, 7, "r1")))
        assert (v.kind, v.slots) == ("PINNED_BLOCK", (SlotId(2, 7),))

    @pytest.mark.parametrize(
        ("pinned", "room", "sub"),
        [("P", "P", None), ("P", "P", "P-A"), ("P-A", "P", "P-A"), ("P-A", "P", None)],
        ids=["room", "parent-locks-sub", "sub", "sub-locks-parent"],
    )
    def test_pinned_room_with_sub_room_lockout(
        self, pinned: str, room: str, sub: str | None
    ) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P")]
        el = _edge_list([_session("a")], rooms=rooms, pins=[_pin(0, 0, rooms=[pinned])])
        place = ("a", 0, 0, room, sub) if sub else ("a", 0, 0, room)
        [v] = validate_solution(el, _solution(place))
        assert (v.kind, v.entity_ids) == ("PINNED_BLOCK", (pinned,))

    def test_pinned_sibling_sub_room_is_fine(self) -> None:
        rooms = [_room("P", 60), _room("P-A", 20, parent="P"), _room("P-B", 20, parent="P")]
        el = _edge_list([_session("a")], rooms=rooms, pins=[_pin(0, 0, rooms=["P-B"])])
        assert validate_solution(el, _solution(("a", 0, 0, "P", "P-A"))) == []


class TestContiguityAndFixed:
    def test_double_cannot_start_in_last_period(self) -> None:
        el = _edge_list([_session("a", duration=2)])
        [v] = validate_solution(el, _solution(("a", 0, 9, "r1")))
        assert (v.kind, v.slots) == ("LAB_CONTIGUITY", (SlotId(0, 9),))

    def test_block_members_must_start_together(self) -> None:
        el = _edge_list(
            [_session("a", "f1", "c1", duration=2), _session("b", "f2", "c2", duration=2)],
            blocks=[("blk", ["a", "b"], 2)],
        )
        [v] = validate_solution(el, _solution(("a", 0, 0, "r1"), ("b", 0, 1, "r2")))
        assert (v.kind, v.session_ids, v.entity_ids) == ("LAB_CONTIGUITY", ("a", "b"), ("blk",))

    def test_block_spanning_short_break_is_fine(self) -> None:
        el = _edge_list(
            [_session("a", "f1", "c1", duration=2), _session("b", "f2", "c2", duration=2)],
            blocks=[("blk", ["a", "b"], 2)],
        )
        assert validate_solution(el, _solution(("a", 0, 1, "r1"), ("b", 0, 1, "r2"))) == []

    def test_fixed_slot_moved(self) -> None:
        el = _edge_list([_session("a", fixed=(2, 0))])
        [v] = validate_solution(el, _solution(("a", 2, 1, "r1")))
        assert (v.kind, v.slots) == ("FIXED_SLOT", (SlotId(2, 0), SlotId(2, 1)))


# ======================================================================
# Malformed input raises; it is not a violation
# ======================================================================


class TestMalformed:
    def test_missing_session(self) -> None:
        el = _edge_list([_session("a"), _session("b")])
        with pytest.raises(ValueError, match="missing"):
            validate_solution(el, _solution(("a", 0, 0, "r1")))

    def test_unknown_session(self) -> None:
        el = _edge_list([_session("a")])
        with pytest.raises(ValueError, match="unknown session"):
            validate_solution(el, _solution(("a", 0, 0, "r1"), ("zz", 0, 1, "r1")))

    def test_duplicate_placement(self) -> None:
        el = _edge_list([_session("a")])
        with pytest.raises(ValueError, match="more than once"):
            validate_solution(el, _solution(("a", 0, 0, "r1"), ("a", 0, 1, "r1")))

    def test_start_on_a_break(self) -> None:
        el = _edge_list([_session("a")])
        with pytest.raises(ValueError, match="non-teaching"):
            validate_solution(el, _solution(("a", 0, 2, "r1")))

    def test_sub_room_of_another_room(self) -> None:
        rooms = [_room("P", 60), _room("Q", 60), _room("P-A", 20, parent="P")]
        el = _edge_list([_session("a")], rooms=rooms)
        with pytest.raises(ValueError, match="not a sub-room"):
            validate_solution(el, _solution(("a", 0, 0, "Q", "P-A")))

    def test_unknown_room(self) -> None:
        el = _edge_list([_session("a")])
        with pytest.raises(ValueError, match="unknown room"):
            validate_solution(el, _solution(("a", 0, 0, "nowhere")))

    def test_non_canonical_grid(self) -> None:
        el = _edge_list([_session("a")])
        el["slot_grid"]["adjacency"] = [[0, 1]]
        with pytest.raises(ValueError, match="adjacency"):
            validate_solution(el, _solution(("a", 0, 0, "r1")))


# ======================================================================
# Committed fixtures
# ======================================================================


def _load(rel: str) -> dict[str, Any]:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


class TestCommittedExamples:
    @pytest.mark.parametrize("folder", ["contracts/examples", "frontend/src/fixtures"])
    def test_solved_example_is_conflict_free(self, folder: str) -> None:
        if not (REPO / folder / "solution_v1.solved.example.json").exists():
            pytest.skip(f"{folder} has no solved example")
        edge_list = _load(f"{folder}/edge_list_v1.example.json")
        solution = _load(f"{folder}/solution_v1.solved.example.json")
        assert validate_solution(edge_list, solution) == []

    def test_violation_to_dict(self) -> None:
        v = Violation("ROOM_TYPE", ("a",), (SlotId(0, 1),), ("r1",), "x")
        assert v.to_dict() == {
            "kind": "ROOM_TYPE", "session_ids": ["a"],
            "slots": [{"day": 0, "period": 1}], "entity_ids": ["r1"], "detail": "x",
        }

    def test_slot_only_entry_point_matches(self) -> None:
        el = _edge_list([_session("a", "f1", "c1"), _session("b", "f1", "c2")],
                        edges=[("a", "b", "FACULTY")])
        assert _kinds(validate_slot_placements(el, {"a": (0, 0), "b": (0, 0)})) == [
            "FACULTY_CLASH"
        ]


# ======================================================================
# Independence and purity
# ======================================================================


class TestIndependence:
    def test_imports_only_stdlib_and_slots(self) -> None:
        """The checker must not share code with the search it checks."""
        tree = ast.parse((REPO / "solver" / "validate.py").read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert imported <= {
            "__future__", "dataclasses", "itertools", "typing", "solver.slots"
        }, imported
