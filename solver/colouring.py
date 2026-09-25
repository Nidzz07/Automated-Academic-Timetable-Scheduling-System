"""Welsh-Powell greedy graph colouring for the Chronos solver.

Colours are ``SlotId`` values — each colour is a (day, period) teaching slot.
Welsh-Powell orders vertices by descending degree, then assigns the smallest
feasible colour to each vertex in that order.

This implementation adds **faculty availability** as an additional constraint
on which colour a vertex may take.  A slot that falls in a faculty member's
unavailable set is removed from that vertex's candidate colours *before* the
adjacency check, so faculty availability is a *domain restriction*, not a
graph edge.

Pinned occupancy (MDM, HSS, LLC, breaks, exams) further restricts domains
through :func:`solver.graph.available_slots_for`.

A ``fixed_slot`` on a session pre-assigns its colour and makes it non-
negotiable: the session keeps that slot regardless of conflicts (the caller
is responsible for ensuring the pre-assignment is feasible).

Returns ``(assignment, unplaced)`` where:

* ``assignment``: ``dict[str, SlotId]`` — session id → assigned slot,
* ``unplaced``:   ``list[str]``        — session ids that could not be placed
  (empty when the greedy succeeds on a feasible instance).

Stdlib only — ``solver/`` must never import ``networkx`` or anything
outside the stdlib (CONTEXT.md rule 3).
"""

from __future__ import annotations

from solver.graph import ConflictGraph, available_slots_for
from solver.slots import SlotId

__all__ = [
    "welsh_powell",
]


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
        *assignment* maps each successfully coloured session id to a
        ``SlotId``.  *unplaced* lists session ids that received no colour
        because every candidate was blocked by an already-coloured
        neighbour or by faculty/pinned unavailability.
    """
    assignment: dict[str, SlotId] = {}
    unplaced: list[str] = []

    # 1. Handle fixed-slot sessions first — they are not negotiable.
    for sess in graph.sessions.values():
        if sess.fixed_slot is not None:
            assignment[sess.id] = sess.fixed_slot

    # 2. Welsh-Powell order: descending degree, then lexicographic id for
    #    deterministic output on ties.
    free_ids = [
        sid for sid in graph.sessions if graph.sessions[sid].fixed_slot is None
    ]
    free_ids.sort(key=lambda sid: (-graph.degree(sid), sid))

    # 3. Greedily colour.
    for sid in free_ids:
        session = graph.sessions[sid]
        candidates = available_slots_for(graph, session)

        placed = False
        for slot in candidates:
            # Check that no already-coloured neighbour has this slot.
            conflict = False
            for neighbour_id in graph.neighbours(sid):
                if assignment.get(neighbour_id) == slot:
                    conflict = True
                    break
            if not conflict:
                assignment[sid] = slot
                placed = True
                break

        if not placed:
            unplaced.append(sid)

    return assignment, unplaced
