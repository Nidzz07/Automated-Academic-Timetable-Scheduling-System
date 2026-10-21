"""Quality improvement of a solved timetable by local search (S12g).

:func:`improve` starts from a valid ``solution.v2`` timetable and moves only
between valid timetables, lowering the penalty :func:`solver.scoring.score`
measures. The backend runs it after :func:`solver.backtracking.backtrack_solve`.

Moves (each one whole, or not at all):

* **relocate** - one session outside a lab block to another start and room;
* **swap** - the starts of two such sessions that share a cohort or a teacher;
* **block** - a whole lab block to another start, all members together.

**Every move keeps every hard rule.** A move lifts its sessions and re-places
them through the backtracker's own checks: a start and room must be in the
session's static domain (:func:`solver.backtracking._build_initial_domains`:
teaching grid, contiguity, faculty availability, pinned faculty, cohort and
room slots - so a lab block never covers a year's lunch, D6/D7 - room type and
capacity, ``fixed_slot``), then :func:`solver.backtracking._placement_ok`
(conflict edges and room occupancy with sub-room lockout, every occupied
period). Pins are not sessions and never move; a session with a ``fixed_slot``,
and a lab block holding one, is never moved either. :func:`improve` checks its
input and its result with :func:`solver.validate.validate_solution`, which
shares no code with the search.

**Objective.** The penalty of the rules in ``quality_rules.yaml``, with their
weights: S-GAP per (cohort, day), S-B2B per (teacher, day) and
FAC_LOAD_IMBALANCE per teacher are kept apart, so a move recomputes only the
days, cohorts and teachers it touches (:class:`_Penalty`). S-LOAD16 counts who
teaches what, which no move changes, so it is a constant. The result is
re-scored by :func:`solver.scoring.score` and must match.

**Search.** Simulated annealing (Artificial Intelligence and Soft Computing,
CE303): a random move is always kept when it does not raise the penalty and
kept with probability ``exp(-delta / T)`` when it does, ``T`` cooling
geometrically from :data:`T_START` to :data:`T_END` over the move budget, so it
ends close to hill climbing (a one-gap loss kept 0.1% of the time); the best
timetable seen is returned. A block move trades places with what is in its way
(1-period sessions period for period, or a lab block starting exactly there), a
compound move in the spirit of Kempe-chain interchanges (DSGT). Tabu search was
not built: nothing measured that it would do better. Randomness is one
``random.Random(seed)`` and every choice is drawn from sorted lists, so a seed
and a move budget fix the result on any machine. ``time_limit_s`` is only a
safety cap: hitting it returns the best so far, which then depends on the
machine. Stdlib only.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from solver.backtracking import (
    _assign,
    _build_initial_domains,
    _new_state,
    _placement_ok,
    _room_is_available,
    _SolverState,
    _unassign,
)
from solver.graph import build_conflict_graph
from solver.scoring import load_rules, score
from solver.slots import SlotGrid, SlotId
from solver.validate import validate_solution

__all__ = ["MAX_MOVES", "SEED", "T_END", "T_START", "improve"]

# Default only, about 20 s on the real EVEN instance; the backend passes its own budget and
# the committed real run uses solver.benchmarks.real_solve.MOVES (docs/real-solve-even-2025-26.md).
MAX_MOVES = 200_000
SEED = 0
# Penalty points: T_START accepts a one-gap loss (2) 80% of the time, T_END about 0.1%.
T_START = 10.0
T_END = 0.3
P_BLOCK, P_SWAP = 0.3, 0.3  # share of block and swap moves; the rest relocate


class _Penalty:
    """S-GAP, S-B2B and FAC_LOAD_IMBALANCE raw counts, kept per day, cohort and teacher.

    The same measures as :mod:`solver.scoring`, split so that a change is
    recomputed only where it lands: a session's periods mark its cohort's
    sharing cohorts on that day, its teacher on that day and its teacher's
    week as dirty, and :meth:`settle` recomputes just those. Hash maps of
    period counts (Data Structures).
    """

    def __init__(self, edge_list: dict[str, Any], grid: SlotGrid) -> None:
        self.grid = grid
        self.adjacency = sorted(grid.adjacency)
        cohort_of = {s["id"]: s["cohort_id"] for s in edge_list["sessions"]}
        self.faculty_of = {s["id"]: s["faculty_id"] for s in edge_list["sessions"]}
        shares = {cohort: {cohort} for cohort in cohort_of.values()}
        for edge in edge_list["edges"]:
            if edge["reason"] == "COHORT":
                a, b = cohort_of[edge["u"]], cohort_of[edge["v"]]
                shares[a].add(b)
                shares[b].add(a)
        # sharing is symmetric, so a session's periods count for every cohort sharing its own
        self.watchers = {sid: sorted(shares[c]) for sid, c in cohort_of.items()}
        self.classes: dict[tuple[str, int], dict[int, int]] = {}  # (cohort, day) -> period -> n
        self.fixed: dict[tuple[str, int], set[int]] = {}  # pinned classes
        self.held: dict[tuple[str, int], set[int]] = {}  # cohort-only pins (a lunch)
        self.taught: dict[tuple[str, int], dict[int, str | None]] = {}  # None: a pin
        for pin in edge_list["pinned_occupancy"]:
            target = self.fixed if pin["faculty_ids"] or pin["room_ids"] else self.held
            for cohort in pin["cohort_ids"]:
                for watcher in sorted(shares.get(cohort, ())):
                    target.setdefault((watcher, pin["day"]), set()).add(pin["period"])
            if grid.is_teaching_period(pin["period"]):
                for fid in pin["faculty_ids"]:
                    self.taught.setdefault((fid, pin["day"]), {})[pin["period"]] = None
        self.gap = {(c, d): 0 for c in shares for d in range(grid.days)}
        self.b2b: dict[tuple[str, int], int] = {}
        self.spread: dict[str, int] = {}
        self.raw = {"S-GAP": 0, "S-B2B": 0, "FAC_LOAD_IMBALANCE": 0}
        self.dirty_gap = set(self.gap)
        self.dirty_b2b = set(self.taught)
        self.dirty_spread = {fid for fid, _ in self.taught}

    def _mark(self, sid: str, day: int) -> None:
        fid = self.faculty_of[sid]
        self.dirty_gap.update((c, day) for c in self.watchers[sid])
        self.dirty_b2b.add((fid, day))
        self.dirty_spread.add(fid)

    def place(self, sid: str, slots: tuple[SlotId, ...]) -> None:
        for slot in slots:
            for c in self.watchers[sid]:
                periods = self.classes.setdefault((c, slot.day), {})
                periods[slot.period] = periods.get(slot.period, 0) + 1
            self.taught.setdefault((self.faculty_of[sid], slot.day), {})[slot.period] = sid
        self._mark(sid, slots[0].day)

    def lift(self, sid: str, slots: tuple[SlotId, ...]) -> None:
        for slot in slots:
            for c in self.watchers[sid]:
                periods = self.classes[(c, slot.day)]
                periods[slot.period] -= 1
                if not periods[slot.period]:
                    del periods[slot.period]
            del self.taught[(self.faculty_of[sid], slot.day)][slot.period]
        self._mark(sid, slots[0].day)

    def _gap(self, key: tuple[str, int]) -> int:
        periods = self.classes.get(key, {}).keys() | self.fixed.get(key, set())
        if not periods:
            return 0
        lo, hi, held = min(periods), max(periods), self.held.get(key, set())
        return sum(lo < p < hi and p not in periods and p not in held
                   for p in self.grid.teaching_periods)

    def _b2b(self, key: tuple[str, int]) -> int:
        owners = self.taught.get(key, {})
        return sum(a in owners and b in owners and owners[a] != owners[b]
                   for a, b in self.adjacency)

    def _spread(self, fid: str) -> int:
        hours = [len(self.taught.get((fid, d), ())) for d in range(self.grid.days)]
        return max(hours) - min(hours)

    def settle(self) -> None:
        """Recompute the dirty parts and the three raw totals."""
        for parts, measure, dirty, rule in (
            (self.gap, self._gap, self.dirty_gap, "S-GAP"),
            (self.b2b, self._b2b, self.dirty_b2b, "S-B2B"),
            (self.spread, self._spread, self.dirty_spread, "FAC_LOAD_IMBALANCE"),
        ):
            for key in dirty:
                new = measure(key)
                self.raw[rule] += new - parts.get(key, 0)
                parts[key] = new
            dirty.clear()


def _room_choices(state: _SolverState) -> dict[str, dict[SlotId, list[str]]]:
    """Session -> start -> rooms its static domain allows there, sorted by id."""
    choices: dict[str, dict[SlotId, list[str]]] = {}
    for sid in sorted(state.domains):
        by_start: dict[SlotId, list[str]] = {}
        for start, room in sorted(state.domains[sid]):
            by_start.setdefault(start, []).append(room)
        choices[sid] = by_start
    return choices


def improve(
    payload: dict[str, Any],
    solution: dict[str, Any],
    *,
    max_moves: int = MAX_MOVES,
    seed: int = SEED,
    time_limit_s: float | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A ``solution.v2`` timetable at least as good as *solution*, still valid.

    Parameters
    ----------
    payload:
        The ``edge_list_v1`` instance *solution* solves.
    solution:
        A solved ``solution.v2`` payload, e.g. from
        :meth:`solver.backtracking.BacktrackResult.to_solution_v2_dict`.
    max_moves:
        Moves proposed, rejected and infeasible ones included. With *seed* it
        fixes the result.
    seed:
        Seed of the one random generator.
    time_limit_s:
        Wall-clock safety cap; ``None`` for none. If it stops the search the
        result is still valid and no worse, but no longer reproducible.
    stats:
        If given, filled with move counts: ``proposed``, ``infeasible``,
        ``accepted`` and ``improved`` (new best), the last two also per move
        kind, ``penalty_start``, ``penalty_best`` and ``stopped_by_time``.

    Returns
    -------
    dict
        The best timetable seen, scored by :func:`solver.scoring.score`;
        ``displaced`` is the input's, ``metadata.algorithm`` appends the local
        search to the input's, ``runtime_ms`` adds this run's wall clock, and
        ``slots_used`` is recounted. Its score is never below the input's.

    Raises
    ------
    ValueError
        If *solution* is not solved or breaks a hard rule of *payload*.
    """
    started = time.perf_counter()
    if solution["status"] != "solved":
        raise ValueError("improve needs a solved timetable")
    violations = validate_solution(payload, solution)
    if violations:
        raise ValueError(f"improve needs a valid timetable: {[v.to_dict() for v in violations]}")

    graph = build_conflict_graph(payload)
    state = _new_state(graph, payload)
    _build_initial_domains(state)
    rooms_at = _room_choices(state)
    penalty = _Penalty(payload, graph.grid)
    for item in sorted(solution["assignment"], key=lambda i: i["session_id"]):
        sid = item["session_id"]
        start = SlotId(item["day"], item["period"])
        slots = state.chains[(start, graph.sessions[sid].duration_periods)]
        _assign(state, sid, start, item["sub_room_id"] or item["room_id"], slots)
        penalty.place(sid, slots)
    penalty.settle()

    weights = {rule.id: rule.weight for rule in load_rules().rules}

    def total() -> float:
        return sum(weights[rule] * raw for rule, raw in penalty.raw.items())

    measured = score(payload, dict(state.slot_assignment))
    if any(penalty.raw.get(e["rule_id"], e["raw"]) != e["raw"] for e in measured["breakdown"]):
        raise AssertionError("incremental penalty disagrees with solver.scoring.score")
    constant = 100.0 - measured["score"] - total()  # S-LOAD16: no move changes who teaches what

    blocks = [
        b for b in sorted(state.lab_blocks, key=lambda b: b.id)
        if all(graph.sessions[sid].fixed_slot is None for sid in b.session_ids)
    ]
    block_starts = {
        b.id: sorted(set.intersection(*(set(rooms_at[sid]) for sid in b.session_ids)))
        for b in blocks
    }
    blocks = [b for b in blocks if len(block_starts[b.id]) > 1]
    block_of = {sid: b for b in blocks for sid in b.session_ids}
    starts_of = {sid: sorted(rooms_at[sid]) for sid in rooms_at}
    singles = [sid for sid in sorted(graph.sessions)
               if sid not in state.session_to_block and graph.sessions[sid].fixed_slot is None
               and len(starts_of[sid]) > 1]
    single_set = set(singles)
    partners = {
        sid: sorted(n for n in graph.neighbours(sid)
                    if n in single_set and graph.sessions[n].duration_periods
                    == graph.sessions[sid].duration_periods)
        for sid in singles
    }

    # slot -> sessions there: a quick clash filter before _placement_ok, which decides
    at: dict[SlotId, set[str]] = {}
    for sid, slots in state.occupied.items():
        for slot in slots:
            at.setdefault(slot, set()).add(sid)

    def lift(sid: str) -> tuple[str, SlotId, str]:
        old = (sid, state.slot_assignment[sid], state.room_assignment[sid])
        for slot in state.occupied[sid]:
            at[slot].discard(sid)
        penalty.lift(sid, state.occupied[sid])
        _unassign(state, sid)
        return old

    def put(sid: str, start: SlotId, room: str, slots: tuple[SlotId, ...]) -> None:
        _assign(state, sid, start, room, slots)
        for slot in slots:
            at.setdefault(slot, set()).add(sid)
        penalty.place(sid, slots)

    def undo(placed: list[str], old: list[tuple[str, SlotId, str]]) -> None:
        for sid in placed:
            lift(sid)
        for sid, start, room in old:
            put(sid, start, room, state.chains[(start, graph.sessions[sid].duration_periods)])

    def relocate(targets: list[tuple[str, SlotId]]) -> list[tuple[str, SlotId, str]] | None:
        """Move each session to its start, keeping its room if it can; None if one cannot go."""
        old = [lift(sid) for sid, _ in targets]
        placed: list[str] = []
        for (sid, start), (_, _, was) in zip(targets, old, strict=True):
            rooms = rooms_at[sid].get(start, [])
            chain = state.chains.get((start, graph.sessions[sid].duration_periods), ())
            if any(not graph.neighbours(sid).isdisjoint(at.get(slot, ())) for slot in chain):
                rooms = []
            for room in ([was] if was in rooms else []) + rooms:
                if not all(_room_is_available(state, room, slot) for slot in chain):
                    continue
                slots = _placement_ok(state, sid, start, room)
                if slots is not None:
                    put(sid, start, room, slots)
                    placed.append(sid)
                    break
            else:
                undo(placed, old)
                return None
        return old

    rng = random.Random(seed)
    counts: dict[str, Any] = {
        "proposed": 0, "infeasible": 0, "accepted": 0, "improved": 0,
        "accepted_by_kind": {"relocate": 0, "swap": 0, "block": 0},
        "improved_by_kind": {"relocate": 0, "swap": 0, "block": 0},
        "stopped_by_time": False,
    }
    current = best_penalty = start_penalty = total()
    best = (dict(state.slot_assignment), dict(state.room_assignment))
    deadline = None if time_limit_s is None else started + time_limit_s
    cooling = (T_END / T_START) ** (1.0 / max(1, max_moves))
    temperature = T_START

    for move in range(max_moves):
        if deadline is not None and move % 256 == 0 and time.perf_counter() > deadline:
            counts["stopped_by_time"] = True
            break
        counts["proposed"] += 1
        temperature *= cooling
        draw = rng.random()
        targets: list[tuple[str, SlotId]] = []
        if blocks and draw < P_BLOCK:
            kind, block = "block", rng.choice(blocks)
            start = rng.choice(block_starts[block.id])
            here = state.occupied[block.session_ids[0]]
            there = state.chains[(start, block.duration_periods)]
            if start != here[0]:
                targets = [(sid, start) for sid in block.session_ids]
                # what is in the way trades places: a 1-period session period for period,
                # a lab block starting exactly there as a whole; anything else, no move
                taken = set(block.session_ids)
                near = {n for sid in block.session_ids for n in graph.neighbours(sid)}
                for other in sorted(near - taken):
                    if other in taken or set(there).isdisjoint(state.occupied[other]):
                        continue
                    swap_with = block_of.get(other)
                    if other in single_set and graph.sessions[other].duration_periods == 1:
                        targets.append((other, here[there.index(state.occupied[other][0])]))
                    elif (swap_with is not None and state.occupied[other][0] == start
                          and swap_with.duration_periods == block.duration_periods):
                        targets += [(sid, here[0]) for sid in swap_with.session_ids]
                        taken.update(swap_with.session_ids)
                    else:
                        targets = []
                        break
        elif singles and draw < P_BLOCK + P_SWAP:
            kind, sid = "swap", rng.choice(singles)
            if partners[sid]:
                other = rng.choice(partners[sid])
                a, b = state.slot_assignment[sid], state.slot_assignment[other]
                if a != b and b in rooms_at[sid] and a in rooms_at[other]:
                    targets = [(sid, b), (other, a)]
        elif singles:
            kind, sid = "relocate", rng.choice(singles)
            start = rng.choice(starts_of[sid])
            if start != state.slot_assignment[sid]:
                targets = [(sid, start)]
        old = relocate(targets) if targets else None
        if old is None:
            counts["infeasible"] += 1
            continue
        penalty.settle()
        delta = total() - current
        if delta > 0 and rng.random() >= math.exp(-delta / temperature):
            undo([sid for sid, _ in targets], old)
            penalty.settle()
            continue
        current += delta
        counts["accepted"] += 1
        counts["accepted_by_kind"][kind] += 1
        if current < best_penalty - 1e-9:
            best_penalty = current
            best = (dict(state.slot_assignment), dict(state.room_assignment))
            counts["improved"] += 1
            counts["improved_by_kind"][kind] += 1

    starts, rooms = best
    assignment = []
    for sid in sorted(starts):
        room = state.rooms[rooms[sid]]
        assignment.append({
            "session_id": sid,
            "day": starts[sid].day,
            "period": starts[sid].period,
            "room_id": room.parent_room_id or room.id,
            "sub_room_id": room.id if room.parent_room_id else None,
        })
    quality = score(payload, starts)
    if not math.isclose(quality["score"], 100.0 - constant - best_penalty, abs_tol=1e-6):
        raise AssertionError("incremental penalty disagrees with solver.scoring.score")
    meta = solution["metadata"]
    result = {
        "schema_version": "solution.v2",
        "status": "solved",
        "assignment": assignment,
        "quality": quality,
        "displaced": list(solution.get("displaced", [])),
        "metadata": {
            **meta,
            "algorithm": f"{meta['algorithm']} + local-search(simulated-annealing, "
                         f"moves={counts['proposed']}, seed={seed})",
            "runtime_ms": meta["runtime_ms"] + (time.perf_counter() - started) * 1000,
            "slots_used": len({
                slot for sid, start in starts.items()
                for slot in state.chains[(start, graph.sessions[sid].duration_periods)]
            }),
        },
    }
    violations = validate_solution(payload, result)
    if violations:
        raise AssertionError(f"local search broke a hard rule: {[v.to_dict() for v in violations]}")
    if stats is not None:
        stats.update(counts, penalty_start=start_penalty + constant,
                     penalty_best=best_penalty + constant)
    return result
