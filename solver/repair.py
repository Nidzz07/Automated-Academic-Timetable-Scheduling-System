"""Repair a solved timetable after a change, moving as few sessions as possible (S14a).

:func:`repair` takes a valid ``solution.v2`` timetable and one change:

* ``faculty_unavailable`` - a faculty member cannot teach at given slots
  (an absence, D36);
* ``room_unavailable`` - a room cannot be used at given slots;
* ``move_session`` - a person drags one session to a given slot and room.

:func:`apply_change` writes the change into the ``edge_list_v1`` payload with
the fields the contract already has: an absence is ``unavailable_slots``, a
closed room is a room-only ``pinned_occupancy`` entry per slot (a closed parent
also closes its sub-rooms, as for any pin), and a drag is the session's
``fixed_slot``; the dragged room has no payload field, so :func:`repair` holds
it as that session's only room. The result is valid against the changed
payload.

**Freeze and expand** (Design and Analysis of Algorithms, CE207: backtracking;
Discrete Structures and Graph Theory: breadth-first search). A session is *hit*
when its placement is no longer allowed (outside its new static domain) or,
for a drag, stands in the dragged session's way; a lab block is hit whole.
Every other session is frozen at its slot and room
(:func:`solver.backtracking.backtrack_solve` with ``seed_assignment`` and
``seed_rooms``) and only the hit sessions are re-placed. If that fails, the
free set grows by one BFS ring - the conflict-graph neighbours of every free
session (same cohort, same teacher) and the sessions in the same room on the
same day - and the search retries, until everything is free. Each ring search
has a node budget (:data:`RING_NODES`), not a clock, so the ring that succeeds
is the same on every machine; running out of nodes only means "expand".

**Fewest moves first, then score.** The ring search does not prefer old
places, so a restore pass then puts each moved session (a lab block as one)
back where it was if it now fits, else at its old start in another room, until
nothing changes (greedy). Finally :func:`solver.improve.improve` runs on a copy
of the payload in which every session still at its old start has that start as
``fixed_slot``, so the local search moves only sessions that already moved
(it never moves a fixed one) and can never add a moved session. The objective
is lexicographic: sessions whose slot changed, then sessions only re-roomed,
then the penalty. The result is a heuristic minimum, not a proven one.

**Moved sessions.** ``displaced`` lists the sessions whose slot changed, as
``solution.v2`` defines it. A session that kept its slot but changed room is
not in it; ``stats["room_changed"]`` lists those.

**Drag onto a frozen item (S14b).** Before any search, a drag whose session
would occupy a period that ``pinned_occupancy`` holds for its faculty, its
cohort or the dropped room is answered at once by :func:`solver.mus.explain`
from that pin and the drag: a minimal conflicting set naming the pin
(``pin.<index>``) and a verified relaxation.

**Infeasible and timeout.** If even the run with everything free fails, its
diagnosis (the pre-solve certificate or ``search_exhaustion``) is explained by
:func:`solver.mus.explain`: a minimal conflicting set (``method = "mus"``) and
the smallest relaxation verified to restore feasibility, or the original
diagnosis when minimality cannot be proven. Every search of the explanation
has a node budget and none uses ``time_limit_s``, so the explanation is the
same on every machine (it can make ``repair`` run past ``time_limit_s``,
never wait forever). If that run runs out of
``time_limit_s`` it raises :class:`TimeoutError`: running out of time proves
nothing (ROADMAP D21, D33). Stdlib only.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from solver.backtracking import (
    BacktrackResult,
    _assign,
    _build_initial_domains,
    _new_state,
    _placement_ok,
    _SolverState,
    _unassign,
    backtrack_solve,
)
from solver.graph import ConflictGraph, build_conflict_graph
from solver.improve import improve
from solver.mus import explain
from solver.scoring import score
from solver.slots import SlotId
from solver.validate import validate_solution

__all__ = ["CHANGE_KINDS", "MAX_MOVES", "RING_NODES", "SEED", "apply_change", "repair"]

CHANGE_KINDS = ("faculty_unavailable", "room_unavailable", "move_session")
MAX_MOVES = 20_000  # local-search moves after the repair; it only touches moved sessions
RING_NODES = 5_000  # search nodes per ring before the free set grows
SEED = 0

Placement = tuple[SlotId, str]  # (start slot, room or sub-room id)


def _slots(change: dict[str, Any]) -> list[dict[str, int]]:
    cells = sorted({(s["day"], s["period"]) for s in change["slots"]})
    if not cells:
        raise ValueError(f"{change['kind']} needs at least one slot")
    return [{"day": d, "period": p} for d, p in cells]


def apply_change(payload: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    """A copy of *payload* with *change* written into its ``edge_list_v1`` fields.

    Changes (plain dicts, slots as ``{"day", "period"}``):

    * ``{"kind": "faculty_unavailable", "faculty_id", "slots"}``
    * ``{"kind": "room_unavailable", "room_id", "slots"}``
    * ``{"kind": "move_session", "session_id", "day", "period", "room_id", "sub_room_id"}``
      - rooms as in a ``solution.v2`` placement; ``sub_room_id`` may be omitted.

    Raises:
        ValueError: on an unknown kind, faculty, room or session, no slots, or a
            slot off the payload's grid.
    """
    changed = copy.deepcopy(payload)
    kind = change.get("kind")
    if kind == "faculty_unavailable":
        entry = next((e for e in changed["faculty_availability"]
                      if e["faculty_id"] == change["faculty_id"]), None)
        if entry is None:
            raise ValueError(f"unknown faculty {change['faculty_id']!r}")
        known = {(s["day"], s["period"]) for s in entry["unavailable_slots"]}
        entry["unavailable_slots"] += [
            s for s in _slots(change) if (s["day"], s["period"]) not in known
        ]
    elif kind == "room_unavailable":
        if change["room_id"] not in {r["id"] for r in changed["rooms"]}:
            raise ValueError(f"unknown room {change['room_id']!r}")
        changed["pinned_occupancy"] += [
            {**s, "faculty_ids": [], "room_ids": [change["room_id"]], "cohort_ids": []}
            for s in _slots(change)
        ]
    elif kind == "move_session":
        session = next((s for s in changed["sessions"] if s["id"] == change["session_id"]), None)
        if session is None:
            raise ValueError(f"unknown session {change['session_id']!r}")
        if _room_of(change) not in {r["id"] for r in changed["rooms"]}:
            raise ValueError(f"unknown room {_room_of(change)!r}")
        session["fixed_slot"] = {"day": change["day"], "period": change["period"]}
    else:
        raise ValueError(f"unknown change kind {kind!r}; expected one of {CHANGE_KINDS}")
    build_conflict_graph(changed)  # every new slot must lie on the grid
    return changed


def _room_of(item: dict[str, Any]) -> str:
    """The solver's room id of a placement-shaped dict: the sub-room when there is one."""
    return item.get("sub_room_id") or item["room_id"]


def _state(graph: ConflictGraph, payload: dict[str, Any],
           forced: dict[str, str]) -> _SolverState:
    """Static domains of *payload*, a dragged session held to its room."""
    state = _new_state(graph, payload)
    _build_initial_domains(state)
    for sid, room in forced.items():
        state.domains[sid] = {v for v in state.domains[sid] if v[1] == room}
    return state


def _put(state: _SolverState, sid: str, start: SlotId, room: str) -> bool:
    """Place *sid* if (start, room) is in its domain and fits now."""
    if (start, room) not in state.domains[sid]:
        return False
    slots = _placement_ok(state, sid, start, room)
    if slots is None:
        return False
    _assign(state, sid, start, room, slots)
    return True


def _in_the_way(state: _SolverState, sid: str, start: SlotId, room: str) -> set[str]:
    """Assigned sessions that clash with *sid* at (start, room): a conflict edge
    or the same room, its parent or a sub-room, in any period it would occupy."""
    chain = state.chains.get((start, state.graph.sessions[sid].duration_periods), ())
    units = {room, *state.children_of.get(room, [])}
    if room in state.parent_of:
        units.add(state.parent_of[room])
    hit = {n for n in state.graph.neighbours(sid)
           if n in state.occupied and not set(chain).isdisjoint(state.occupied[n])}
    hit.update(state.room_occupancy[(slot, unit)] for slot in chain for unit in units
               if (slot, unit) in state.room_occupancy)
    hit.discard(sid)
    return hit


def _frozen_in_the_way(state: _SolverState, payload: dict[str, Any],
                       change: dict[str, Any]) -> list[str]:
    """``pin.<index>`` of every ``pinned_occupancy`` entry holding the dragged
    session's faculty, cohort or dropped room in a period it would occupy."""
    session = state.graph.sessions[change["session_id"]]
    start = SlotId(change["day"], change["period"])
    chain = state.chains.get((start, session.duration_periods), ())
    room = _room_of(change)
    units = {room, state.parent_of.get(room, room), *state.children_of.get(room, [])}
    return [f"pin.{i}" for i, pin in enumerate(payload["pinned_occupancy"])
            if SlotId(pin["day"], pin["period"]) in chain
            and (session.faculty_id in pin["faculty_ids"] or session.cohort_id in pin["cohort_ids"]
                 or not units.isdisjoint(pin["room_ids"]))]


def repair(
    payload: dict[str, Any],
    solution: dict[str, Any],
    change: dict[str, Any],
    *,
    seed: int = SEED,
    max_moves: int = MAX_MOVES,
    ring_nodes: int = RING_NODES,
    time_limit_s: float | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """*solution* repaired for *change*: a ``solution.v2`` valid against
    ``apply_change(payload, change)``.

    Parameters
    ----------
    payload:
        The ``edge_list_v1`` instance *solution* solves, before the change.
    solution:
        A valid solved ``solution.v2`` payload.
    change:
        One change, as :func:`apply_change` describes.
    seed, max_moves:
        For the closing :func:`solver.improve.improve` pass; ``max_moves=0``
        skips it.
    ring_nodes:
        Search nodes each frozen ring may use before the free set grows.
    time_limit_s:
        Wall-clock safety cap on each search, ``None`` for none. Hitting it on
        a ring only grows the ring (and the result then depends on the machine).
        The explanation of an infeasible change has node budgets instead.
    stats:
        If given, filled with ``hit`` (sessions the change hit), ``rings``
        (``[ring, freed, outcome]`` per search), ``room_changed`` (same slot,
        new room), ``nodes``, ``improve`` (its stats) and, when infeasible,
        ``mus`` (the stats of :func:`solver.mus.explain`).

    Returns
    -------
    dict
        Solved: the repaired timetable, ``displaced`` = sessions whose slot
        changed, scored against the changed payload. Infeasible (a drag onto a
        frozen item, or no timetable even with every session free): the
        explained diagnosis.

    Raises
    ------
    ValueError
        If *solution* is not solved or not valid for *payload*, or *change* is
        malformed (see :func:`apply_change`).
    TimeoutError
        If the search with every session free ran out of *time_limit_s*.
    """
    started = time.perf_counter()
    if solution["status"] != "solved":
        raise ValueError("repair needs a solved timetable")
    violations = validate_solution(payload, solution)
    if violations:
        raise ValueError(f"repair needs a valid timetable: {[v.to_dict() for v in violations]}")
    changed = apply_change(payload, change)
    graph = build_conflict_graph(changed)
    old: dict[str, Placement] = {
        i["session_id"]: (SlotId(i["day"], i["period"]), _room_of(i))
        for i in solution["assignment"]
    }
    forced = {change["session_id"]: _room_of(change)} if change["kind"] == "move_session" else {}
    deadline = None if time_limit_s is None else started + time_limit_s

    def left() -> float | None:
        return None if deadline is None else max(0.0, deadline - time.perf_counter())

    # --- a drag onto a frozen item: explained before any search
    state = _state(graph, changed, forced)
    blocked = _frozen_in_the_way(state, payload, change) if forced else []
    if blocked:
        mus_stats: dict[str, Any] = {}
        out = explain(payload, None, change=change, initial=blocked, timetable=solution,
                      stats=mus_stats)
        if out is not None:
            out["metadata"].update(
                algorithm=f"freeze-and-expand(pre-check) + {out['metadata']['algorithm']}",
                runtime_ms=(time.perf_counter() - started) * 1000)
            if stats is not None:
                stats.update(hit=[change["session_id"]], rings=[], room_changed=[], nodes=0,
                             improve={}, mus=mus_stats)
            return out

    # --- hit: placements the change forbids, and for a drag what stands in its way
    hit = {sid for sid in sorted(old) if old[sid] not in state.domains[sid]}
    for sid in sorted(set(old) - hit):
        start, room = old[sid]
        _assign(state, sid, start, room,
                state.chains[(start, graph.sessions[sid].duration_periods)])
    for sid, room in forced.items():
        if sid in hit:
            hit |= _in_the_way(state, sid, SlotId(change["day"], change["period"]), room)
    block_of = {sid: b.session_ids for b in state.lab_blocks for sid in b.session_ids}

    def whole(sids: set[str]) -> set[str]:
        return {m for sid in sids for m in block_of.get(sid, (sid,))}

    by_room_day: dict[tuple[str, int], set[str]] = {}
    for sid, (start, room) in old.items():
        top = state.parent_of.get(room, room)
        by_room_day.setdefault((top, start.day), set()).add(sid)

    def ring(free: set[str]) -> set[str]:
        grown = set(free)
        for sid in free:
            grown |= graph.neighbours(sid)
            start, room = old[sid]
            grown |= by_room_day[(state.parent_of.get(room, room), start.day)]
        return whole(grown)

    # --- freeze and expand
    hit = whole(hit)
    free, rings, nodes = set(hit), [], 0
    while True:
        everything = len(free) == len(graph.sessions)
        frozen = sorted(set(graph.sessions) - free)
        budget = left()
        result = backtrack_solve(
            graph, changed,
            seed_assignment={sid: old[sid][0] for sid in frozen},
            seed_rooms={**{sid: old[sid][1] for sid in frozen}, **forced},
            prefer=old,
            node_limit=None if everything else ring_nodes,
            time_limit_s=budget,
        )
        nodes += result.nodes_explored
        rings.append(["all" if everything else len(rings), len(free), result.outcome])
        if result.solved:
            break
        if everything:
            if result.timed_out:
                raise TimeoutError(f"no repair found within {time_limit_s} s (ROADMAP D33)")
            out = result.to_solution_v2_dict(
                total_sessions=len(graph.sessions),
                runtime_ms=(time.perf_counter() - started) * 1000,
            )
            out["metadata"].update(algorithm=f"freeze-and-expand(rings={len(rings)})",
                                   backtracks=nodes)
            mus_stats = {}
            out = explain(payload, out, change=change, timetable=solution,
                          stats=mus_stats) or out
            out["metadata"]["runtime_ms"] = (time.perf_counter() - started) * 1000
            if stats is not None:
                stats.update(hit=sorted(hit), rings=rings, room_changed=[], nodes=nodes,
                             improve={}, mus=mus_stats)
            return out
        grown = ring(free)
        free = grown if grown != free else set(graph.sessions)

    # --- restore: put moved sessions back where they were, whole blocks at a time
    state = _state(graph, changed, forced)
    for sid in sorted(result.assignment):
        start = result.assignment[sid]
        _assign(state, sid, start, result.room_assignment[sid],
                state.chains[(start, graph.sessions[sid].duration_periods)])

    def cost(unit: tuple[str, ...]) -> tuple[int, int]:
        moved = sum(state.slot_assignment[s] != old[s][0] for s in unit)
        return moved, sum(state.room_assignment[s] != old[s][1] for s in unit) - moved

    def back(unit: tuple[str, ...], any_room: bool) -> bool:
        """Every member at its old start: in its old room, or (any_room) the first that fits."""
        for s in unit:
            start = old[s][0]
            rooms = ([r for r in sorted({r for st, r in state.domains[s] if st == start})
                      if r != old[s][1]] if any_room else [])
            if not any(_put(state, s, start, r) for r in [old[s][1], *rooms]):
                return False
        return True

    units = sorted({block_of.get(sid, (sid,)) for sid in graph.sessions})
    better = True
    while better:
        better = False
        for unit in units:
            was = cost(unit)
            if was == (0, 0):
                continue
            now = [(s, state.slot_assignment[s], state.room_assignment[s]) for s in unit]
            for any_room in ([False, True] if was[0] else [False]):
                for s in unit:
                    _unassign(state, s)
                if back(unit, any_room) and cost(unit) < was:
                    better = True
                    break
                for s in unit:
                    if s in state.slot_assignment:
                        _unassign(state, s)
                for s, start, room in now:
                    _assign(state, s, start, room,
                            state.chains[(start, graph.sessions[s].duration_periods)])

    # --- improve, moving only sessions that already moved
    starts = dict(state.slot_assignment)
    repaired = BacktrackResult(
        assignment=starts, room_assignment=dict(state.room_assignment), solved=True,
        nodes_explored=nodes, rooms=state.rooms, occupied=dict(state.occupied),
        edge_list=changed,
    ).to_solution_v2_dict(total_sessions=len(graph.sessions),
                          runtime_ms=(time.perf_counter() - started) * 1000)
    repaired["metadata"]["algorithm"] = (
        f"freeze-and-expand(rings={len(rings)}, freed={len(free)}, nodes={nodes})"
    )
    moved = {sid for sid in starts if starts[sid] != old[sid][0]}
    improve_stats: dict[str, Any] = {}
    if moved and max_moves > 0:
        held = copy.deepcopy(changed)
        for s in held["sessions"]:
            if s["id"] not in moved:
                s["fixed_slot"] = {"day": starts[s["id"]].day, "period": starts[s["id"]].period}
        repaired = improve(held, repaired, max_moves=max_moves, seed=seed,
                           stats=improve_stats)
        repaired["quality"] = score(changed, {
            i["session_id"]: SlotId(i["day"], i["period"]) for i in repaired["assignment"]
        })
    final = {i["session_id"]: (SlotId(i["day"], i["period"]), _room_of(i))
             for i in repaired["assignment"]}
    repaired["displaced"] = sorted(sid for sid in final if final[sid][0] != old[sid][0])
    repaired["metadata"]["runtime_ms"] = (time.perf_counter() - started) * 1000
    violations = validate_solution(changed, repaired)
    if violations:
        raise AssertionError(f"repair broke a hard rule: {[v.to_dict() for v in violations]}")
    if stats is not None:
        stats.update(
            hit=sorted(hit), rings=rings, nodes=nodes, improve=improve_stats,
            room_changed=sorted(sid for sid in final
                                if final[sid][0] == old[sid][0] and final[sid][1] != old[sid][1]),
        )
    return repaired
