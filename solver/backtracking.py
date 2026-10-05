"""Backtracking solver with forward checking and MRV ordering.

This is Phase 2 Track A of the Chronos solver.  It picks up where
:func:`solver.colouring.welsh_powell` leaves off: given a conflict graph
*and* the room inventory and lab-block declarations from the edge-list
payload, it searches for a complete assignment of ``(start SlotId, room_id)``
pairs to every session, or proves the instance infeasible.

Key design decisions
~~~~~~~~~~~~~~~~~~~~

**Every period a placement occupies is checked.**
A session of ``duration_periods = n`` placed at a start slot occupies that
slot and the next ``n - 1`` periods in teaching order (``solution_v1``'s
definition of ``period``).  :func:`_occupied_slots` is the *one* place that
turns a placement into the slots it occupies, and every check and prune
uses it: availability, conflict-graph neighbours, room occupancy, forward
checking.  This holds for a session in a LabBlock and equally for a
multi-period session that is *not* in one - such a session is never
silently treated as one period.  Earlier code recorded only a block's first
period, so a theory session could be placed in a lab's second period for the
same cohort and the instance still reported "solved"
(docs/contract-change-proposal-v2.md section 5.1, observation 2).

**A fixed slot restricts where a session starts; it never bypasses a check.**
A ``fixed_slot`` is intersected with faculty availability, pinned occupancy
and every other constraint, through the same domain as any other session.
An empty intersection makes the instance infeasible
(proposal section 5.1, observation 1).

**Trail-based undo (no deep copy, no recomputation).**
Every domain prune pushed by forward checking is recorded on a *trail*
— a list of ``(session_id, start_slot, room_id)`` entries.  When the search
backtracks, it replays the trail in reverse to restore domains to their
exact prior state.  Because a prune removes a whole ``(start, room)`` domain
value whatever period of it overlapped, undo restores exactly the values
that were pruned, for every period.  A test asserts exact restoration.

**MRV variable ordering.**
The next variable to assign is always the unassigned session (or
lab-block) whose current domain is smallest.  Ties break lexicographically
for determinism.

**LabBlock joint allocation.**
A LabBlock's N parallel batch sessions are one composite decision variable.
The solver picks a ``(start_slot, room_for_each_session)`` tuple for the
whole block from the intersection of the members' domains.  If any session
in the block cannot be placed, the entire block assignment backtracks.
Double-period contiguity uses ``solver.slots.is_adjacent``, which correctly
treats periods 1 and 3 as adjacent across the short break.

**Sub-room awareness.**
Two sessions may share a physical room in the same slot if they occupy
*different* sub-rooms.  Same sub-room at the same time is a conflict.
A session assigned to a parent room (non-sub-room) locks out all of
its sub-rooms for that slot, and a sub-room in use locks out its parent.

**Capacity check.**
``session.cohort_size ≤ room.capacity`` is enforced when building domains.

**Room type: three-valued, and only ``lab`` hosts a lab.**
:class:`Room` carries ``room_type`` (``class`` | ``lab`` | ``unknown``), the
same vocabulary as ``ingestion_v1``'s ``rooms[].room_type``, rather than a
bare ``is_lab`` flag.  A session with ``requires_lab`` may only go in a room
whose ``room_type == "lab"``; ``unknown`` never hosts a lab.

*Decision (2026-10-03):* rooms 605 and 609 (``used as = unsure`` in
``classrooms.xlsx``, ingested as ``room_type = unknown``) stay unusable for
labs until someone reclassifies them.  Reclassifying is exactly the
``RECLASSIFY_ROOM`` relaxation in the v2 proposal (section 8.1): a coordinator
action, never a solver guess.  ``edge_list_v1`` itself still carries only
``is_lab: boolean`` - the data layer collapses ``unknown`` to
``is_lab = false`` - so :func:`parse_rooms` maps ``true -> "lab"`` and
``false -> "class"``, and ``unknown`` cannot reach the solver until the edge
list carries ``room_type``.  That is a contract change, not made here.

**Pinned blocks.**
Pinned faculty and cohort slots are excluded from domains through
:func:`solver.graph.slot_is_open`, for every occupied period.  Pinned rooms
are excluded for every occupied period, including a pinned parent locking
its sub-rooms and a pinned sub-room locking its parent.

**Infeasible results carry a PLACEHOLDER diagnosis.**
See :func:`_placeholder_diagnosis`.  It is not a minimal unsatisfiable
subset; ``solver/mus.py`` does not exist yet.

Stdlib only — ``solver/`` must never import ``networkx`` or any
non-stdlib package (CONTEXT.md rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from solver.graph import ConflictGraph, Session, available_slots_for, slot_is_open
from solver.slots import DAYS, TEACHING_PERIODS, SlotId, is_adjacent

__all__ = [
    "BacktrackResult",
    "LabBlock",
    "Room",
    "RoomType",
    "backtrack_solve",
    "parse_lab_blocks",
    "parse_rooms",
]


# ---------------------------------------------------------------------------
# Data classes — plain Python, no ORM
# ---------------------------------------------------------------------------

RoomType = Literal["class", "lab", "unknown"]


@dataclass(frozen=True, slots=True)
class Room:
    """A room or sub-room available to the solver."""

    id: str
    code: str
    capacity: int
    room_type: RoomType
    parent_room_id: str | None  # None ⇒ this is a top-level physical room

    @property
    def hosts_labs(self) -> bool:
        """Only a room positively classified as a lab may host a lab session."""
        return self.room_type == "lab"


@dataclass(frozen=True, slots=True)
class LabBlock:
    """A group of sessions that must be placed jointly.

    All sessions in the block start in the same slot, run over the same
    contiguous periods, and each session gets its own room/sub-room.
    """

    id: str
    session_ids: tuple[str, ...]
    duration_periods: int
    must_be_contiguous: bool  # always True in v1


@dataclass(slots=True)
class BacktrackResult:
    """Output of :func:`backtrack_solve`."""

    assignment: dict[str, SlotId]  # session_id → START slot
    room_assignment: dict[str, str]  # session_id → room_id
    solved: bool
    nodes_explored: int
    unplaced_sessions: list[str] = field(default_factory=list)
    rooms: dict[str, Room] = field(default_factory=dict)
    # session_id → every slot the placement occupies, in teaching order
    occupied: dict[str, tuple[SlotId, ...]] = field(default_factory=dict)

    def to_solution_dict(
        self,
        *,
        total_sessions: int | None = None,
        runtime_ms: float = 0.0,
        quality: dict[str, Any] | None = None,
        displaced: list[str] | None = None,
        diagnosis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Serialise this result into a dict matching ``contracts/solution_v1.schema.json``."""
        tot = (
            total_sessions
            if total_sessions is not None
            else (len(self.assignment) + len(self.unplaced_sessions))
        )
        slots_used = (
            len({s for slots in self.occupied.values() for s in slots})
            if self.solved
            else None
        )

        metadata: dict[str, Any] = {
            "algorithm": "backtracking(forward-checking, mrv)",
            "runtime_ms": max(0.0, float(runtime_ms)),
            "sessions_total": tot,
            "sessions_assigned": len(self.assignment),
            "slots_used": slots_used,
            "backtracks": self.nodes_explored,
        }

        if self.solved:
            items: list[dict[str, Any]] = []
            for sid, slot in sorted(self.assignment.items()):
                r_id = self.room_assignment.get(sid, "")
                parent_id: str = r_id
                sub_id: str | None = None
                if r_id in self.rooms and self.rooms[r_id].parent_room_id is not None:
                    parent_id = self.rooms[r_id].parent_room_id or r_id
                    sub_id = r_id
                items.append({
                    "session_id": sid,
                    "day": slot.day,
                    "period": slot.period,
                    "room_id": parent_id,
                    "sub_room_id": sub_id,
                })

            # !!! PLACEHOLDER QUALITY — NOT A SCORE !!!
            # No scoring has run: solver/scoring.py does not exist yet. 100.0 with
            # an empty breakdown is a hardcoded stand-in, NOT a measured perfect
            # score. solution_v1 requires `quality.score` to be a number when
            # status is "solved" and has no way to say "not evaluated", so the
            # stand-in cannot be removed under v1. solution.v2 (proposal change 6)
            # adds per-rule status and rules_version; Phase 3 scoring replaces this.
            qual = (
                quality
                if quality is not None
                else {"score": 100.0, "breakdown": []}
            )
            disp = displaced if displaced is not None else []
            return {
                "schema_version": "solution.v1",
                "status": "solved",
                "assignment": items,
                "quality": qual,
                "displaced": disp,
                "metadata": metadata,
            }
        diag = diagnosis if diagnosis is not None else _placeholder_diagnosis(
            self.unplaced_sessions
        )
        return {
            "schema_version": "solution.v1",
            "status": "infeasible",
            "diagnosis": diag,
            "metadata": metadata,
        }


def _placeholder_diagnosis(unplaced: list[str]) -> dict[str, Any]:
    """!!! PLACEHOLDER — this is NOT infeasibility diagnosis. !!!

    The search proved the instance infeasible by exhausting it, but nothing
    extracted *why*.  This lists every session left unplaced as an
    ``unplaced.<id>`` / ``UNSATISFIABLE_DOMAIN`` entry and suggests "Relax
    constraints on session X".  That is **not** a minimal unsatisfiable subset:
    the entries are search outcomes, not constraints, they are not minimal, and
    the "relaxation" is not a concrete change.  Because the search unwinds
    completely before returning, the list is normally every session.

    The shape is kept as-is on purpose so ``solution_v1`` consumers keep
    working.  ``solution.v2`` (proposal section 5.3) migrates it to
    ``method = "search_exhaustion"`` with an empty set and no relaxation; the
    real diagnosis comes from ``solver/mus.py`` (ROADMAP Phase 4).
    """
    return {
        "minimal_conflicting_set": [
            {
                "constraint_id": f"unplaced.{sid}",
                "kind": "UNSATISFIABLE_DOMAIN",
                "description": (
                    f"Session {sid} could not be placed in any "
                    "conflict-free slot and room."
                ),
                "entity_ids": [sid],
            }
            for sid in unplaced
        ]
        or [
            {
                "constraint_id": "general.infeasible",
                "kind": "INFEASIBLE_INSTANCE",
                "description": (
                    "No valid timetable exists satisfying all "
                    "domain and conflict constraints."
                ),
                "entity_ids": [],
            }
        ],
        "suggested_relaxation": {
            "constraint_id": (
                f"unplaced.{unplaced[0]}" if unplaced else "general.infeasible"
            ),
            "description": (
                f"Relax constraints on session {unplaced[0]} "
                "to restore feasibility."
                if unplaced
                else "Relax domain constraints to restore feasibility."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Parsing helpers — build rooms and lab_blocks from the payload
# ---------------------------------------------------------------------------


def parse_rooms(payload: dict[str, Any]) -> dict[str, Room]:
    """Parse the ``rooms`` array from an edge-list payload.

    ``edge_list_v1`` carries ``is_lab: boolean``, so ``room_type`` is ``"lab"``
    or ``"class"`` here; see the module docstring for why ``"unknown"`` cannot
    arrive through v1.
    """
    rooms: dict[str, Room] = {}
    for raw in payload.get("rooms", []):
        room = Room(
            id=raw["id"],
            code=raw["code"],
            capacity=raw["capacity"],
            room_type="lab" if raw["is_lab"] else "class",
            parent_room_id=raw["parent_room_id"],
        )
        rooms[room.id] = room
    return rooms


def parse_lab_blocks(payload: dict[str, Any]) -> list[LabBlock]:
    """Parse the ``lab_blocks`` array from an edge-list payload."""
    blocks: list[LabBlock] = []
    for raw in payload.get("lab_blocks", []):
        blocks.append(
            LabBlock(
                id=raw["id"],
                session_ids=tuple(raw["session_ids"]),
                duration_periods=raw["duration_periods"],
                must_be_contiguous=raw["must_be_contiguous"],
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# Trail entry — the atom of undo
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _TrailEntry:
    """One domain value removed by forward checking."""

    session_id: str
    slot: SlotId  # the START slot of the removed (start, room) value
    room_id: str


# ---------------------------------------------------------------------------
# Internal state for backtracking
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SolverState:
    """Mutable state that the backtracker operates on."""

    graph: ConflictGraph
    rooms: dict[str, Room]
    lab_blocks: list[LabBlock]

    # session_id → set of (start slot, room_id) candidates
    domains: dict[str, set[tuple[SlotId, str]]]

    # Current assignment
    slot_assignment: dict[str, SlotId]  # start slot
    room_assignment: dict[str, str]

    # Which sessions are in lab blocks?
    session_to_block: dict[str, LabBlock]

    # (start, duration) → occupied slots, for every start that has a full
    # teaching-adjacent chain.  Read only through _occupied_slots.
    chains: dict[tuple[SlotId, int], tuple[SlotId, ...]] = field(default_factory=dict)

    # session_id → every slot an assigned session occupies
    occupied: dict[str, tuple[SlotId, ...]] = field(default_factory=dict)

    # Room occupancy: (slot, room_id) → session_id that is placed there
    room_occupancy: dict[tuple[SlotId, str], str] = field(default_factory=dict)

    # Sub-room bookkeeping: parent_room_id → dict of children room_ids
    children_of: dict[str, list[str]] = field(default_factory=dict)
    # room_id → parent_room_id (for sub-rooms only)
    parent_of: dict[str, str] = field(default_factory=dict)

    nodes_explored: int = 0
    trail: list[_TrailEntry] = field(default_factory=list)


def _build_room_hierarchy(rooms: dict[str, Room]) -> tuple[
    dict[str, list[str]],  # children_of
    dict[str, str],  # parent_of
]:
    """Build parent→children and child→parent mappings."""
    children_of: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    for room in rooms.values():
        if room.parent_room_id is not None:
            children_of.setdefault(room.parent_room_id, []).append(room.id)
            parent_of[room.id] = room.parent_room_id
    return children_of, parent_of


def _contiguous_start_slots(
    duration: int,
) -> list[tuple[SlotId, ...]]:
    """Return all valid chains of contiguous teaching-period slots.

    A chain of length *duration* is valid when every consecutive pair
    satisfies ``is_adjacent``.  This correctly handles the short-break span
    (period 1 → period 3) and blocks spanning lunch.
    """
    result: list[tuple[SlotId, ...]] = []
    for day in range(DAYS):
        for start_idx in range(len(TEACHING_PERIODS)):
            chain = [SlotId(day, TEACHING_PERIODS[start_idx])]
            for offset in range(1, duration):
                next_idx = start_idx + offset
                if next_idx >= len(TEACHING_PERIODS):
                    break
                candidate = SlotId(day, TEACHING_PERIODS[next_idx])
                if is_adjacent(chain[-1], candidate):
                    chain.append(candidate)
                else:
                    break
            if len(chain) == duration:
                result.append(tuple(chain))
    return result


def _new_state(graph: ConflictGraph, payload: dict[str, Any]) -> _SolverState:
    """Build solver state from a graph and its edge-list payload.

    Raises:
        ValueError: if a lab block names an unknown session, a session sits in
            two blocks, or a member's ``duration_periods`` disagrees with its
            block's - the instance would be ambiguous about what to occupy.
    """
    rooms = parse_rooms(payload)
    lab_blocks = parse_lab_blocks(payload)

    session_to_block: dict[str, LabBlock] = {}
    for block in lab_blocks:
        for sid in block.session_ids:
            if sid not in graph.sessions:
                raise ValueError(f"lab block {block.id!r} names unknown session {sid!r}")
            if sid in session_to_block:
                raise ValueError(f"session {sid!r} is in more than one lab block")
            if graph.sessions[sid].duration_periods != block.duration_periods:
                raise ValueError(
                    f"lab block {block.id!r} has duration {block.duration_periods} but "
                    f"member {sid!r} has duration {graph.sessions[sid].duration_periods}"
                )
            session_to_block[sid] = block

    children_of, parent_of = _build_room_hierarchy(rooms)

    chains: dict[tuple[SlotId, int], tuple[SlotId, ...]] = {}
    for duration in {s.duration_periods for s in graph.sessions.values()}:
        for chain in _contiguous_start_slots(duration):
            chains[(chain[0], duration)] = chain

    return _SolverState(
        graph=graph,
        rooms=rooms,
        lab_blocks=lab_blocks,
        domains={},
        slot_assignment={},
        room_assignment={},
        session_to_block=session_to_block,
        chains=chains,
        children_of=children_of,
        parent_of=parent_of,
    )


# ---------------------------------------------------------------------------
# Occupancy — the ONE helper every check and prune goes through
# ---------------------------------------------------------------------------


def _occupied_slots(
    state: _SolverState,
    sid: str,
    start: SlotId,
) -> tuple[SlotId, ...] | None:
    """Every slot session *sid* occupies when it starts at *start*.

    ``duration_periods`` teaching-adjacent slots from *start*, in teaching
    order; ``None`` when the day has too few periods left.  Every check that
    asks "when is this session in the room / with this cohort / with this
    teacher" must call this rather than look at *start* alone.
    """
    return state.chains.get((start, state.graph.sessions[sid].duration_periods))


def _overlaps(
    state: _SolverState,
    sid: str,
    start: SlotId,
    slots: set[SlotId],
) -> bool:
    """True when *sid* placed at *start* occupies any slot in *slots*."""
    occupied = _occupied_slots(state, sid, start)
    return occupied is not None and not slots.isdisjoint(occupied)


def _room_suits(room: Room, session: Session) -> bool:
    """Room type and capacity — the slot-independent room constraints."""
    if session.requires_lab and not room.hosts_labs:
        return False
    return room.capacity >= session.cohort_size


def _room_is_pinned(state: _SolverState, room_id: str, slot: SlotId) -> bool:
    """True when ``pinned_occupancy`` holds this room, its parent, or one of
    its sub-rooms at *slot*."""
    pin = state.graph.pinned_slots.get(slot)
    if pin is None:
        return False
    held = pin["room_ids"]
    if room_id in held:
        return True
    parent = state.parent_of.get(room_id)
    if parent is not None and parent in held:
        return True
    return any(child in held for child in state.children_of.get(room_id, []))


def _room_is_available(
    state: _SolverState,
    room_id: str,
    slot: SlotId,
) -> bool:
    """Check if a room (or sub-room) is free at the given slot.

    Rules:
    * If (slot, room_id) is already occupied → False.
    * If room_id is a sub-room and the parent room is occupied → False.
    * If room_id is a parent room and any of its sub-rooms is occupied → False.
    * If pinned_occupancy claims this room, its parent or a sub-room → False.
    """
    if (slot, room_id) in state.room_occupancy:
        return False
    parent = state.parent_of.get(room_id)
    if parent is not None and (slot, parent) in state.room_occupancy:
        return False
    for child_id in state.children_of.get(room_id, []):
        if (slot, child_id) in state.room_occupancy:
            return False
    return not _room_is_pinned(state, room_id, slot)


def _clashes_with_assigned(
    state: _SolverState,
    sid: str,
    slots: tuple[SlotId, ...],
) -> bool:
    """True when an already-assigned neighbour of *sid* occupies any of *slots*."""
    wanted = set(slots)
    for neighbour_id in state.graph.neighbours(sid):
        occupied = state.occupied.get(neighbour_id)
        if occupied is not None and not wanted.isdisjoint(occupied):
            return True
    return False


def _placement_ok(
    state: _SolverState,
    sid: str,
    start: SlotId,
    room_id: str,
) -> tuple[SlotId, ...] | None:
    """The occupied slots if *sid* can go at (*start*, *room_id*) now, else None.

    Forward checking should already have pruned every inconsistent value; this
    re-checks every occupied period against the current assignment so that a
    pruning gap can never turn into a reported conflict.
    """
    slots = _occupied_slots(state, sid, start)
    if slots is None:
        return None
    if _clashes_with_assigned(state, sid, slots):
        return None
    if not all(_room_is_available(state, room_id, s) for s in slots):
        return None
    return slots


def _assign(
    state: _SolverState,
    sid: str,
    start: SlotId,
    room_id: str,
    slots: tuple[SlotId, ...],
) -> None:
    state.slot_assignment[sid] = start
    state.room_assignment[sid] = room_id
    state.occupied[sid] = slots
    for s in slots:
        state.room_occupancy[(s, room_id)] = sid


def _unassign(state: _SolverState, sid: str) -> None:
    room_id = state.room_assignment.pop(sid)
    for s in state.occupied.pop(sid):
        del state.room_occupancy[(s, room_id)]
    del state.slot_assignment[sid]


# ---------------------------------------------------------------------------
# Domain initialisation
# ---------------------------------------------------------------------------


def _build_initial_domains(
    state: _SolverState,
) -> None:
    """Populate ``state.domains`` with all valid ``(start slot, room_id)`` pairs.

    A start is valid only when every slot it occupies is open for the
    session's faculty and cohort, and a room only when it suits the session
    and no occupied slot pins it.  ``available_slots_for`` intersects a
    ``fixed_slot`` with availability, so a fixed session's domain holds at most
    its fixed start.
    """
    graph = state.graph
    for sid, session in graph.sessions.items():
        domain: set[tuple[SlotId, str]] = set()
        for start in available_slots_for(graph, session):
            slots = _occupied_slots(state, sid, start)
            if slots is None:
                continue
            if not all(slot_is_open(graph, session, s) for s in slots):
                continue
            for room in state.rooms.values():
                if not _room_suits(room, session):
                    continue
                if any(_room_is_pinned(state, room.id, s) for s in slots):
                    continue
                domain.add((start, room.id))
        state.domains[sid] = domain


# ---------------------------------------------------------------------------
# Forward checking
# ---------------------------------------------------------------------------


def _forward_check(state: _SolverState, assigned_sid: str) -> bool:
    """Prune domains of unassigned sessions after assigning *assigned_sid*.

    Uses every slot *assigned_sid* occupies, and every slot each candidate
    value would occupy: a value is pruned when the two overlap in **any**
    period.  Returns False if any domain becomes empty (wipe-out).  Records
    every prune on ``state.trail`` so the caller can undo exactly.
    """
    slots = set(state.occupied[assigned_sid])
    room_id = state.room_assignment[assigned_sid]

    # 1. Neighbours can't overlap these slots (conflict-graph adjacency).
    for neighbour_id in state.graph.neighbours(assigned_sid):
        if neighbour_id in state.slot_assignment:
            continue  # Already assigned — skip.
        domain = state.domains[neighbour_id]
        to_remove = [v for v in domain if _overlaps(state, neighbour_id, v[0], slots)]
        for v in to_remove:
            domain.discard(v)
            state.trail.append(_TrailEntry(neighbour_id, v[0], v[1]))
        if not domain:
            return False

    # 2. Room occupancy: no other session can use this room (or its parent or
    #    its sub-rooms) in any overlapping slot.
    blocked_rooms: set[str] = {room_id}
    parent = state.parent_of.get(room_id)
    if parent is not None:
        blocked_rooms.add(parent)
    blocked_rooms.update(state.children_of.get(room_id, []))

    for sid, domain in state.domains.items():
        if sid in state.slot_assignment:
            continue
        to_remove = [
            v for v in domain
            if v[1] in blocked_rooms and _overlaps(state, sid, v[0], slots)
        ]
        for v in to_remove:
            domain.discard(v)
            state.trail.append(_TrailEntry(sid, v[0], v[1]))
        if not domain:
            return False

    return True


def _undo_trail(state: _SolverState, trail_start: int) -> None:
    """Restore all domain values pruned from trail_start onwards."""
    while len(state.trail) > trail_start:
        entry = state.trail.pop()
        state.domains[entry.session_id].add((entry.slot, entry.room_id))


# ---------------------------------------------------------------------------
# MRV variable selection
# ---------------------------------------------------------------------------


def _select_mrv(state: _SolverState) -> str | None:
    """Pick the unassigned non-lab-block session with smallest domain.

    Lab-block member sessions are handled via their parent block.
    Returns None when all sessions are assigned.
    """
    best_sid: str | None = None
    best_size = float("inf")

    for sid in state.graph.sessions:
        if sid in state.slot_assignment:
            continue
        if sid in state.session_to_block:
            continue  # Handled by block selection
        size = len(state.domains[sid])
        if size < best_size or (size == best_size and (
            best_sid is None or sid < best_sid
        )):
            best_size = size
            best_sid = sid

    return best_sid


def _select_mrv_block(state: _SolverState) -> LabBlock | None:
    """Pick the unassigned lab block whose 'hardest' session has the smallest
    domain.
    """
    best_block: LabBlock | None = None
    best_min_size = float("inf")
    best_block_id = ""

    for block in state.lab_blocks:
        # Skip an empty block, or one already placed
        if not block.session_ids or any(
            sid in state.slot_assignment for sid in block.session_ids
        ):
            continue
        # The hardest session in the block
        min_size = min(len(state.domains[sid]) for sid in block.session_ids)
        if min_size < best_min_size or (
            min_size == best_min_size and block.id < best_block_id
        ):
            best_min_size = min_size
            best_block = block
            best_block_id = block.id

    return best_block


# ---------------------------------------------------------------------------
# Lab-block placement
# ---------------------------------------------------------------------------


def _gen_room_tuples(
    room_lists: list[list[str]],
    state: _SolverState,
    idx: int = 0,
    chosen: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    """Enumerate room assignments for the block's sessions, in order.

    No two sessions share a room, and no session takes a whole room while
    another takes one of its sub-rooms.
    """
    if idx == len(room_lists):
        return [chosen]
    results: list[tuple[str, ...]] = []
    for r in room_lists[idx]:
        if any(
            r == c or state.parent_of.get(r) == c or state.parent_of.get(c) == r
            for c in chosen
        ):
            continue
        results.extend(_gen_room_tuples(room_lists, state, idx + 1, (*chosen, r)))
    return results


def _lab_block_candidates(
    state: _SolverState,
    block: LabBlock,
) -> list[tuple[SlotId, tuple[str, ...]]]:
    """Generate candidate ``(start_slot, room_tuple)`` for a LabBlock.

    Every member starts at the same slot and occupies the same chain, so a
    conflict edge between two members makes the block unplaceable.  Starts
    come from the intersection of the members' current domains; each member's
    rooms are those its domain still allows at that start and that pass
    :func:`_placement_ok` over every occupied period.

    Returns a sorted list for determinism.
    """
    members = block.session_ids
    if not members:
        return []
    for i, a in enumerate(members):
        if any(b in state.graph.adjacency[a] for b in members[i + 1:]):
            return []

    common_starts = set.intersection(
        *({start for start, _ in state.domains[sid]} for sid in members)
    )

    candidates: list[tuple[SlotId, tuple[str, ...]]] = []
    for start in sorted(common_starts):
        room_lists: list[list[str]] = []
        for sid in members:
            rooms = sorted(
                r for s, r in state.domains[sid]
                if s == start and _placement_ok(state, sid, start, r) is not None
            )
            if not rooms:
                break
            room_lists.append(rooms)
        else:
            for rt in _gen_room_tuples(room_lists, state):
                candidates.append((start, rt))

    candidates.sort()
    return candidates


# ---------------------------------------------------------------------------
# Core recursive backtracking
# ---------------------------------------------------------------------------


def _solve(state: _SolverState) -> bool:
    """Recursive backtracking with forward checking.

    Returns True if a complete assignment was found.
    """
    state.nodes_explored += 1

    # 1. Try to place the next lab block (prioritise blocks — they are harder)
    block = _select_mrv_block(state)
    if block is not None:
        return _solve_block(state, block)

    # 2. Try to place the next individual session
    sid = _select_mrv(state)
    if sid is None:
        # All sessions assigned — success!
        return True

    return _solve_session(state, sid)


def _solve_session(state: _SolverState, sid: str) -> bool:
    """Try to assign session *sid* to each (start, room) in its domain."""
    for start, room_id in sorted(state.domains[sid]):
        slots = _placement_ok(state, sid, start, room_id)
        if slots is None:
            continue

        trail_start = len(state.trail)
        _assign(state, sid, start, room_id, slots)

        if _forward_check(state, sid) and _solve(state):
            return True

        _undo_trail(state, trail_start)
        _unassign(state, sid)

    return False


def _solve_block(state: _SolverState, block: LabBlock) -> bool:
    """Try to place a LabBlock jointly."""
    for start, room_tuple in _lab_block_candidates(state, block):
        trail_start = len(state.trail)

        for sid, room_id in zip(block.session_ids, room_tuple, strict=True):
            slots = _occupied_slots(state, sid, start)
            assert slots is not None  # start came from the member's domain
            _assign(state, sid, start, room_id, slots)

        if all(_forward_check(state, sid) for sid in block.session_ids) and _solve(state):
            return True

        _undo_trail(state, trail_start)
        for sid in block.session_ids:
            _unassign(state, sid)

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def backtrack_solve(
    graph: ConflictGraph,
    payload: dict[str, Any],
    *,
    seed_assignment: dict[str, SlotId] | None = None,
) -> BacktrackResult:
    """Solve the timetable by backtracking with forward checking and MRV.

    Parameters
    ----------
    graph:
        A :class:`~solver.graph.ConflictGraph` built by
        :func:`~solver.graph.build_conflict_graph`.
    payload:
        The full edge-list payload dict (for rooms and lab_blocks).
    seed_assignment:
        Optional starting slots, e.g. from greedy colouring.  A seeded session
        may only start at its seed slot - its domain is restricted to it, like
        a ``fixed_slot`` - and is checked like any other placement.  Ids not in
        the graph are ignored.

    Returns
    -------
    BacktrackResult
        ``solved=True`` with full slot and room assignments, or
        ``solved=False`` with an explored-node count.  The search unwinds
        fully on failure, so an infeasible result normally has no sessions
        assigned.

    Raises
    ------
    ValueError
        On an inconsistent lab-block declaration (see :func:`_new_state`).
    """
    state = _new_state(graph, payload)
    _build_initial_domains(state)

    if seed_assignment:
        for sid, slot in seed_assignment.items():
            if sid in state.domains:
                state.domains[sid] = {v for v in state.domains[sid] if v[0] == slot}

    solved = _solve(state)

    unplaced = [
        sid for sid in graph.sessions if sid not in state.slot_assignment
    ]

    return BacktrackResult(
        assignment=dict(state.slot_assignment),
        room_assignment=dict(state.room_assignment),
        solved=solved,
        nodes_explored=state.nodes_explored,
        unplaced_sessions=unplaced,
        rooms=state.rooms,
        occupied=dict(state.occupied),
    )
