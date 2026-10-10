"""Welsh-Powell greedy graph colouring for the Chronos solver.

Colours are ``SlotId`` values — each colour is the (day, period) teaching slot
a session **starts** in.  Welsh-Powell orders vertices by descending degree,
then assigns the smallest feasible colour to each vertex in that order.

What "feasible" means
~~~~~~~~~~~~~~~~~~~~~

A colour is feasible for a session only if every hard constraint that does not
involve rooms holds - the same set :func:`solver.validate.validate_slot_placements`
checks:

* **Every occupied period, not just the start.**  A session of
  ``duration_periods = n`` starting at a slot occupies that slot and the next
  ``n - 1`` teaching periods (:func:`solver.slots.is_adjacent`, so a double may
  span the short break or lunch).  A start whose chain would run off the end of
  the day is not a colour at all.  Every occupied period must be open for the
  session's faculty and cohort (:func:`solver.graph.slot_is_open`), and must be
  disjoint from every period an already-coloured neighbour occupies.
* **Lab blocks are one unit.**  The members of a lab block are coloured
  together, with one shared start; the block's degree is the number of
  distinct sessions outside the block that any member conflicts with.  A block
  with a conflict edge *between* two members can never be placed (members
  share every slot), so all its members go to ``unplaced``.
* **A fixed slot restricts the start, it never bypasses a check.**  A
  ``fixed_slot`` session (or a block with a fixed member) is coloured before
  the free ones, as before, but only at its fixed start and only if that start
  passes every check above.  If it does not, the session is unplaced - the
  instance is infeasible as declared, which is the honest answer.

Earlier versions compared start slots only, coloured lab-block members
independently, and pre-assigned fixed slots unconditionally; on the property
generator in ``solver/tests/test_property_solved_is_valid.py`` 338 of 394
complete colourings broke a hard constraint.

What it does **not** do: rooms.  Colouring assigns no rooms, so room capacity,
room type and room occupancy are not checked here (``ROOM`` conflict edges, if
the data layer emitted them, are).  A complete colouring is a valid *time*
assignment; :mod:`solver.backtracking` is what assigns rooms.

Returns ``(assignment, unplaced)`` where:

* ``assignment``: ``dict[str, SlotId]`` — session id → assigned **start** slot,
* ``unplaced``:   ``list[str]``        — session ids that could not be placed
  (empty when the greedy succeeds on a feasible instance).

Stdlib only — ``solver/`` must never import ``networkx`` or anything
outside the stdlib (CONTEXT.md rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass

from solver.graph import ConflictGraph, Session, available_slots_for, slot_is_open
from solver.slots import TEACHING_PERIODS, SlotId

__all__ = [
    "welsh_powell",
]

#: Position of each teaching period in teaching order.
_POSITION: dict[int, int] = {period: i for i, period in enumerate(TEACHING_PERIODS)}


@dataclass(frozen=True, slots=True)
class _Unit:
    """What gets one colour: a single session, or every member of a lab block."""

    members: tuple[str, ...]
    fixed: bool
    degree: int
    tie_break: str


def _chain(start: SlotId, duration: int) -> tuple[SlotId, ...] | None:
    """The *duration* teaching-adjacent slots from *start*, or None if the day
    runs out first.  Consecutive teaching periods are adjacent by definition
    (:func:`solver.slots.is_adjacent` measures position in teaching order)."""
    first = _POSITION.get(start.period)
    if first is None or first + duration > len(TEACHING_PERIODS):
        return None
    return tuple(
        SlotId(start.day, TEACHING_PERIODS[i]) for i in range(first, first + duration)
    )


def _units(graph: ConflictGraph) -> list[_Unit]:
    """Lab blocks and free-standing sessions, in Welsh-Powell colouring order.

    Order: fixed units first, then descending degree, then the smallest member
    id - deterministic, and identical to the classic (-degree, id) order on a
    graph with no blocks and no fixed slots.
    """
    in_block = {sid for members in graph.lab_blocks.values() for sid in members}
    groups = [members for members in graph.lab_blocks.values() if members]
    groups += [(sid,) for sid in graph.sessions if sid not in in_block]

    units: list[_Unit] = []
    for members in groups:
        inside = set(members)
        outside = set().union(*(graph.neighbours(sid) for sid in members)) - inside
        units.append(
            _Unit(
                members=members,
                fixed=any(graph.sessions[sid].fixed_slot is not None for sid in members),
                degree=len(outside),
                tie_break=min(members),
            )
        )
    units.sort(key=lambda u: (not u.fixed, -u.degree, u.tie_break))
    return units


def _occupancy_if_open(
    graph: ConflictGraph,
    session: Session,
    start: SlotId,
) -> tuple[SlotId, ...] | None:
    """Slots *session* occupies from *start*, if every one is open for it."""
    slots = _chain(start, session.duration_periods)
    if slots is None:
        return None
    if not all(slot_is_open(graph, session, slot) for slot in slots):
        return None
    return slots


def _try_start(
    graph: ConflictGraph,
    unit: _Unit,
    start: SlotId,
    occupied: dict[str, tuple[SlotId, ...]],
) -> dict[str, tuple[SlotId, ...]] | None:
    """Every member's occupied slots if the whole unit can start at *start*."""
    placed: dict[str, tuple[SlotId, ...]] = {}
    for sid in unit.members:
        slots = _occupancy_if_open(graph, graph.sessions[sid], start)
        if slots is None:
            return None
        wanted = set(slots)
        for neighbour in graph.neighbours(sid):
            taken = occupied.get(neighbour)
            if taken is not None and not wanted.isdisjoint(taken):
                return None
        placed[sid] = slots
    return placed


def welsh_powell(
    graph: ConflictGraph,
) -> tuple[dict[str, SlotId], list[str]]:
    """Greedy colour the conflict graph using Welsh-Powell ordering.

    Parameters
    ----------
    graph:
        A :class:`~solver.graph.ConflictGraph` built by
        :func:`~solver.graph.build_conflict_graph`.

    Returns
    -------
    (assignment, unplaced)
        *assignment* maps each successfully coloured session id to its start
        ``SlotId``.  *unplaced* lists session ids that received no colour
        because no start passed every check (see the module docstring): every
        candidate was blocked by an already-coloured neighbour, by faculty or
        pinned unavailability in any occupied period, by the end of the day,
        or by a fixed slot that fails those checks.
    """
    assignment: dict[str, SlotId] = {}
    occupied: dict[str, tuple[SlotId, ...]] = {}
    unplaced: list[str] = []

    for unit in _units(graph):
        members = set(unit.members)
        # Members of one unit share every slot, so an edge between two of them
        # can never be satisfied.
        internal_clash = any(
            graph.neighbours(sid) & members for sid in unit.members
        )

        placed = None
        if not internal_clash:
            # A start must be a colour for every member: in its availability
            # (which already intersects fixed_slot) for each one.
            candidates = set(available_slots_for(graph, graph.sessions[unit.members[0]]))
            for sid in unit.members[1:]:
                candidates &= set(available_slots_for(graph, graph.sessions[sid]))
            for start in sorted(candidates):
                placed = _try_start(graph, unit, start, occupied)
                if placed is not None:
                    for sid, slots in placed.items():
                        assignment[sid] = start
                        occupied[sid] = slots
                    break

        if placed is None:
            unplaced.extend(unit.members)

    return assignment, unplaced
