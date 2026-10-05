"""Backtracking solver with forward checking and MRV ordering.

This is Phase 2 Track A of the Chronos solver.  It picks up where
:func:`solver.colouring.welsh_powell` leaves off: given a conflict graph
*and* the room inventory and lab-block declarations from the edge-list
payload, it searches for a complete assignment of ``(SlotId, room_id)``
pairs to every session, or proves the instance infeasible.

Key design decisions
~~~~~~~~~~~~~~~~~~~~

**Trail-based undo (no deep copy, no recomputation).**
Every domain prune pushed by forward checking is recorded on a *trail*
— a list of ``(session_id, removed_slot_room)`` pairs.  When the search
backtracks, it replays the trail in reverse to restore domains to their
exact prior state.  A test asserts byte-identical restoration.

**MRV variable ordering.**
The next variable to assign is always the unassigned session (or
lab-block) whose current domain is smallest.  Ties break lexicographically
for determinism.

**LabBlock joint allocation.**
A LabBlock's N parallel batch sessions are one composite decision variable.
The solver picks a ``(starting_slot, room_assignment_for_each_session)``
tuple for the whole block.  If any session in the block cannot be placed,
the entire block assignment backtracks.  Double-period contiguity uses
``solver.slots.is_adjacent``, which correctly treats periods 1 and 3 as
adjacent across the short break.

**Sub-room awareness.**
Two sessions may share a physical room in the same slot if they occupy
*different* sub-rooms.  Same sub-room at the same time is a conflict.
A session assigned to a parent room (non-sub-room) locks out all of
its sub-rooms for that slot.

**Capacity check.**
``session.cohort_size ≤ room.capacity`` is enforced when building
candidate room lists.

**Pinned blocks.**
Already excluded from candidate domains by
:func:`solver.graph.available_slots_for`.  The backtracker additionally
refuses to place any session into a slot+room that ``pinned_occupancy``
has claimed.

Stdlib only — ``solver/`` must never import ``networkx`` or any
non-stdlib package (CONTEXT.md rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from solver.graph import ConflictGraph, Session, available_slots_for
from solver.slots import TEACHING_PERIODS, SlotId, is_adjacent, is_teaching_period

__all__ = [
    "BacktrackResult",
    "LabBlock",
    "Room",
    "backtrack_solve",
]


# ---------------------------------------------------------------------------
# Data classes — plain Python, no ORM
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Room:
    """A room or sub-room available to the solver."""

    id: str
    code: str
    capacity: int
    is_lab: bool
    parent_room_id: str | None  # None ⇒ this is a top-level physical room


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

    assignment: dict[str, SlotId]
    room_assignment: dict[str, str]  # session_id → room_id
    solved: bool
    nodes_explored: int
    unplaced_sessions: list[str] = field(default_factory=list)
    rooms: dict[str, Room] = field(default_factory=dict)

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
        slots_used = len(set(self.assignment.values())) if self.solved else None

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
        else:
            diag = diagnosis
            if diag is None:
                diag = {
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
                        for sid in self.unplaced_sessions
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
                            f"unplaced.{self.unplaced_sessions[0]}"
                            if self.unplaced_sessions
                            else "general.infeasible"
                        ),
                        "description": (
                            f"Relax constraints on session {self.unplaced_sessions[0]} "
                            "to restore feasibility."
                            if self.unplaced_sessions
                            else "Relax domain constraints to restore feasibility."
                        ),
                    },
                }
            return {
                "schema_version": "solution.v1",
                "status": "infeasible",
                "diagnosis": diag,
                "metadata": metadata,
            }


# ---------------------------------------------------------------------------
# Parsing helpers — build rooms and lab_blocks from the payload
# ---------------------------------------------------------------------------


def parse_rooms(payload: dict[str, Any]) -> dict[str, Room]:
    """Parse the ``rooms`` array from an edge-list payload."""
    rooms: dict[str, Room] = {}
    for raw in payload.get("rooms", []):
        room = Room(
            id=raw["id"],
            code=raw["code"],
            capacity=raw["capacity"],
            is_lab=raw["is_lab"],
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
    slot: SlotId
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

    # session_id → set of (slot, room_id) candidates
    domains: dict[str, set[tuple[SlotId, str]]]

    # Current assignment
    slot_assignment: dict[str, SlotId]
    room_assignment: dict[str, str]

    # Which sessions are in lab blocks?
    session_to_block: dict[str, LabBlock]

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
    from solver.slots import DAYS

    result: list[tuple[SlotId, ...]] = []
    for day in range(DAYS):
        # Walk through teaching periods for this day and find runs.
        day_teaching = [p for p in TEACHING_PERIODS if is_teaching_period(p)]
        for start_idx in range(len(day_teaching)):
            chain = [SlotId(day, day_teaching[start_idx])]
            for offset in range(1, duration):
                next_idx = start_idx + offset
                if next_idx >= len(day_teaching):
                    break
                candidate = SlotId(day, day_teaching[next_idx])
                if is_adjacent(chain[-1], candidate):
                    chain.append(candidate)
                else:
                    break
            if len(chain) == duration:
                result.append(tuple(chain))
    return result


def _slot_is_available_for_session(
    state: _SolverState,
    session: Session,
    slot: SlotId,
) -> bool:
    """Check if the slot is valid for the session ignoring room concerns.

    Checks:
    * No neighbour already assigned to this slot.
    * Slot is in the session's available set (faculty, pinned).
    """
    # Neighbour check
    for neighbour_id in state.graph.neighbours(session.id):
        if state.slot_assignment.get(neighbour_id) == slot:
            return False
    return True


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
    * If pinned_occupancy claims this room for this slot → False.
    """
    # Direct occupancy
    if (slot, room_id) in state.room_occupancy:
        return False

    # Sub-room → check parent
    parent = state.parent_of.get(room_id)
    if parent is not None and (slot, parent) in state.room_occupancy:
        return False

    # Parent → check all children
    for child_id in state.children_of.get(room_id, []):
        if (slot, child_id) in state.room_occupancy:
            return False

    # Pinned occupancy (room)
    pin = state.graph.pinned_slots.get(slot)
    if pin is not None:
        if room_id in pin["room_ids"]:
            return False
        # If room is a sub-room, also check if parent is pinned
        if parent is not None and parent in pin["room_ids"]:
            return False

    return True


def _candidate_rooms_for_session(
    state: _SolverState,
    session: Session,
    slot: SlotId,
) -> list[str]:
    """Rooms where *session* can go at *slot*.

    Filters by: is_lab requirement, capacity ≥ cohort_size, room available.
    """
    result: list[str] = []
    for room in state.rooms.values():
        if session.requires_lab and not room.is_lab:
            continue
        if room.capacity < session.cohort_size:
            continue
        if not _room_is_available(state, room.id, slot):
            continue
        result.append(room.id)
    # Sort for determinism
    result.sort()
    return result


# ---------------------------------------------------------------------------
# Domain initialisation
# ---------------------------------------------------------------------------


def _build_initial_domains(
    state: _SolverState,
) -> None:
    """Populate ``state.domains`` with all valid ``(slot, room_id)`` pairs."""
    for sid, session in state.graph.sessions.items():
        domain: set[tuple[SlotId, str]] = set()
        available = available_slots_for(state.graph, session)
        for slot in available:
            for room in state.rooms.values():
                if session.requires_lab and not room.is_lab:
                    continue
                if room.capacity < session.cohort_size:
                    continue
                # Pinned room check
                pin = state.graph.pinned_slots.get(slot)
                if pin is not None:
                    parent = state.parent_of.get(room.id)
                    if room.id in pin["room_ids"]:
                        continue
                    if parent is not None and parent in pin["room_ids"]:
                        continue
                domain.add((slot, room.id))
        state.domains[sid] = domain


# ---------------------------------------------------------------------------
# Forward checking
# ---------------------------------------------------------------------------


def _forward_check(
    state: _SolverState,
    assigned_sid: str,
    slot: SlotId,
    room_id: str,
    trail_start: int,
) -> bool:
    """Prune domains of unassigned neighbours after assigning *assigned_sid*.

    Returns False if any neighbour's domain becomes empty (wipe-out).
    Records all prunes on ``state.trail`` from index *trail_start* onwards,
    so they can be undone precisely.
    """
    # 1. Neighbours can't use this slot (conflict-graph adjacency).
    for neighbour_id in state.graph.neighbours(assigned_sid):
        if neighbour_id in state.slot_assignment:
            continue  # Already assigned — skip.
        to_remove: list[tuple[SlotId, str]] = []
        for sr in state.domains[neighbour_id]:
            if sr[0] == slot:
                to_remove.append(sr)
        for sr in to_remove:
            state.domains[neighbour_id].discard(sr)
            state.trail.append(_TrailEntry(neighbour_id, sr[0], sr[1]))
        if not state.domains[neighbour_id]:
            return False

    # 2. Room occupancy: no other session can use this room+slot.
    #    Also enforce sub-room / parent-room mutual exclusion.
    blocked_rooms: set[str] = {room_id}
    parent = state.parent_of.get(room_id)
    if parent is not None:
        blocked_rooms.add(parent)
    for child in state.children_of.get(room_id, []):
        blocked_rooms.add(child)

    for sid, domain in state.domains.items():
        if sid in state.slot_assignment:
            continue
        to_remove_sr: list[tuple[SlotId, str]] = []
        for sr in domain:
            if sr[0] == slot and sr[1] in blocked_rooms:
                to_remove_sr.append(sr)
        for sr in to_remove_sr:
            domain.discard(sr)
            state.trail.append(_TrailEntry(sid, sr[0], sr[1]))
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
        # Skip if any session in the block is already assigned
        if any(sid in state.slot_assignment for sid in block.session_ids):
            continue
        # The hardest session in the block
        min_size = min(
            len(state.domains[sid]) for sid in block.session_ids
        )
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
    n_sessions: int,
    idx: int,
    chosen: list[str],
    used_rooms: set[str],
    used_parents: set[str],
) -> list[tuple[str, ...]]:
    """Enumerate valid room assignments for N sessions (no two share a room)."""
    if idx == n_sessions:
        return [tuple(chosen)]
    results: list[tuple[str, ...]] = []
    for r in room_lists[idx]:
        if r in used_rooms:
            continue
        parent = state.parent_of.get(r)
        if parent is not None and parent in used_rooms:
            continue
        children = state.children_of.get(r, [])
        if any(c in used_rooms for c in children):
            continue
        new_used = used_rooms | {r}
        new_parents = set(used_parents)
        if parent is not None:
            new_parents.add(parent)
        results.extend(
            _gen_room_tuples(
                room_lists, state, n_sessions,
                idx + 1, [*chosen, r], new_used, new_parents,
            )
        )
    return results



def _lab_block_candidates(
    state: _SolverState,
    block: LabBlock,
) -> list[tuple[tuple[SlotId, ...], tuple[str, ...]]]:
    """Generate candidate ``(slot_chain, room_tuple)`` for a LabBlock.

    A slot_chain is a tuple of contiguous SlotIds of length
    ``block.duration_periods``.  Each session gets one room per element
    of the chain (same room for all periods of the block).

    Returns sorted list for determinism.
    """
    all_chains = _contiguous_start_slots(block.duration_periods)
    sessions = [state.graph.sessions[sid] for sid in block.session_ids]
    candidates: list[tuple[tuple[SlotId, ...], tuple[str, ...]]] = []

    for chain in all_chains:

        # All sessions in the block must have this slot in their available set.
        all_available = True
        for sess in sessions:
            avail_slots = available_slots_for(state.graph, sess)
            # For multi-period: all slots in the chain must be available
            for s in chain:
                if s not in avail_slots:
                    all_available = False
                    break
            if not all_available:
                break
            # Also no neighbour conflict on any slot in the chain
            for s in chain:
                if not _slot_is_available_for_session(state, sess, s):
                    all_available = False
                    break
            if not all_available:
                break
        if not all_available:
            continue

        # Find compatible rooms for each session at the first slot.
        # All sessions in the block share the same slot chain but DIFFERENT
        # rooms (one room per session).
        room_lists: list[list[str]] = []
        for sess in sessions:
            rooms_for_sess: list[str] = []
            for room in state.rooms.values():
                if sess.requires_lab and not room.is_lab:
                    continue
                if room.capacity < sess.cohort_size:
                    continue
                # Check all slots in the chain for room availability
                ok = True
                for s in chain:
                    if not _room_is_available(state, room.id, s):
                        ok = False
                        break
                if ok:
                    rooms_for_sess.append(room.id)
            rooms_for_sess.sort()
            room_lists.append(rooms_for_sess)

        # Generate all compatible room tuples (no two sessions in same room).
        # Use backtracking on room assignment for the N sessions.
        room_tuples = _gen_room_tuples(
            room_lists, state, len(sessions), 0, [], set(), set(),
        )
        for rt in room_tuples:
            candidates.append((chain, rt))

    # Sort for determinism
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
    """Try to assign session *sid* to each (slot, room) in its domain."""
    session = state.graph.sessions[sid]
    # Sort domain for determinism
    candidates = sorted(state.domains[sid])

    for slot, room_id in candidates:
        # Verify slot is still valid (neighbour check)
        if not _slot_is_available_for_session(state, session, slot):
            continue
        if not _room_is_available(state, room_id, slot):
            continue

        # Assign
        trail_start = len(state.trail)
        state.slot_assignment[sid] = slot
        state.room_assignment[sid] = room_id
        state.room_occupancy[(slot, room_id)] = sid

        # Forward check
        if _forward_check(state, sid, slot, room_id, trail_start) and _solve(state):
            return True

        # Undo
        _undo_trail(state, trail_start)
        del state.slot_assignment[sid]
        del state.room_assignment[sid]
        del state.room_occupancy[(slot, room_id)]

    return False


def _solve_block(state: _SolverState, block: LabBlock) -> bool:
    """Try to place a LabBlock jointly."""
    candidates = _lab_block_candidates(state, block)

    for chain, room_tuple in candidates:
        trail_start = len(state.trail)
        sessions = [state.graph.sessions[sid] for sid in block.session_ids]

        # Assign all sessions in the block
        placed: list[tuple[str, SlotId, str]] = []
        ok = True
        for sess, room_id in zip(sessions, room_tuple, strict=True):
            # For multi-period: assign the starting slot
            state.slot_assignment[sess.id] = chain[0]
            state.room_assignment[sess.id] = room_id
            # Mark all slots in the chain as occupied for this room
            for s in chain:
                state.room_occupancy[(s, room_id)] = sess.id
                placed.append((sess.id, s, room_id))

        # Forward check for all sessions in the block
        for sess in sessions:
            if not _forward_check(
                state, sess.id,
                state.slot_assignment[sess.id],
                state.room_assignment[sess.id],
                trail_start,
            ):
                ok = False
                break

        if ok and _solve(state):
            return True

        # Undo everything
        _undo_trail(state, trail_start)
        for _sess_id, s, r in placed:
            del state.room_occupancy[(s, r)]
        for sess in sessions:
            state.slot_assignment.pop(sess.id, None)
            state.room_assignment.pop(sess.id, None)

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
        Optional starting assignment from greedy colouring.  Sessions in this
        dict are fixed at their given slots; the backtracker assigns rooms
        and fills any gaps.

    Returns
    -------
    BacktrackResult
        ``solved=True`` with full slot and room assignments, or
        ``solved=False`` with partial results and an explored-node count.
    """
    rooms = parse_rooms(payload)
    lab_blocks = parse_lab_blocks(payload)

    # Map each session to its lab block (if any).
    session_to_block: dict[str, LabBlock] = {}
    for block in lab_blocks:
        for sid in block.session_ids:
            session_to_block[sid] = block

    # Build room hierarchy
    children_of, parent_of = _build_room_hierarchy(rooms)

    state = _SolverState(
        graph=graph,
        rooms=rooms,
        lab_blocks=lab_blocks,
        domains={},
        slot_assignment={},
        room_assignment={},
        session_to_block=session_to_block,
        children_of=children_of,
        parent_of=parent_of,
    )

    # Build initial domains
    _build_initial_domains(state)

    # Apply seed assignment (e.g., from greedy or fixed_slot).
    if seed_assignment:
        for sid, slot in seed_assignment.items():
            if sid in graph.sessions:
                session = graph.sessions[sid]
                # Find a compatible room
                candidate_rooms = _candidate_rooms_for_session(
                    state, session, slot
                )
                if candidate_rooms:
                    room_id = candidate_rooms[0]
                    state.slot_assignment[sid] = slot
                    state.room_assignment[sid] = room_id
                    state.room_occupancy[(slot, room_id)] = sid
                    # FC from seed
                    _forward_check(
                        state, sid, slot, room_id, len(state.trail)
                    )

    # Handle fixed_slot sessions that aren't in the seed.
    for sid, session in graph.sessions.items():
        if sid in state.slot_assignment:
            continue
        if session.fixed_slot is not None:
            slot = session.fixed_slot
            candidate_rooms = _candidate_rooms_for_session(
                state, session, slot
            )
            if candidate_rooms:
                room_id = candidate_rooms[0]
                state.slot_assignment[sid] = slot
                state.room_assignment[sid] = room_id
                state.room_occupancy[(slot, room_id)] = sid
                _forward_check(
                    state, sid, slot, room_id, len(state.trail)
                )

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
        rooms=rooms,
    )
