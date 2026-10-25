"""Lower bounds on the teaching periods a week needs (S12i).

:func:`lower_bounds` reads an ``edge_list_v1`` payload and solves nothing; no
solve, improve or repair result depends on it.

**Clique bound** (Discrete Structures and Graph Theory: the clique number is at
most the chromatic number, ``omega(G) <= chi(G)``). Sessions joined by a
conflict edge (same teacher, students shared, a ROOM edge) may not share a
period, so the sessions of a clique need pairwise different periods: their
total length, a 2-period practical counting 2 (a lab block's members each
count its length), is a lower bound on the periods the week must hold. The
maximum-weight clique is found by branch and bound (Design and Analysis of
Algorithms: vertices by weight, prune when the clique plus every remaining
candidate cannot beat the best), within :data:`EXACT_NODES` search nodes;
past that budget the heaviest clique a greedy pass grows from each vertex is
used instead, and ``method`` says which. A greedy clique is still a clique, so
the bound holds either way; only the exact one is the largest.

**Load bounds.** One teacher's week holds their sessions' periods plus every
teaching slot a pin holds them in or they are unavailable at; one cohort's
week holds its own sessions' periods plus every teaching slot a pin holds it
in (a year's lunch included: the solver cannot tell lunch from another pin,
D41). Sessions never use those slots, so the sum is busy teaching slots, at
most the grid's teaching slots. Counting over hash maps (Data Structures).

Stdlib and ``solver.*`` only.
"""

from __future__ import annotations

from typing import Any

from solver.graph import build_conflict_graph

__all__ = ["EXACT_NODES", "lower_bounds"]

EXACT_NODES = 200_000  # branch-and-bound nodes before the greedy clique is used


class _Budget(Exception):
    pass


def _exact(order: list[str], weight: dict[str, int], adj: dict[str, frozenset[str]],
           start: tuple[int, list[str]]) -> tuple[int, list[str]]:
    """Maximum-weight clique by branch and bound; raises :class:`_Budget` past EXACT_NODES."""
    best = start
    nodes = 0

    def expand(clique: list[str], total: int, candidates: list[str]) -> None:
        nonlocal best, nodes
        nodes += 1
        if nodes > EXACT_NODES:
            raise _Budget
        if total > best[0]:
            best = (total, list(clique))
        rest = sum(weight[v] for v in candidates)
        for i, v in enumerate(candidates):
            if total + rest <= best[0]:
                return  # even every remaining candidate cannot beat the best
            rest -= weight[v]
            expand([*clique, v], total + weight[v],
                   [u for u in candidates[i + 1:] if u in adj[v]])

    expand([], 0, order)
    return best


def _greedy(order: list[str], weight: dict[str, int],
            adj: dict[str, frozenset[str]]) -> tuple[int, list[str]]:
    """From each vertex, add the heaviest vertex adjacent to all chosen; keep the heaviest."""
    best: tuple[int, list[str]] = (0, [])
    for v in order:
        clique, candidates = [v], [u for u in order if u in adj[v]]
        while candidates:
            u = candidates[0]  # order is by weight, then id
            clique.append(u)
            candidates = [x for x in candidates[1:] if x in adj[u]]
        total = sum(weight[x] for x in clique)
        if total > best[0]:
            best = (total, clique)
    return best


def lower_bounds(edge_list: dict[str, Any]) -> dict[str, Any]:
    """Lower bounds on the teaching periods a week needs, as plain data.

    Returns
    -------
    dict
        ``teaching_slots``: the grid's teaching (day, period) cells;
        ``clique``: ``{"periods", "session_ids", "method"}`` (``exact`` or
        ``greedy``), sessions in id order; ``teacher`` and ``cohort``: the
        heaviest load, ``{"id", "periods", "sessions", "held"}`` (session
        periods, then pinned or unavailable slots), ties to the smaller id.
    """
    graph = build_conflict_graph(edge_list)
    grid = graph.grid
    weight = {sid: s.duration_periods for sid, s in graph.sessions.items()}
    adj = {sid: graph.neighbours(sid) for sid in graph.sessions}
    order = sorted(graph.sessions, key=lambda v: (-weight[v], v))

    greedy = _greedy(order, weight, adj)
    try:
        periods, clique = _exact(order, weight, adj, greedy)
        method = "exact"
    except _Budget:
        (periods, clique), method = greedy, "greedy"

    taught: dict[str, int] = {}
    attended: dict[str, int] = {}
    for s in graph.sessions.values():
        taught[s.faculty_id] = taught.get(s.faculty_id, 0) + s.duration_periods
        attended[s.cohort_id] = attended.get(s.cohort_id, 0) + s.duration_periods
    busy_teacher: dict[str, set[Any]] = {
        f: {s for s in slots if grid.is_teaching_period(s.period)}
        for f, slots in graph.faculty_unavailable.items()}
    busy_cohort: dict[str, set[Any]] = {}
    for slot, pin in graph.pinned_slots.items():
        if grid.is_teaching_period(slot.period):
            for f in pin["faculty_ids"]:
                busy_teacher.setdefault(f, set()).add(slot)
            for c in pin["cohort_ids"]:
                busy_cohort.setdefault(c, set()).add(slot)

    def heaviest(sessions: dict[str, int], held: dict[str, set[Any]]) -> dict[str, Any] | None:
        loads = sorted(((sessions[k] + len(held.get(k, ())), k) for k in sessions),
                       key=lambda t: (-t[0], t[1]))
        if not loads:
            return None
        total, key = loads[0]
        return {"id": key, "periods": total, "sessions": sessions[key],
                "held": len(held.get(key, ()))}

    return {
        "teaching_slots": grid.days * len(grid.teaching_periods),
        "clique": {"periods": periods, "session_ids": sorted(clique), "method": method},
        "teacher": heaviest(taught, busy_teacher),
        "cohort": heaviest(attended, busy_cohort),
    }
