"""Tests for :mod:`solver.backtracking`.

All instances are hand-built small graphs where the correct answer is known
by inspection.

Test coverage:
  - Trail-based undo produces byte-identical domain state after backtrack.
  - A case that requires backtracking (greedy alone fails).
  - A LabBlock that must be placed jointly.
  - The short-break contiguity case (periods 1 and 3 are adjacent).
  - Sub-room legality: two sessions share a parent room via different sub-rooms.
  - Sub-room conflict: same sub-room at the same time is illegal.
  - Capacity check enforcement.
  - An infeasible instance that exhausts the search.
  - Pinned occupancy blocks room placement.
  - Regression, proposal section 5.1: a fixed slot never overrides faculty
    unavailability or pinned blocks; every period of a multi-period placement
    (in a lab block or not) is checked.
  - Solver purity (no networkx import).

Every SOLVED result in this file goes through ``_solve_checked``, which holds it
to the independent checker in :mod:`solver.validate`.
"""

from __future__ import annotations

import pickle
from typing import Any

import pytest

from solver.backtracking import (
    BacktrackResult,
    Room,
    _assign,
    _build_initial_domains,
    _forward_check,
    _new_state,
    _occupied_slots,
    _SolverState,
    _unassign,
    _undo_trail,
    backtrack_solve,
    parse_lab_blocks,
    parse_rooms,
)
from solver.graph import ConflictGraph, build_conflict_graph
from solver.slots import SlotId, is_adjacent
from solver.validate import validate_solution

# ======================================================================
# Helpers — tiny payload builders (adapted from test_graph_colouring)
# ======================================================================


def _slot_grid() -> dict[str, Any]:
    return {
        "days": 5,
        "periods_per_day": 10,
        "teaching_periods": [0, 1, 3, 4, 6, 7, 8, 9],
        "adjacency": [[0, 1], [1, 3], [3, 4], [4, 6], [6, 7], [7, 8], [8, 9]],
    }


def _session(
    sid: str,
    faculty: str = "fac-1",
    cohort: str = "coh-1",
    *,
    fixed_slot: dict[str, int] | None = None,
    subject: str = "subj-1",
    duration: int = 1,
    cohort_size: int = 20,
    session_type: str = "theory",
    requires_lab: bool = False,
) -> dict[str, Any]:
    return {
        "id": sid,
        "subject_id": subject,
        "faculty_id": faculty,
        "cohort_id": cohort,
        "session_type": session_type,
        "duration_periods": duration,
        "cohort_size": cohort_size,
        "requires_lab": requires_lab,
        "fixed_slot": fixed_slot,
    }


def _faculty_avail(
    faculty: str, unavailable: list[dict[str, int]] | None = None
) -> dict[str, Any]:
    return {
        "faculty_id": faculty,
        "unavailable_slots": unavailable or [],
    }


def _edge(u: str, v: str, reason: str = "FACULTY") -> dict[str, str]:
    return {"u": u, "v": v, "reason": reason}


def _room(
    rid: str,
    *,
    capacity: int = 30,
    is_lab: bool = False,
    parent_room_id: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "code": code or rid,
        "capacity": capacity,
        "is_lab": is_lab,
        "parent_room_id": parent_room_id,
    }


def _lab_block(
    block_id: str,
    session_ids: list[str],
    duration: int = 2,
) -> dict[str, Any]:
    return {
        "id": block_id,
        "session_ids": session_ids,
        "duration_periods": duration,
        "must_be_contiguous": True,
    }


def _payload(
    sessions: list[dict[str, Any]],
    edges: list[dict[str, str]] | None = None,
    rooms: list[dict[str, Any]] | None = None,
    faculty_availability: list[dict[str, Any]] | None = None,
    pinned_occupancy: list[dict[str, Any]] | None = None,
    lab_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if faculty_availability is None:
        seen: set[str] = set()
        faculty_availability = []
        for s in sessions:
            fid = s["faculty_id"]
            if fid not in seen:
                seen.add(fid)
                faculty_availability.append(_faculty_avail(fid))
    return {
        "schema_version": "edge_list.v1",
        "slot_grid": _slot_grid(),
        "sessions": sessions,
        "edges": edges or [],
        "rooms": rooms or [_room("room-default", capacity=200)],
        "faculty_availability": faculty_availability,
        "lab_blocks": lab_blocks or [],
        "pinned_occupancy": pinned_occupancy or [],
    }


def _solve_checked(graph: ConflictGraph, payload: dict[str, Any]) -> BacktrackResult:
    """Solve, and hold every SOLVED result to the independent validator."""
    result = backtrack_solve(graph, payload)
    if result.solved:
        violations = validate_solution(payload, result.to_solution_dict())
        assert violations == [], f"solver reported solved but: {violations}"
    return result


# ======================================================================
# Parsing tests
# ======================================================================


class TestParseRooms:
    def test_basic_room(self) -> None:
        rooms = parse_rooms({
            "rooms": [
                {"id": "r1", "code": "508", "capacity": 80,
                 "is_lab": False, "parent_room_id": None}
            ]
        })
        assert len(rooms) == 1
        assert rooms["r1"].capacity == 80
        assert rooms["r1"].parent_room_id is None

    def test_sub_room(self) -> None:
        rooms = parse_rooms({
            "rooms": [
                {"id": "r1", "code": "702", "capacity": 60,
                 "is_lab": True, "parent_room_id": None},
                {"id": "r1-a", "code": "702-A", "capacity": 20,
                 "is_lab": True, "parent_room_id": "r1"},
            ]
        })
        assert rooms["r1-a"].parent_room_id == "r1"


class TestParseLabBlocks:
    def test_basic_block(self) -> None:
        blocks = parse_lab_blocks({
            "lab_blocks": [
                {"id": "lb1", "session_ids": ["s1", "s2"],
                 "duration_periods": 2, "must_be_contiguous": True}
            ]
        })
        assert len(blocks) == 1
        assert blocks[0].session_ids == ("s1", "s2")
        assert blocks[0].duration_periods == 2


# ======================================================================
# Trail-based undo: exact domain restoration
# ======================================================================


class TestTrailUndo:
    """The undo must be EXACT.

    Each check compares the domains two ways: plain set equality, and the
    pickled bytes of a canonical (sorted) form.  Pickling the raw sets would not
    be a meaningful byte test - a set's iteration order can change after values
    are removed and re-added even though the set is equal - so the canonical
    form is what gets pickled.
    """

    @staticmethod
    def _sets(state: _SolverState) -> dict[str, frozenset[tuple[SlotId, str]]]:
        return {sid: frozenset(domain) for sid, domain in state.domains.items()}

    @staticmethod
    def _pickled(state: _SolverState) -> bytes:
        canonical = sorted(
            (sid, sorted(domain)) for sid, domain in state.domains.items()
        )
        return pickle.dumps(canonical)

    @staticmethod
    def _state(payload: dict[str, Any]) -> _SolverState:
        state = _new_state(build_conflict_graph(payload), payload)
        _build_initial_domains(state)
        return state

    def test_domain_state_restored_exactly_after_full_backtrack(self) -> None:
        """After FC + undo, domains must be identical to before."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1"),
                _session("s2", faculty="f2", cohort="c2"),
                _session("s3", faculty="f3", cohort="c3"),
            ],
            edges=[
                _edge("s1", "s2", "COHORT"),
                _edge("s1", "s3", "COHORT"),
            ],
            rooms=[_room("r1", capacity=200)],
        )
        state = self._state(payload)
        sets_before = self._sets(state)
        bytes_before = self._pickled(state)

        # Assign s1 and forward-check
        slot = SlotId(0, 0)
        trail_start = len(state.trail)
        _assign(state, "s1", slot, "r1", (slot,))
        _forward_check(state, "s1")

        assert self._sets(state) != sets_before, (
            "FC should have changed at least one domain"
        )

        _undo_trail(state, trail_start)
        _unassign(state, "s1")

        assert self._sets(state) == sets_before
        assert self._pickled(state) == bytes_before, (
            "Domain state must be byte-identical after undo"
        )

    def test_multiple_fc_and_undo_cycles(self) -> None:
        """Multiple assign/FC/undo cycles must leave domains untouched."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1"),
                _session("s2", faculty="f1", cohort="c2"),
            ],
            edges=[_edge("s1", "s2", "FACULTY")],
            rooms=[_room("r1", capacity=200)],
        )
        state = self._state(payload)
        sets_before = self._sets(state)
        bytes_before = self._pickled(state)

        for slot in [SlotId(0, 0), SlotId(1, 1), SlotId(2, 3)]:
            t = len(state.trail)
            _assign(state, "s1", slot, "r1", (slot,))
            _forward_check(state, "s1")
            _undo_trail(state, t)
            _unassign(state, "s1")

        assert self._sets(state) == sets_before
        assert self._pickled(state) == bytes_before

    def test_multi_period_prune_and_undo_is_exact(self) -> None:
        """A 2-period placement prunes neighbours in BOTH periods, and undo
        restores exactly what was pruned."""
        payload = _payload(
            sessions=[
                _session("lab", faculty="f1", cohort="c1", duration=2,
                         session_type="lab", requires_lab=True),
                _session("thy", faculty="f2", cohort="c1"),
                _session("other", faculty="f3", cohort="c3"),
            ],
            edges=[_edge("lab", "thy", "COHORT")],
            rooms=[_room("lab-r", capacity=30, is_lab=True),
                   _room("class-r", capacity=30)],
        )
        state = self._state(payload)
        sets_before = self._sets(state)
        bytes_before = self._pickled(state)

        start = SlotId(0, 1)  # occupies periods 1 and 3, across the short break
        occupied = _occupied_slots(state, "lab", start)
        assert occupied == (SlotId(0, 1), SlotId(0, 3))

        t = len(state.trail)
        _assign(state, "lab", start, "lab-r", occupied)
        assert _forward_check(state, "lab")

        thy_starts = {s for s, _ in state.domains["thy"]}
        assert SlotId(0, 1) not in thy_starts
        assert SlotId(0, 3) not in thy_starts, "second period must be pruned too"
        # The unrelated session keeps both periods (its room differs).
        other_starts = {s for s, _ in state.domains["other"]}
        assert {SlotId(0, 1), SlotId(0, 3)} <= other_starts

        _undo_trail(state, t)
        _unassign(state, "lab")

        assert self._sets(state) == sets_before
        assert self._pickled(state) == bytes_before
        assert state.room_occupancy == {}


# ======================================================================
# Backtracking required (greedy fails)
# ======================================================================


class TestBacktrackingRequired:
    """Instances where greedy colouring fails but backtracking succeeds."""

    def test_greedy_fails_backtrack_succeeds(self) -> None:
        """The counterexample from the solved-example doc:
        a high-degree vertex with a broad domain can starve tight-domain
        vertices if assigned greedily.  Backtracking reassigns it.

        We use 4 sessions with 3 available slots:
        C1 conflicts with T1, T2, L1.
        T1 conflicts with T2.
        T1 and T2 have restricted faculty availability (2 slots each).
        """
        # Only 3 slots available: day=4 periods 6,7,8
        # Make all other periods unavailable for everyone via faculty unavail.
        from solver.slots import all_slots

        avail_slots_set = {SlotId(4, 6), SlotId(4, 7), SlotId(4, 8)}
        unavail = [
            {"day": s.day, "period": s.period}
            for s in all_slots()
            if s not in avail_slots_set
        ]
        # T1 and T2 can only do periods 6 and 7.
        unavail_restricted = [*unavail, {"day": 4, "period": 8}]

        payload = _payload(
            sessions=[
                _session("C1", faculty="f1", cohort="c1"),
                _session("T1", faculty="f2", cohort="c2"),
                _session("T2", faculty="f3", cohort="c3"),
                _session("L1", faculty="f4", cohort="c4"),
            ],
            edges=[
                _edge("C1", "T1", "COHORT"),
                _edge("C1", "T2", "COHORT"),
                _edge("C1", "L1", "COHORT"),
                _edge("T1", "T2", "COHORT"),
            ],
            rooms=[
                _room("r1", capacity=200),
                _room("r2", capacity=200),
            ],
            faculty_availability=[
                _faculty_avail("f1", unavail),  # C1: {6,7,8}
                _faculty_avail("f2", unavail_restricted),  # T1: {6,7}
                _faculty_avail("f3", unavail_restricted),  # T2: {6,7}
                _faculty_avail("f4",  # L1: {6,8}
                               [*unavail, {"day": 4, "period": 7}]),
            ],
        )

        # First verify greedy fails
        from solver.colouring import welsh_powell

        graph = build_conflict_graph(payload)
        _, unplaced = welsh_powell(graph)
        assert len(unplaced) > 0, "Greedy should fail on this instance"

        # Now backtracking should succeed
        result = _solve_checked(graph, payload)
        assert result.solved, (
            "Backtracking should solve an instance that greedy cannot"
        )
        assert len(result.assignment) == 4
        # Verify no conflicts
        for sid1 in result.assignment:
            for sid2 in graph.neighbours(sid1):
                if sid2 in result.assignment:
                    assert result.assignment[sid1] != result.assignment[sid2], (
                        f"{sid1} and {sid2} conflict but share slot"
                    )


# ======================================================================
# LabBlock joint allocation
# ======================================================================


class TestLabBlock:
    """A LabBlock's N sessions must be placed jointly or not at all."""

    def test_lab_block_joint_placement(self) -> None:
        """Four batch sessions in a lab block all get the same starting slot
        and different rooms."""
        payload = _payload(
            sessions=[
                _session("lb-A", faculty="f1", cohort="c-A",
                         session_type="lab", requires_lab=True,
                         duration=2, cohort_size=20),
                _session("lb-B", faculty="f2", cohort="c-B",
                         session_type="lab", requires_lab=True,
                         duration=2, cohort_size=20),
                _session("lb-C", faculty="f3", cohort="c-C",
                         session_type="lab", requires_lab=True,
                         duration=2, cohort_size=20),
                _session("lb-D", faculty="f4", cohort="c-D",
                         session_type="lab", requires_lab=True,
                         duration=2, cohort_size=20),
            ],
            edges=[],
            rooms=[
                _room("lab-702-a", capacity=20, is_lab=True,
                      parent_room_id="lab-702"),
                _room("lab-702-b", capacity=20, is_lab=True,
                      parent_room_id="lab-702"),
                _room("lab-603-1", capacity=20, is_lab=True,
                      parent_room_id="lab-603"),
                _room("lab-603-2", capacity=20, is_lab=True,
                      parent_room_id="lab-603"),
                _room("lab-702", capacity=60, is_lab=True),
                _room("lab-603", capacity=60, is_lab=True),
            ],
            lab_blocks=[
                _lab_block("blk-1", ["lb-A", "lb-B", "lb-C", "lb-D"],
                           duration=2),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert result.solved, "Lab block should be placed jointly"

        # All 4 sessions must have the SAME starting slot
        slots = {result.assignment[sid] for sid in
                 ["lb-A", "lb-B", "lb-C", "lb-D"]}
        assert len(slots) == 1, (
            f"All lab block sessions should share a slot, got {slots}"
        )

        # All 4 sessions must have DIFFERENT rooms
        rooms = [result.room_assignment[sid] for sid in
                 ["lb-A", "lb-B", "lb-C", "lb-D"]]
        assert len(set(rooms)) == 4, (
            f"Each session should have a different room, got {rooms}"
        )


# ======================================================================
# Double-period contiguity: the short-break case
# ======================================================================


class TestContiguity:
    """Teaching-sequence adjacency, NOT wall-clock adjacency.

    The real data has labs spanning the 11.00-11.15 short break
    (period 1 -> period 3).  Period 2 IS the break and is NOT a teaching
    period.  Periods 1 and 3 are adjacent in teaching order, even though
    their wall-clock indices differ by 2.
    """

    def test_period_1_and_3_are_teaching_adjacent(self) -> None:
        """is_adjacent(1, 3) must be True — the short-break span."""
        assert is_adjacent(SlotId(0, 1), SlotId(0, 3)), (
            "Periods 1 and 3 should be adjacent across the short break"
        )

    def test_period_1_and_2_are_NOT_adjacent(self) -> None:
        """Period 2 is the break, so is_adjacent(1, 2) must be False."""
        # SlotId(0, 2) is a break period. is_adjacent should return False
        # because period 2 is not a teaching period.
        assert not is_adjacent(SlotId(0, 1), SlotId(0, 2)), (
            "Period 2 is the break — not adjacent to anything"
        )

    def test_lab_block_spans_short_break(self) -> None:
        """A 2-period lab that starts at period 1 (10:00) should run into
        period 3 (11:15), spanning the short break at period 2.

        This is the ET Lab /DDA /509 (10.00-12.00) case from CONTEXT.md."""
        payload = _payload(
            sessions=[
                _session("lab-s1", faculty="f1", cohort="c1",
                         session_type="lab", requires_lab=True,
                         duration=2, cohort_size=20),
            ],
            rooms=[_room("lab-509", capacity=40, is_lab=True)],
            lab_blocks=[
                _lab_block("blk-1", ["lab-s1"], duration=2),
            ],
            # Force the session into a slot where period 1 is the only
            # valid starting point by making everything else unavailable.
            faculty_availability=[
                _faculty_avail("f1", [
                    {"day": d, "period": p}
                    for d in range(5) for p in [0, 1, 3, 4, 6, 7, 8, 9]
                    if not (d == 0 and p in (1, 3))
                ]),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert result.solved, "Lab should be placed spanning the short break"
        assert result.assignment["lab-s1"] == SlotId(0, 1), (
            f"Lab should start at period 1, got {result.assignment['lab-s1']}"
        )

    def test_period_4_and_6_adjacent_across_lunch(self) -> None:
        """Periods 4 and 6 are adjacent in teaching order across lunch."""
        assert is_adjacent(SlotId(0, 4), SlotId(0, 6)), (
            "Periods 4 and 6 should be adjacent across lunch break"
        )


# ======================================================================
# Sub-room awareness
# ======================================================================


class TestSubRoomAwareness:
    """Two sessions in DIFFERENT sub-rooms of the SAME parent are legal."""

    def test_different_sub_rooms_same_slot_is_legal(self) -> None:
        """Two non-conflicting sessions can share a physical room via
        different sub-rooms in the same slot."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1",
                         requires_lab=True, cohort_size=20),
                _session("s2", faculty="f2", cohort="c2",
                         requires_lab=True, cohort_size=20),
            ],
            edges=[],  # No conflict edge — different faculty, different cohort
            rooms=[
                _room("parent-702", capacity=60, is_lab=True),
                _room("702-A", capacity=20, is_lab=True,
                      parent_room_id="parent-702"),
                _room("702-B", capacity=20, is_lab=True,
                      parent_room_id="parent-702"),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert result.solved

        # They CAN share the same slot
        # (they might or might not depending on search order, but if they do
        #  the result must be valid)
        # Check that no room collision: if same slot, must be different rooms.
        if result.assignment["s1"] == result.assignment["s2"]:
            assert result.room_assignment["s1"] != result.room_assignment["s2"]

    def test_same_sub_room_same_slot_is_conflict(self) -> None:
        """Two sessions cannot share the same sub-room at the same time,
        even if they have no graph edge."""
        # Force both sessions into the same slot and give only one sub-room.
        from solver.slots import all_slots

        forced_slot = SlotId(0, 0)
        unavail = [
            {"day": s.day, "period": s.period}
            for s in all_slots()
            if s != forced_slot
        ]

        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1",
                         requires_lab=True, cohort_size=20),
                _session("s2", faculty="f2", cohort="c2",
                         requires_lab=True, cohort_size=20),
            ],
            edges=[],
            rooms=[
                # Only one sub-room — they can't both fit.
                _room("702-A", capacity=20, is_lab=True,
                      parent_room_id="parent-702"),
            ],
            faculty_availability=[
                _faculty_avail("f1", unavail),
                _faculty_avail("f2", unavail),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert not result.solved, (
            "Two sessions cannot share one sub-room at the same time"
        )

    def test_parent_room_occupied_blocks_sub_rooms(self) -> None:
        """If a session occupies the parent room, its sub-rooms are blocked."""
        from solver.slots import all_slots

        forced_slot = SlotId(0, 0)
        unavail = [
            {"day": s.day, "period": s.period}
            for s in all_slots()
            if s != forced_slot
        ]

        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1",
                         cohort_size=60),  # Needs the parent (cap 60)
                _session("s2", faculty="f2", cohort="c2",
                         requires_lab=True, cohort_size=20),
            ],
            edges=[],
            rooms=[
                _room("parent-702", capacity=60, is_lab=True),
                _room("702-A", capacity=20, is_lab=True,
                      parent_room_id="parent-702"),
            ],
            faculty_availability=[
                _faculty_avail("f1", unavail),
                _faculty_avail("f2", unavail),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        # s1 takes parent-702 (only room with cap ≥ 60)
        # s2 needs lab and cap ≥ 20, but 702-A is blocked by parent
        # parent-702 is taken by s1
        assert not result.solved, (
            "Sub-room blocked when parent room occupied"
        )


# ======================================================================
# Capacity check
# ======================================================================


class TestCapacity:
    """Session's cohort_size must fit the assigned room's capacity."""

    def test_cohort_too_large_for_only_room(self) -> None:
        """No room large enough → infeasible."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort_size=200),
            ],
            rooms=[_room("r1", capacity=50)],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert not result.solved, "No room with sufficient capacity"

    def test_cohort_fits_large_room(self) -> None:
        """A session fits a room with adequate capacity."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort_size=60),
            ],
            rooms=[_room("r1", capacity=80)],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert result.solved
        assert result.room_assignment["s1"] == "r1"


# ======================================================================
# Infeasible instance
# ======================================================================


class TestInfeasible:
    """The search exhausts all branches and reports infeasibility."""

    def test_complete_graph_exceeding_slots(self) -> None:
        """K_{n} with fewer available slots than n → infeasible.

        We make a clique of 3 sessions but only 2 available slots,
        so at least one session can't be placed.
        """
        from solver.slots import all_slots

        avail_set = {SlotId(0, 0), SlotId(0, 1)}
        unavail = [
            {"day": s.day, "period": s.period}
            for s in all_slots()
            if s not in avail_set
        ]

        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1"),
                _session("s2", faculty="f2", cohort="c2"),
                _session("s3", faculty="f3", cohort="c3"),
            ],
            edges=[
                _edge("s1", "s2", "COHORT"),
                _edge("s2", "s3", "COHORT"),
                _edge("s1", "s3", "COHORT"),
            ],
            rooms=[_room("r1", capacity=200)],
            faculty_availability=[
                _faculty_avail("f1", unavail),
                _faculty_avail("f2", unavail),
                _faculty_avail("f3", unavail),
            ],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert not result.solved, (
            "K3 with 2 slots should be infeasible"
        )
        assert result.nodes_explored > 0


# ======================================================================
# Pinned occupancy blocks room placement
# ======================================================================


class TestPinnedOccupancy:
    """Pinned occupancy must prevent room placement."""

    def test_pinned_room_blocks_session(self) -> None:
        """A session cannot be placed in a room that is pinned at that slot."""
        from solver.slots import all_slots

        forced_slot = SlotId(0, 0)
        unavail = [
            {"day": s.day, "period": s.period}
            for s in all_slots()
            if s != forced_slot
        ]

        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort="c1", cohort_size=20),
            ],
            rooms=[_room("r1", capacity=200)],
            faculty_availability=[_faculty_avail("f1", unavail)],
            pinned_occupancy=[{
                "day": 0, "period": 0,
                "faculty_ids": [],
                "room_ids": ["r1"],
                "cohort_ids": [],
            }],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        # The only slot available has its only room pinned → infeasible
        assert not result.solved


# ======================================================================
# Fixed-slot sessions
# ======================================================================


class TestFixedSlot:
    """Sessions with fixed_slot must be assigned to exactly that slot."""

    def test_fixed_slot_honoured(self) -> None:
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1",
                         fixed_slot={"day": 2, "period": 3}),
            ],
            rooms=[_room("r1", capacity=200)],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert result.solved
        assert result.assignment["s1"] == SlotId(2, 3)


# ======================================================================
# Integration with contract example payload
# ======================================================================


class TestContractExampleBacktrack:
    """The committed example payload should solve via backtracking."""

    @pytest.fixture()
    def example_payload(self) -> dict[str, Any]:
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "examples"
            / "edge_list_v1.example.json"
        )
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_example_solves(
        self, example_payload: dict[str, Any]
    ) -> None:
        graph = build_conflict_graph(example_payload)
        result = _solve_checked(graph, example_payload)
        assert result.solved, (
            "Contract example should be solvable by backtracking"
        )
        # Every session should be assigned
        assert len(result.assignment) == len(graph.sessions)

    def test_example_no_slot_conflicts(
        self, example_payload: dict[str, Any]
    ) -> None:
        graph = build_conflict_graph(example_payload)
        result = _solve_checked(graph, example_payload)
        assert result.solved
        for sid in result.assignment:
            for neighbour in graph.neighbours(sid):
                if neighbour in result.assignment:
                    assert result.assignment[sid] != result.assignment[neighbour]

    def test_example_fixed_slot_honoured(
        self, example_payload: dict[str, Any]
    ) -> None:
        graph = build_conflict_graph(example_payload)
        result = _solve_checked(graph, example_payload)
        assert result.solved
        # sess-0008 has fixed_slot day=2 period=0
        assert result.assignment["sess-0008"] == SlotId(2, 0)

    def test_example_lab_block_jointly_placed(
        self, example_payload: dict[str, Any]
    ) -> None:
        graph = build_conflict_graph(example_payload)
        result = _solve_checked(graph, example_payload)
        assert result.solved
        # All sessions in labblk-0001 should share the same starting slot.
        block_sids = ["sess-0001", "sess-0002", "sess-0003", "sess-0004"]
        block_slots = {result.assignment[sid] for sid in block_sids}
        assert len(block_slots) == 1, (
            f"Lab block sessions should all start at the same slot, "
            f"got {block_slots}"
        )

    def test_example_solution_conforms_to_solution_v1_schema(
        self, example_payload: dict[str, Any]
    ) -> None:
        import json
        from pathlib import Path

        from jsonschema import Draft202012Validator

        graph = build_conflict_graph(example_payload)
        result = _solve_checked(graph, example_payload)
        assert result.solved

        sol_dict = result.to_solution_dict()
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "solution_v1.schema.json"
        )
        with schema_path.open(encoding="utf-8") as fh:
            solution_schema = json.load(fh)

        # Must validate cleanly without exception
        Draft202012Validator(solution_schema).validate(sol_dict)

    def test_infeasible_solution_conforms_to_solution_v1_schema(self) -> None:
        import json
        from pathlib import Path

        from jsonschema import Draft202012Validator

        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", cohort_size=200),
            ],
            rooms=[_room("r1", capacity=50)],
        )
        graph = build_conflict_graph(payload)
        result = _solve_checked(graph, payload)
        assert not result.solved

        sol_dict = result.to_solution_dict()
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "solution_v1.schema.json"
        )
        with schema_path.open(encoding="utf-8") as fh:
            solution_schema = json.load(fh)

        Draft202012Validator(solution_schema).validate(sol_dict)


# ======================================================================
# Regression — docs/contract-change-proposal-v2.md section 5.1
# ======================================================================


def _only_open(*slots: SlotId) -> list[dict[str, int]]:
    """Unavailability list leaving exactly *slots* open for a faculty member."""
    from solver.slots import all_slots

    keep = set(slots)
    return [{"day": s.day, "period": s.period} for s in all_slots() if s not in keep]


def _hand_solution(placements: list[tuple[str, int, int, str]]) -> dict[str, Any]:
    """A hand-built solution_v1 'solved' payload (physical rooms only)."""
    return {
        "schema_version": "solution.v1",
        "status": "solved",
        "assignment": [
            {"session_id": sid, "day": d, "period": p, "room_id": r, "sub_room_id": None}
            for sid, d, p, r in placements
        ],
        "quality": {"score": 0.0, "breakdown": []},
        "displaced": [],
        "metadata": {
            "algorithm": "hand-built", "runtime_ms": 0.0,
            "sessions_total": len(placements), "sessions_assigned": len(placements),
            "slots_used": None, "backtracks": None,
        },
    }


class TestRegressionFixedSlotVsAvailability:
    """Bug 1: a fixed_slot overrode faculty unavailability.

    ``available_slots_for`` returned ``[fixed_slot]`` before consulting
    availability, so a session fixed to a slot its faculty member is
    unavailable in was placed and reported solved.
    """

    @staticmethod
    def _repro() -> dict[str, Any]:
        # Section 5.1 observation 1: f1 is unavailable at Wednesday 11.15,
        # and s1 is fixed to exactly that slot.
        return _payload(
            sessions=[_session("s1", faculty="f1", fixed_slot={"day": 2, "period": 3})],
            rooms=[_room("r1", capacity=200)],
            faculty_availability=[_faculty_avail("f1", [{"day": 2, "period": 3}])],
        )

    def test_section_5_1_fixed_slot_in_unavailable_slot_is_infeasible(self) -> None:
        payload = self._repro()
        result = _solve_checked(build_conflict_graph(payload), payload)
        assert not result.solved
        assert result.unplaced_sessions == ["s1"]

    def test_validator_flags_what_the_old_solver_returned(self) -> None:
        """The pre-fix output (s1 at its fixed slot) is a FACULTY_UNAVAILABLE."""
        violations = validate_solution(self._repro(), _hand_solution([("s1", 2, 3, "r1")]))
        assert [(v.kind, v.session_ids, v.slots) for v in violations] == [
            ("FACULTY_UNAVAILABLE", ("s1",), (SlotId(2, 3),)),
        ]

    def test_available_slots_for_intersects_fixed_slot(self) -> None:
        from solver.graph import available_slots_for

        graph = build_conflict_graph(self._repro())
        assert available_slots_for(graph, graph.sessions["s1"]) == []

    @pytest.mark.parametrize("pinned_key", ["faculty_ids", "cohort_ids"])
    def test_fixed_slot_in_pinned_slot_is_infeasible(self, pinned_key: str) -> None:
        pin: dict[str, Any] = {
            "day": 2, "period": 3, "faculty_ids": [], "room_ids": [], "cohort_ids": [],
        }
        pin[pinned_key] = ["f1" if pinned_key == "faculty_ids" else "c1"]
        payload = _payload(
            sessions=[_session("s1", faculty="f1", cohort="c1",
                               fixed_slot={"day": 2, "period": 3})],
            rooms=[_room("r1", capacity=200)],
            pinned_occupancy=[pin],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_fixed_multi_period_session_needs_every_period_open(self) -> None:
        """Fixed at period 1, but its second period (3) is unavailable."""
        payload = _payload(
            sessions=[_session("s1", faculty="f1", duration=2,
                               fixed_slot={"day": 0, "period": 1})],
            rooms=[_room("r1", capacity=200)],
            faculty_availability=[_faculty_avail("f1", [{"day": 0, "period": 3}])],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_two_fixed_sessions_with_an_edge_in_one_slot_are_infeasible(self) -> None:
        """Fixed sessions used to be pre-placed with no neighbour check."""
        payload = _payload(
            sessions=[
                _session("s1", faculty="f1", fixed_slot={"day": 1, "period": 0}),
                _session("s2", faculty="f1", fixed_slot={"day": 1, "period": 0}),
            ],
            edges=[_edge("s1", "s2", "FACULTY")],
            rooms=[_room("r1", capacity=200), _room("r2", capacity=200)],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_infeasible_result_keeps_placeholder_diagnosis_shape(self) -> None:
        payload = self._repro()
        sol = _solve_checked(build_conflict_graph(payload), payload).to_solution_dict()
        assert sol["status"] == "infeasible"
        entry = sol["diagnosis"]["minimal_conflicting_set"][0]
        assert entry["constraint_id"] == "unplaced.s1"
        assert entry["kind"] == "UNSATISFIABLE_DOMAIN"


class TestRegressionMultiPeriodOccupancy:
    """Bug 2: only the first period of a multi-period placement was checked.

    Section 5.1 observation 2: a 2-period lab for cohort C1 at Monday
    periods 0-1 plus a C1 theory session with a COHORT edge to it returned
    solved with the theory at Monday period 1 - both at Monday period 1.
    """

    @staticmethod
    def _repro(
        *, standalone: bool = False, theory_open: tuple[SlotId, ...] = ()
    ) -> dict[str, Any]:
        lab_open = (SlotId(0, 0), SlotId(0, 1))  # lab can only run Mon 09.00-11.00
        thy_open = (SlotId(0, 1), *theory_open)  # theory forced into Mon 10.00
        return _payload(
            sessions=[
                _session("lab", faculty="f-lab", cohort="C1", duration=2,
                         session_type="lab", requires_lab=True),
                _session("thy", faculty="f-thy", cohort="C1"),
            ],
            edges=[_edge("lab", "thy", "COHORT")],
            rooms=[_room("lab-r", capacity=30, is_lab=True),
                   _room("class-r", capacity=30)],
            faculty_availability=[
                _faculty_avail("f-lab", _only_open(*lab_open)),
                _faculty_avail("f-thy", _only_open(*thy_open)),
            ],
            lab_blocks=[] if standalone else [_lab_block("blk", ["lab"], duration=2)],
        )

    def test_section_5_1_lab_and_theory_both_at_monday_period_1_is_infeasible(
        self,
    ) -> None:
        payload = self._repro()
        result = _solve_checked(build_conflict_graph(payload), payload)
        assert not result.solved, "lab occupies Mon period 1; theory has nowhere else"

    def test_validator_flags_what_the_old_solver_returned(self) -> None:
        """Pre-fix output: lab starts Mon 0 (occupying 0 and 1), theory at Mon 1."""
        violations = validate_solution(
            self._repro(),
            _hand_solution([("lab", 0, 0, "lab-r"), ("thy", 0, 1, "class-r")]),
        )
        assert [(v.kind, v.session_ids, v.slots) for v in violations] == [
            ("COHORT_CLASH", ("lab", "thy"), (SlotId(0, 1),)),
        ]

    def test_theory_moves_past_the_lab_when_it_can(self) -> None:
        payload = self._repro(theory_open=(SlotId(0, 3),))
        result = _solve_checked(build_conflict_graph(payload), payload)
        assert result.solved
        assert result.assignment["lab"] == SlotId(0, 0)
        assert result.occupied["lab"] == (SlotId(0, 0), SlotId(0, 1))
        assert result.assignment["thy"] == SlotId(0, 3)

    def test_multi_period_session_outside_a_lab_block_is_enforced(self) -> None:
        """duration_periods = 2 with no LabBlock used to be placed as 1 period."""
        payload = self._repro(standalone=True)
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

        payload = self._repro(standalone=True, theory_open=(SlotId(0, 3),))
        result = _solve_checked(build_conflict_graph(payload), payload)
        assert result.solved
        assert result.occupied["lab"] == (SlotId(0, 0), SlotId(0, 1))

    def test_room_is_held_for_every_period(self) -> None:
        """No edge, one room: a session in the other's second period has no room."""
        payload = _payload(
            sessions=[
                _session("long", faculty="f1", cohort="c1", duration=2),
                _session("short", faculty="f2", cohort="c2"),
            ],
            rooms=[_room("r1", capacity=30)],
            faculty_availability=[
                _faculty_avail("f1", _only_open(SlotId(0, 0), SlotId(0, 1))),
                _faculty_avail("f2", _only_open(SlotId(0, 1))),
            ],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_session_longer_than_the_rest_of_the_day_is_infeasible(self) -> None:
        payload = _payload(
            sessions=[_session("s1", faculty="f1", duration=2)],
            rooms=[_room("r1", capacity=30)],
            faculty_availability=[_faculty_avail("f1", _only_open(SlotId(0, 9)))],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_second_period_must_be_open_for_the_cohort(self) -> None:
        """Start open, second period pinned for the cohort → that start is out."""
        payload = _payload(
            sessions=[_session("s1", faculty="f1", cohort="c1", duration=2)],
            rooms=[_room("r1", capacity=30)],
            faculty_availability=[
                _faculty_avail("f1", _only_open(SlotId(0, 1), SlotId(0, 3))),
            ],
            pinned_occupancy=[{"day": 0, "period": 3, "faculty_ids": [],
                               "room_ids": [], "cohort_ids": ["c1"]}],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved


class TestLabBlockDeclarations:
    def test_member_duration_must_match_block(self) -> None:
        payload = _payload(
            sessions=[_session("a", faculty="f1", duration=1)],
            lab_blocks=[_lab_block("blk", ["a"], duration=2)],
        )
        with pytest.raises(ValueError, match="duration"):
            backtrack_solve(build_conflict_graph(payload), payload)

    def test_session_in_two_blocks_is_rejected(self) -> None:
        payload = _payload(
            sessions=[_session("a", faculty="f1", duration=2)],
            lab_blocks=[_lab_block("b1", ["a"]), _lab_block("b2", ["a"])],
        )
        with pytest.raises(ValueError, match="more than one lab block"):
            backtrack_solve(build_conflict_graph(payload), payload)

    def test_edge_inside_a_block_makes_it_unplaceable(self) -> None:
        """Members share every slot, so a shared faculty member cannot work."""
        payload = _payload(
            sessions=[
                _session("a", faculty="f1", cohort="ca", duration=2, requires_lab=True),
                _session("b", faculty="f1", cohort="cb", duration=2, requires_lab=True),
            ],
            edges=[_edge("a", "b", "FACULTY")],
            rooms=[_room("l1", is_lab=True), _room("l2", is_lab=True)],
            lab_blocks=[_lab_block("blk", ["a", "b"])],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved

    def test_empty_block_does_not_block_the_search(self) -> None:
        payload = _payload(
            sessions=[_session("a", faculty="f1")],
            lab_blocks=[_lab_block("blk", [])],
        )
        assert _solve_checked(build_conflict_graph(payload), payload).solved


class TestRoomType:
    def test_parse_rooms_maps_is_lab_to_room_type(self) -> None:
        rooms = parse_rooms({"rooms": [_room("lab", is_lab=True), _room("cls")]})
        assert rooms["lab"].room_type == "lab"
        assert rooms["cls"].room_type == "class"

    def test_unknown_room_never_hosts_a_lab(self) -> None:
        """Rooms 605/609 (unsure → unknown) stay unusable for labs."""
        payload = _payload(
            sessions=[_session("s1", faculty="f1", requires_lab=True, cohort_size=10)],
            rooms=[_room("r605", capacity=40)],
        )
        state = _new_state(build_conflict_graph(payload), payload)
        state.rooms = {"r605": Room("r605", "605", 40, "unknown", None)}
        _build_initial_domains(state)
        assert state.domains["s1"] == set()

    def test_unknown_room_can_host_theory(self) -> None:
        payload = _payload(
            sessions=[_session("s1", faculty="f1", cohort_size=10)],
            rooms=[_room("r605", capacity=40)],
        )
        state = _new_state(build_conflict_graph(payload), payload)
        state.rooms = {"r605": Room("r605", "605", 40, "unknown", None)}
        _build_initial_domains(state)
        assert state.domains["s1"]


class TestPinnedSubRoomLocksParent:
    def test_pinned_sub_room_blocks_whole_room(self) -> None:
        payload = _payload(
            sessions=[_session("s1", faculty="f1", cohort_size=50)],
            rooms=[_room("p702", capacity=60),
                   _room("702-A", capacity=20, parent_room_id="p702")],
            faculty_availability=[_faculty_avail("f1", _only_open(SlotId(0, 0)))],
            pinned_occupancy=[{"day": 0, "period": 0, "faculty_ids": [],
                               "room_ids": ["702-A"], "cohort_ids": []}],
        )
        assert not _solve_checked(build_conflict_graph(payload), payload).solved


# ======================================================================
# Solver purity
# ======================================================================


class TestSolverPurityBacktracking:
    """solver/backtracking.py must not import networkx or any forbidden pkg."""

    def test_backtracking_has_no_networkx(self) -> None:
        import importlib

        source = importlib.util.find_spec("solver.backtracking")
        assert source is not None
        assert source.origin is not None
        with open(source.origin, encoding="utf-8") as fh:
            code = fh.read()
        assert "import networkx" not in code
        assert "from networkx" not in code

    def test_backtracking_has_no_web_framework(self) -> None:
        import importlib

        source = importlib.util.find_spec("solver.backtracking")
        assert source is not None
        assert source.origin is not None
        with open(source.origin, encoding="utf-8") as fh:
            code = fh.read()
        for banned in ("flask", "django", "fastapi", "sqlalchemy", "peewee"):
            assert f"import {banned}" not in code
            assert f"from {banned}" not in code
