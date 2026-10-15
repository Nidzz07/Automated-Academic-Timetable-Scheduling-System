"""Pre-solve: polynomial infeasibility checks run before the search (ROADMAP D21).

Chronological backtracking can only refute "40 pairwise-conflicting periods in
39 slots" by exhausting the search, which did not finish in 300 s on the
synthetic ``infeasible`` preset (docs/solver-baseline-2026-10-06.md, finding 4).
Every check here is a *necessary* condition for a timetable to exist, run on the
initial domains of :mod:`solver.backtracking`.  A failed check is therefore a
proof of infeasibility, returned as a :class:`Certificate`; a passed check proves
nothing, and the search still runs.

Checks, in the order they run:

1. ``room_suitability`` - every session has at least one room of the right type
   and capacity.
2. ``faculty_load`` / ``cohort_load`` - pigeonhole (Discrete Structures,
   CE201).  The periods a group of pairwise-conflicting sessions must be taught
   cannot exceed the periods any of them can be taught in.
3. ``lab_capacity`` - per period, the lab sessions *forced* into that period
   cannot outnumber the lab rooms usable in parallel then.
4. ``hall_faculty`` / ``hall_cohort`` - Hall's marriage theorem, tested by a
   maximum bipartite matching found with Hopcroft-Karp (Design and Analysis of
   Algorithms, CE207): every subset of the group's periods needs at least as
   many slots it can use.  This catches what the counting check cannot - for
   example three sessions all fixed into the same two slots.

**Groups of pairwise-conflicting sessions.**  ``edge_list_v1`` carries no
cohort hierarchy, so "a division session also occupies all its batches" is
read from the COHORT edges the data layer emits (as :mod:`solver.graph` does):
for each cohort, a clique is grown greedily from that cohort's own sessions,
adding any session COHORT-adjacent to every member so far.  For a batch that
picks up its division's and combined-division sessions plus its own lab
sessions.  The faculty groups are built the same way on FACULTY edges.  Only
edges are used, never ``faculty_id`` alone, so a check never claims a conflict
the search would not enforce.

**What "available" means.**  A session's reachable slots are the union of the
periods it occupies over every start left in its initial domain - so faculty
unavailability, pinned blocks, fixed slots, contiguity and room availability
are already folded in.

Pure stdlib; called by :func:`solver.backtracking.backtrack_solve`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from solver.backtracking import _occupied_slots, _room_is_pinned, _room_suits, _SolverState
from solver.graph import ConflictGraph
from solver.slots import SlotId

__all__ = ["Certificate", "hopcroft_karp", "presolve"]


@dataclass(frozen=True, slots=True)
class Certificate:
    """Why the instance is infeasible, found before any search.

    ``kind`` is the ``solution.v2`` closed constraint kind the check maps to;
    under v1 it is just the free-text ``kind`` string.
    """

    check: str
    kind: str
    session_ids: tuple[str, ...]
    resource: str
    reason: str

    def to_diagnosis(self) -> dict[str, Any]:
        """The certificate in ``solution_v1``'s ``diagnosis`` shape.

        A certificate is a proof, not a minimal unsatisfiable subset: v1 has no
        field for that distinction (v2's ``diagnosis.method`` will).
        """
        cid = f"presolve.{self.check}.{self.resource}"
        ids = [*self.session_ids]
        if self.check in _RESOURCE_IS_AN_ID:
            ids.append(self.resource)
        return {
            "minimal_conflicting_set": [
                {"constraint_id": cid, "kind": self.kind, "description": self.reason,
                 "entity_ids": ids},
            ],
            "suggested_relaxation": {
                "constraint_id": cid,
                "description": (
                    f"Pre-solve check '{self.check}' failed for {self.resource}: move or "
                    "drop one of the listed sessions, or free more slots or rooms for them."
                ),
            },
        }


# Checks whose resource is a faculty or cohort id from the payload; the others
# name a slot or a room requirement, which is not an entity id.
_RESOURCE_IS_AN_ID = frozenset({"faculty_load", "cohort_load", "hall_faculty", "hall_cohort"})


def presolve(state: _SolverState) -> Certificate | None:
    """Run every check on *state*'s initial domains; the first failure, or None."""
    graph = state.graph
    reach = {
        sid: {
            slot
            for start in {start for start, _ in domain}
            for slot in _occupied_slots(state, sid, start) or ()
        }
        for sid, domain in state.domains.items()
    }
    groups = [
        ("faculty", fid, _clique(graph, [s for s in sorted(graph.sessions)
                                         if graph.sessions[s].faculty_id == fid], "FACULTY"))
        for fid in sorted({s.faculty_id for s in graph.sessions.values()})
    ] + [
        ("cohort", cid, _clique(graph, [s for s in sorted(graph.sessions)
                                        if graph.sessions[s].cohort_id == cid], "COHORT"))
        for cid in sorted({s.cohort_id for s in graph.sessions.values()})
    ]
    return (
        _room_suitability(state)
        or next(filter(None, (_load(state, reach, *g) for g in groups)), None)
        or _lab_capacity(state)
        or next(filter(None, (_hall(state, reach, *g) for g in groups)), None)
    )


def _clique(graph: ConflictGraph, seeds: list[str], reason: str) -> list[str]:
    """Greedy clique on *reason* edges: *seeds* first, then their common neighbours."""
    if not seeds:
        return []
    first = graph.adjacency[seeds[0]]
    extra = sorted(n for n, reasons in first.items() if reason in reasons and n not in seeds)
    clique: list[str] = []
    for sid in seeds + extra:
        if all(reason in graph.adjacency[sid].get(m, ()) for m in clique):
            clique.append(sid)
    return clique


# v2 kind: ROOM_TYPE (no lab room at all) or ROOM_CAPACITY (none large enough).
def _room_suitability(state: _SolverState) -> Certificate | None:
    rooms = list(state.rooms.values())
    for sid in sorted(state.graph.sessions):
        session = state.graph.sessions[sid]
        if any(_room_suits(r, session) for r in rooms):
            continue
        typed = [r for r in rooms if r.hosts_labs or not session.requires_lab]
        what = "lab room" if session.requires_lab else "room"
        if typed:
            largest = max(r.capacity for r in typed)
            reason = (f"Session {sid} needs a {what} for {session.cohort_size} students; "
                      f"the largest {what} holds {largest}.")
            return Certificate("room_suitability", "ROOM_CAPACITY", (sid,), what, reason)
        reason = f"Session {sid} needs a {what} and the room inventory has none."
        return Certificate("room_suitability", "ROOM_TYPE", (sid,), what, reason)
    return None


# v2 kind: FACULTY_CLASH (faculty) / COHORT_CLASH (cohort); the slots lost to
# FACULTY_UNAVAILABLE and PINNED_BLOCK are what make the bound bite.
def _load(
    state: _SolverState,
    reach: dict[str, set[SlotId]],
    group: str,
    resource: str,
    clique: list[str],
) -> Certificate | None:
    """Pigeonhole (CE201): pairwise-conflicting sessions occupy disjoint periods."""
    need = sum(state.graph.sessions[s].duration_periods for s in clique)
    have = len(set().union(*(reach[s] for s in clique)))
    if need <= have:
        return None
    kind = "FACULTY_CLASH" if group == "faculty" else "COHORT_CLASH"
    reason = (f"{group.capitalize()} {resource} must be taught {need} periods "
              f"({len(clique)} sessions that cannot overlap) but only {have} periods are "
              "free for them.")
    return Certificate(f"{group}_load", kind, tuple(sorted(clique)), resource, reason)


# v2 kind: ROOM_OCCUPANCY (with ROOM_TYPE: only lab rooms count).
def _lab_capacity(state: _SolverState) -> Certificate | None:
    """Lab sessions forced into a period vs. lab rooms usable in parallel then.

    A session (or whole lab block) is forced into a period when every start
    left in its domain occupies it.  Parallel capacity counts, per physical
    room, either the room itself or its lab sub-rooms, whichever is more, and
    ignores head count - an upper bound, so the check stays sound.
    """
    units: list[tuple[str, ...]] = [tuple(b.session_ids) for b in state.lab_blocks]
    units += [(sid,) for sid in sorted(state.graph.sessions)
              if state.graph.sessions[sid].requires_lab and sid not in state.session_to_block]
    forced: dict[SlotId, list[str]] = {}
    for members in units:
        if not members:
            continue
        starts = set.intersection(*({st for st, _ in state.domains[s]} for s in members))
        chains = [set(_occupied_slots(state, members[0], st) or ()) for st in starts]
        for slot in set.intersection(*chains) if chains else ():
            forced.setdefault(slot, []).extend(members)
    for slot in sorted(forced):
        sessions = forced[slot]
        capacity = sum(
            max(
                int(room.hosts_labs and not _room_is_pinned(state, room.id, slot)),
                sum(state.rooms[c].hosts_labs and not _room_is_pinned(state, c, slot)
                    for c in state.children_of.get(room.id, [])),
            )
            for room in state.rooms.values() if room.parent_room_id is None
        )
        if len(sessions) > capacity:
            reason = (f"At {slot}, {len(sessions)} lab sessions have no other possible "
                      f"slot but only {capacity} lab rooms can be used in parallel.")
            return Certificate("lab_capacity", "ROOM_OCCUPANCY", tuple(sorted(sessions)),
                               f"slot.{slot.day}.{slot.period}", reason)
    return None


# v2 kind: FACULTY_CLASH (faculty) / COHORT_CLASH (cohort), as for _load.
def _hall(
    state: _SolverState,
    reach: dict[str, set[SlotId]],
    group: str,
    resource: str,
    clique: list[str],
) -> Certificate | None:
    """Hall's condition (CE207) on periods -> slots for one conflicting group.

    Each session contributes ``duration_periods`` left vertices, each joined
    to every slot the session can occupy.  A timetable gives every period of
    the group its own slot, so it is a matching that saturates the left side;
    if the maximum matching is smaller, the alternating-path set from an
    unmatched period is a Hall violator: ``|N(L)| = |L| - 1``.
    """
    units = [s for s in clique for _ in range(state.graph.sessions[s].duration_periods)]
    slots = sorted(set().union(*(reach[s] for s in clique)))
    index = {slot: i for i, slot in enumerate(slots)}
    adj = [sorted(index[t] for t in reach[s]) for s in units]
    match_l = hopcroft_karp(adj, len(slots))
    if -1 not in match_l:
        return None
    match_r = [-1] * len(slots)
    for u, v in enumerate(match_l):
        if v != -1:
            match_r[v] = u
    left, right = {match_l.index(-1)}, set()
    queue = deque(left)
    while queue:
        for v in adj[queue.popleft()]:
            if v not in right:
                right.add(v)
                w = match_r[v]  # matched: the matching is maximum
                if w not in left:
                    left.add(w)
                    queue.append(w)
    sessions = tuple(sorted({units[u] for u in left}))
    free = ", ".join(str(slots[v]) for v in sorted(right)) or "none"
    reason = (f"{group.capitalize()} {resource}: sessions {', '.join(sessions)} need "
              f"{len(left)} periods that cannot overlap but can only use {len(right)} "
              f"slots ({free}).")
    kind = "FACULTY_CLASH" if group == "faculty" else "COHORT_CLASH"
    return Certificate(f"hall_{group}", kind, sessions, resource, reason)


def hopcroft_karp(adj: list[list[int]], n_right: int) -> list[int]:
    """Maximum bipartite matching (Hopcroft-Karp, Design and Analysis of Algorithms CE207).

    *adj[u]* lists the right vertices of left vertex *u*.  Each phase finds the
    shortest augmenting-path layers by BFS from every free left vertex, then
    augments along vertex-disjoint layered paths by DFS; O(E sqrt(V)).
    Returns, per left vertex, its matched right vertex or -1.
    """
    inf = len(adj) + 1
    match_l = [-1] * len(adj)
    match_r = [-1] * n_right
    dist = [inf] * len(adj)

    def augment(u: int) -> bool:
        for v in adj[u]:
            w = match_r[v]
            if w == -1 or (dist[w] == dist[u] + 1 and augment(w)):
                match_l[u], match_r[v] = v, u
                return True
        dist[u] = inf
        return False

    while True:
        queue: deque[int] = deque()
        for u in range(len(adj)):
            dist[u] = 0 if match_l[u] == -1 else inf
            if match_l[u] == -1:
                queue.append(u)
        found = False
        while queue:
            u = queue.popleft()
            for v in adj[u]:
                w = match_r[v]
                if w == -1:
                    found = True
                elif dist[w] == inf:
                    dist[w] = dist[u] + 1
                    queue.append(w)
        if not found:
            return match_l
        for u in range(len(adj)):
            if match_l[u] == -1:
                augment(u)
