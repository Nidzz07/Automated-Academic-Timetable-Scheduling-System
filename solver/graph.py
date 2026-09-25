"""Conflict-graph construction from an edge-list payload.

This is the first half of the solver core.  It reads an edge-list payload
(validated against ``contracts/edge_list_v1.schema.json``) and builds an
undirected conflict graph:

* **one vertex** per session (including each batch session of a lab block),
* **one edge** per declared conflict, carrying its ``reason`` field.

A ``CombinedDivisions`` lecture becomes a *single* vertex over its union
cohort — the data layer has already emitted it that way, and the COHORT edges
it produces reflect containment (a Batch conflicts with its parent Division,
and a CombinedDivisions session conflicts with sessions of any member
division).  The graph builder trusts those edges; it does *not* re-derive
cohort overlaps itself.

Design note — why the builder trusts the payload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Section 5 of ``CONTEXT.md`` freezes the edge-list contract as the *only*
coupling between the data layer and the solver.  The data layer has full
knowledge of the cohort hierarchy (Division → Batch, CombinedDivisions →
member divisions) and emits COHORT edges for every overlapping pair.  The
solver receiving pre-computed edges is cleaner than duplicating the
hierarchy resolution inside ``solver/``, and it keeps ``solver/`` free of
database or ORM imports (rule 2).

What the graph builder *does* verify:

* every edge endpoint is a known session id,
* a session's ``faculty_id`` has a matching ``faculty_availability`` entry,
* there are no duplicate session ids.

Stdlib only — ``solver/`` must never import ``networkx`` or any non-stdlib
package (CONTEXT.md rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from solver.slots import SlotId, all_slots, is_teaching_period

__all__ = [
    "ConflictGraph",
    "Edge",
    "Session",
    "build_conflict_graph",
]


# ---------------------------------------------------------------------------
# Data classes — plain Python, no ORM
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Session:
    """One vertex in the conflict graph."""

    id: str
    subject_id: str
    faculty_id: str
    cohort_id: str
    session_type: str  # "theory" | "lab"
    duration_periods: int
    cohort_size: int
    requires_lab: bool
    fixed_slot: SlotId | None


@dataclass(frozen=True, slots=True)
class Edge:
    """An undirected conflict edge between two sessions."""

    u: str
    v: str
    reason: str  # "FACULTY" | "ROOM" | "COHORT"

    @property
    def pair(self) -> frozenset[str]:
        return frozenset((self.u, self.v))


@dataclass(slots=True)
class ConflictGraph:
    """Undirected conflict graph with O(1) adjacency lookups.

    The ``adjacency`` dict maps each session id to a dict of
    ``{neighbour_id: set_of_reasons}``.  A pair may appear with more than
    one reason (e.g. FACULTY **and** COHORT), and each reason is preserved
    because infeasibility diagnosis needs it.
    """

    sessions: dict[str, Session] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    adjacency: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    faculty_unavailable: dict[str, set[SlotId]] = field(default_factory=dict)
    pinned_slots: dict[SlotId, dict[str, set[str]]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Query helpers — O(1), as ROADMAP Track A [S] asks for
    # ------------------------------------------------------------------

    def degree(self, session_id: str) -> int:
        """Number of distinct neighbours (not distinct edges — a pair with
        two reasons counts as one neighbour)."""
        return len(self.adjacency.get(session_id, {}))

    def neighbours(self, session_id: str) -> frozenset[str]:
        """Ids of sessions adjacent to *session_id*."""
        return frozenset(self.adjacency.get(session_id, {}))

    def vertex_count(self) -> int:
        return len(self.sessions)

    def edge_count(self) -> int:
        """Distinct (u, v) pairs — a pair with two reasons is one edge."""
        seen: set[frozenset[str]] = set()
        for e in self.edges:
            seen.add(e.pair)
        return len(seen)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _parse_slot(raw: dict[str, Any] | None) -> SlotId | None:
    if raw is None:
        return None
    return SlotId(day=raw["day"], period=raw["period"])


def build_conflict_graph(payload: dict[str, Any]) -> ConflictGraph:
    """Build a :class:`ConflictGraph` from a validated edge-list payload.

    Parameters
    ----------
    payload:
        A Python dict matching ``contracts/edge_list_v1.schema.json``.
        The caller is responsible for JSON-schema validation; this function
        checks only structural invariants that cannot be expressed in the
        schema (referential integrity, uniqueness).

    Raises
    ------
    ValueError
        If the payload violates a structural invariant.
    """
    graph = ConflictGraph()

    # ---- sessions → vertices -----------------------------------------

    for raw in payload["sessions"]:
        sid = raw["id"]
        if sid in graph.sessions:
            raise ValueError(f"duplicate session id: {sid!r}")
        graph.sessions[sid] = Session(
            id=sid,
            subject_id=raw["subject_id"],
            faculty_id=raw["faculty_id"],
            cohort_id=raw["cohort_id"],
            session_type=raw["session_type"],
            duration_periods=raw["duration_periods"],
            cohort_size=raw["cohort_size"],
            requires_lab=raw["requires_lab"],
            fixed_slot=_parse_slot(raw["fixed_slot"]),
        )
        graph.adjacency[sid] = {}

    # ---- edges -------------------------------------------------------

    for raw in payload["edges"]:
        u, v, reason = raw["u"], raw["v"], raw["reason"]
        if u not in graph.sessions:
            raise ValueError(f"edge references unknown session: {u!r}")
        if v not in graph.sessions:
            raise ValueError(f"edge references unknown session: {v!r}")
        if u == v:
            raise ValueError(f"self-loop on session {u!r}")

        edge = Edge(u=u, v=v, reason=reason)
        graph.edges.append(edge)

        # Symmetric adjacency with reason sets.
        graph.adjacency[u].setdefault(v, set()).add(reason)
        graph.adjacency[v].setdefault(u, set()).add(reason)

    # ---- faculty availability ----------------------------------------

    for entry in payload["faculty_availability"]:
        fid = entry["faculty_id"]
        slots: set[SlotId] = set()
        for raw_slot in entry["unavailable_slots"]:
            slots.add(SlotId(day=raw_slot["day"], period=raw_slot["period"]))
        graph.faculty_unavailable[fid] = slots

    # Verify every session's faculty has an availability entry.
    for sess in graph.sessions.values():
        if sess.faculty_id not in graph.faculty_unavailable:
            raise ValueError(
                f"session {sess.id!r} references faculty {sess.faculty_id!r} "
                f"which has no faculty_availability entry"
            )

    # ---- pinned occupancy --------------------------------------------
    # Store per-slot sets of consumed faculty / room / cohort ids.

    for pin in payload["pinned_occupancy"]:
        slot = SlotId(day=pin["day"], period=pin["period"])
        bucket = graph.pinned_slots.setdefault(
            slot,
            {"faculty_ids": set(), "room_ids": set(), "cohort_ids": set()},
        )
        bucket["faculty_ids"].update(pin["faculty_ids"])
        bucket["room_ids"].update(pin["room_ids"])
        bucket["cohort_ids"].update(pin["cohort_ids"])

    return graph


def available_slots_for(
    graph: ConflictGraph,
    session: Session,
) -> list[SlotId]:
    """Teaching slots where *session* can be placed, respecting:

    * faculty unavailability,
    * pinned occupancy blocking the session's faculty or cohort,
    * the fixed_slot pre-assignment (returns just that slot).

    Room assignment is **not** handled here — that is Phase 2 (backtracking).
    This function provides the colour domain for greedy colouring.
    """
    if session.fixed_slot is not None:
        return [session.fixed_slot]

    unavailable = graph.faculty_unavailable.get(session.faculty_id, set())
    result: list[SlotId] = []

    for slot in all_slots():
        if not is_teaching_period(slot.period):
            continue
        if slot in unavailable:
            continue
        # Pinned occupancy: skip if this slot pins the session's faculty or
        # cohort.
        pin = graph.pinned_slots.get(slot)
        if pin is not None:
            if session.faculty_id in pin["faculty_ids"]:
                continue
            if session.cohort_id in pin["cohort_ids"]:
                continue
        result.append(slot)

    return result
