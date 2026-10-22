"""Quality improvement by local search (S12g): a valid timetable in, a better one out.

:func:`improve` takes a solved timetable - normally :func:`solver.backtracking.backtrack_solve`'s,
which satisfies every hard constraint and optimises nothing soft - and walks from it through
valid timetables only, keeping the best one it sees under :func:`solver.scoring.score`.

**Moves.** Each step proposes one change (Artificial Intelligence and Soft Computing,
CE303: neighbourhoods for local search over a constraint problem). A *unit* is a session
outside any lab block, or a whole lab block, whose members always move together:

* move one session outside any lab block to another start and room;
* swap the starts of two such sessions that share a cohort or a teacher;
* move a whole lab block: every member to one new start, each in a room of its own;
* a Kempe-chain interchange of two starts (:meth:`_Search._interchange`);
* aimed at a student gap: a unit holding that cohort's students is moved onto the idle
  period (or anywhere), either along a Kempe chain or by ejecting the one or two sessions
  in its way into the slots it leaves (:meth:`_Search._gap_directed`, :meth:`_Search._eject`).

A proposal is checked by the backtracker's own placement checks, which hold the same hard
rules as :mod:`solver.validate`: a start must be in the session's initial domain (grid,
faculty unavailability, pinned faculty and cohort slots - a year's lunch among them, so a
lab block never covers it -, room type, capacity, pinned rooms, fixed slots), and
:func:`solver.backtracking._placement_ok`'s checks cover every occupied period against every
conflict neighbour and the room, its parent and its sub-rooms. A proposal that fails is
undone at once; nothing invalid is ever scored. Pins are not sessions and never move;
a session with a ``fixed_slot``, or a lab block with such a member, is never proposed.
The result is checked again by :func:`solver.validate.validate_solution` before it is
returned.

**Objective, computed incrementally.** The penalty is ``100 - score``: weights from
``quality_rules.yaml`` times the raw counts of the four D34 rules. A move changes only the
days it leaves and enters, the cohorts sharing students with the moved sessions and their
teachers, so only those (cohort, day) gap counts, (teacher, day) back-to-back counts and
teachers' daily-load ranges are recomputed (Data Structures: hash maps keyed by the affected
units). S-LOAD16 counts who teaches what, which no move changes (FACULTY edges keep a
teacher to one session a slot, so their slot count is their load). The raw counts are
integers, so the penalty is recomputed from them every time and never drifts; at the start
and at the end they are checked against :func:`solver.scoring.score`.

**Search.** Simulated annealing (CE303): a move that does not worsen the penalty is always
taken, a worse one with probability ``exp(-delta / T)``; ``T`` cools geometrically from
:data:`T_START` over :data:`STAGES` equal stages of the budget, so the last stretch is
plain hill climbing. The best timetable seen is kept, and it replaces the input only when
strictly better, so the score returned is never below the input's. Tabu search and
restarts from the best were tried and did worse on the real instance; neither is kept
(``docs/real-solve-even-2025-26.md``).

**Reproducible.** Every choice comes from ``random.Random(seed)`` over lists in sorted
order (no iteration over a set of strings, whose order changes per process), and ``exp``
and the temperatures are computed with + - * / only (:func:`_exp`), which IEEE 754 rounds
the same on every machine; the library ``exp`` and ``**`` may differ in the last bit. The
search stops after
``max_moves`` proposals, so a fixed seed and budget give the same timetable everywhere.
``time_limit_s`` is a safety cap only: a run it cuts short depends on the machine.

Stdlib and ``solver.*`` only (CONTEXT.md rules 1-3); no learned model anywhere.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from solver.backtracking import (
    LabBlock,
    _assign,
    _build_initial_domains,
    _clashes_with_assigned,
    _new_state,
    _occupied_slots,
    _room_is_available,
    _SolverState,
    _unassign,
)
from solver.graph import build_conflict_graph
from solver.scoring import load_rules, score
from solver.slots import SlotId
from solver.validate import validate_solution

__all__ = ["DEFAULT_MAX_MOVES", "improve"]

#: Proposals per run unless the caller says otherwise: about 14 s on the real EVEN instance
#: (docs/real-solve-even-2025-26.md).
DEFAULT_MAX_MOVES = 300_000
#: Annealing temperature, in penalty points: T_START, then times COOLING at each of STAGES
#: equal stages of the budget (geometric cooling, 15 down to 0.05). At 15 a move costing a
#: division gap (5 cohorts x 2 = 10 points) is taken half the time; at 0.05 never.
#: These and the probabilities below were chosen on the real instance (S12g sweeps).
T_START = 15.0
COOLING = 0.944
STAGES = 100
#: Probability that a proposal is aimed at a student gap, and that such a proposal ejects
#: what is in the way instead of growing a Kempe chain.
P_GAP = 0.6
P_EJECT = 0.8
#: Otherwise: probability of a Kempe-chain interchange, and of a swap; else one session or
#: one lab block moves.
P_KEMPE = 0.3
P_SWAP = 0.2
#: A Kempe chain longer than this many sessions is not tried.
KEMPE_MAX = 24
_CLOCK_EVERY = 256  # proposals between wall-clock checks


def _exp(x: float) -> float:
    """``e ** x`` for ``x <= 0`` with + - * / only, so every IEEE 754 machine agrees.

    Halve ``x`` until it is at most 1/2 in size, sum the Taylor series there (terms below
    2**-60 of the first), then square back. Reproducibility, not speed, is the point.
    """
    if x < -60.0:
        return 0.0
    halvings = 0
    while x < -0.5:
        x /= 2.0
        halvings += 1
    term, total, n = 1.0, 1.0, 0
    while abs(term) > 1e-18:
        n += 1
        term = term * x / n
        total += term
    for _ in range(halvings):
        total *= total
    return total


# ---------------------------------------------------------------------------
# Incremental quality: the four D34 rules, per affected unit
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Quality:
    """The raw counts of :mod:`solver.scoring`, kept per unit so a move updates a few."""

    teaching: tuple[int, ...]
    adjacency: tuple[tuple[int, int], ...]
    days: int
    cohort_of: dict[str, str]
    faculty_of: dict[str, str]
    shares: dict[str, tuple[str, ...]]  # cohort -> cohorts sharing students, itself included
    fixed_class: dict[str, set[SlotId]]  # cohort -> slots a pin with a teacher or room gives
    fixed_held: dict[str, set[SlotId]]  # cohort -> slots a cohort-only pin (a lunch) holds
    occ: dict[str, dict[SlotId, int]]  # cohort -> slot -> sessions of that cohort there
    taught: dict[str, dict[SlotId, str | None]]  # faculty -> slot -> session, None for a pin
    weights: dict[str, float]
    load: int  # S-LOAD16 raw: fixed by who teaches what
    gap: dict[tuple[str, int], int] = field(default_factory=dict)
    b2b: dict[tuple[str, int], int] = field(default_factory=dict)
    spread: dict[str, int] = field(default_factory=dict)
    totals: list[int] = field(default_factory=lambda: [0, 0, 0])  # gaps, b2b, spread

    def raw(self) -> dict[str, int]:
        """Each rule's raw count, as in the ``raw`` fields of :func:`solver.scoring.score`."""
        return {"S-GAP": self.totals[0], "S-B2B": self.totals[1],
                "S-LOAD16": self.load, "FAC_LOAD_IMBALANCE": self.totals[2]}

    def penalty(self) -> float:
        """``100 - score``: weight times raw, summed in the rule file's order."""
        raw = self.raw()
        return sum(weight * raw[rule] for rule, weight in self.weights.items())

    def _gap(self, cohort: str, day: int) -> int:
        return len(self.idle(cohort, day))

    def idle(self, cohort: str, day: int) -> list[int]:
        """The idle teaching periods of *cohort* on *day*, as S-GAP counts them."""
        bounds = {s.period for s in self.fixed_class[cohort] if s.day == day}
        for other in self.shares[cohort]:
            bounds.update(s.period for s, n in self.occ[other].items() if n and s.day == day)
        if not bounds:
            return []
        lo, hi = min(bounds), max(bounds)
        return [p for p in self.teaching if lo < p < hi and p not in bounds
                and SlotId(day, p) not in self.fixed_held[cohort]]

    def _b2b(self, fid: str, day: int) -> int:
        slots = self.taught.get(fid, {})
        count = 0
        for a, b in self.adjacency:
            x, y = SlotId(day, a), SlotId(day, b)
            if x in slots and y in slots and slots[x] != slots[y]:
                count += 1
        return count

    def _spread(self, fid: str) -> int:
        hours = [0] * self.days
        for slot in self.taught.get(fid, {}):
            hours[slot.day] += 1
        return max(hours) - min(hours)

    def lift(self, sid: str, slots: tuple[SlotId, ...]) -> None:
        """Take a placed session out of the counts."""
        occ, taught = self.occ[self.cohort_of[sid]], self.taught[self.faculty_of[sid]]
        for s in slots:
            occ[s] -= 1
            del taught[s]

    def drop(self, sid: str, slots: tuple[SlotId, ...]) -> None:
        """Put a placed session into the counts."""
        occ, taught = self.occ[self.cohort_of[sid]], self.taught[self.faculty_of[sid]]
        for s in slots:
            occ[s] = occ.get(s, 0) + 1
            taught[s] = sid

    def units(self, moved: list[tuple[str, tuple[SlotId, ...]]]) -> tuple[set[Any], ...]:
        """The (cohort, day), (faculty, day) and faculty units these placements touch."""
        cohort_days: set[tuple[str, int]] = set()
        faculty_days: set[tuple[str, int]] = set()
        faculty: set[str] = set()
        for sid, slots in moved:
            fid = self.faculty_of[sid]
            faculty.add(fid)
            for day in {s.day for s in slots}:
                faculty_days.add((fid, day))
                cohort_days.update((c, day) for c in self.shares[self.cohort_of[sid]])
        return cohort_days, faculty_days, faculty

    def recount(self, units: tuple[set[Any], ...]) -> tuple[Any, ...]:
        """Recompute the given units; returns what :meth:`restore` needs to undo it."""
        cohort_days, faculty_days, faculty = units
        saved = ({k: self.gap[k] for k in cohort_days}, {k: self.b2b[k] for k in faculty_days},
                 {k: self.spread[k] for k in faculty}, list(self.totals))
        for k in cohort_days:
            new = self._gap(*k)
            self.totals[0] += new - self.gap[k]
            self.gap[k] = new
        for k in faculty_days:
            new = self._b2b(*k)
            self.totals[1] += new - self.b2b[k]
            self.b2b[k] = new
        for f in faculty:
            new = self._spread(f)
            self.totals[2] += new - self.spread[f]
            self.spread[f] = new
        return saved

    def restore(self, saved: tuple[Any, ...]) -> None:
        self.gap.update(saved[0])
        self.b2b.update(saved[1])
        self.spread.update(saved[2])
        self.totals = saved[3]


def _quality(payload: dict[str, Any], state: _SolverState) -> _Quality:
    """Counts for the timetable placed in *state*, read as :mod:`solver.scoring` reads it."""
    grid = state.graph.grid
    sessions = payload["sessions"]
    cohort_of = {s["id"]: s["cohort_id"] for s in sessions}
    shares: dict[str, set[str]] = {c: {c} for c in cohort_of.values()}
    for edge in payload["edges"]:
        if edge["reason"] == "COHORT":
            a, b = cohort_of[edge["u"]], cohort_of[edge["v"]]
            shares[a].add(b)
            shares[b].add(a)
    pin_class: dict[str, set[SlotId]] = {}
    pin_held: dict[str, set[SlotId]] = {}
    taught: dict[str, dict[SlotId, str | None]] = {s["faculty_id"]: {} for s in sessions}
    for pin in payload["pinned_occupancy"]:
        slot = grid.slot(pin["day"], pin["period"])
        target = pin_class if pin["faculty_ids"] or pin["room_ids"] else pin_held
        for c in pin["cohort_ids"]:
            target.setdefault(c, set()).add(slot)
        if grid.is_teaching_period(slot.period):
            for fid in pin["faculty_ids"]:
                taught.setdefault(fid, {})[slot] = None
    rules = load_rules()
    q = _Quality(
        teaching=grid.teaching_periods,
        adjacency=tuple(sorted(grid.adjacency)),
        days=grid.days,
        cohort_of=cohort_of,
        faculty_of={s["id"]: s["faculty_id"] for s in sessions},
        shares={c: tuple(sorted(o)) for c, o in shares.items()},
        fixed_class={c: set().union(*(pin_class.get(o, ()) for o in others))
                     for c, others in shares.items()},
        fixed_held={c: set().union(*(pin_held.get(o, ()) for o in others))
                    for c, others in shares.items()},
        occ={c: {} for c in shares},
        taught=taught,
        weights={r.id: r.weight for r in rules.rules},
        load=0,
    )
    for sid, slots in state.occupied.items():
        q.drop(sid, slots)
    threshold = next(r.parameters["threshold_hours"] for r in rules.rules if r.id == "S-LOAD16")
    q.load = sum(1 for slots in taught.values() if len(slots) > threshold)
    q.gap = {(c, d): 0 for c in shares for d in range(grid.days)}
    q.b2b = {(f, d): 0 for f in taught for d in range(grid.days)}
    q.spread = dict.fromkeys(taught, 0)
    q.recount((set(q.gap), set(q.b2b), set(q.spread)))
    return q


def _raw(quality: dict[str, Any]) -> dict[str, int]:
    return {entry["rule_id"]: entry["raw"] for entry in quality["breakdown"]}


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Search:
    state: _SolverState
    quality: _Quality
    rng: random.Random
    # session -> start -> rooms its initial domain allows there, by id
    rooms_at: dict[str, dict[SlotId, list[str]]]
    singles: list[str]  # movable sessions outside any lab block, by id
    blocks: list[LabBlock]  # movable lab blocks, by id
    block_starts: dict[str, list[SlotId]]  # block id -> starts every member allows
    partners: dict[str, list[str]]  # single -> singles sharing its cohort or teacher
    unit_of: dict[str, tuple[str, ...]]  # movable session -> itself, or its lab block's members
    neighbours: dict[str, tuple[str, ...]]  # session -> conflict neighbours, by id
    # cohort -> the movable units holding any of its students, by first id
    units_of_cohort: dict[str, list[tuple[str, ...]]]
    at_start: dict[SlotId, set[str]]  # start -> sessions starting there

    def _put(self, sid: str, start: SlotId, room: str, slots: tuple[SlotId, ...]) -> None:
        _assign(self.state, sid, start, room, slots)
        self.at_start.setdefault(start, set()).add(sid)

    def _take(self, sid: str) -> None:
        self.at_start[self.state.slot_assignment[sid]].discard(sid)
        _unassign(self.state, sid)

    def _place(self, sid: str, start: SlotId, prefer: str | None) -> bool:
        """Put *sid* at *start* in the first room that passes every check, *prefer* first.

        The checks of :func:`solver.backtracking._placement_ok`, with the conflict
        neighbours checked once rather than once per room.
        """
        st = self.state
        slots = _occupied_slots(st, sid, start)
        if slots is None or _clashes_with_assigned(st, sid, slots):
            return False
        for room in sorted(self.rooms_at[sid].get(start, []), key=lambda r: r != prefer):
            if all(_room_is_available(st, room, s) for s in slots):
                self._put(sid, start, room, slots)
                return True
        return False

    def _try(self, plan: list[tuple[str, SlotId]]) -> tuple[Any, ...] | None:
        """Re-place every session of *plan* at its new start, in order.

        Returns the undo record, or None (with everything put back) when a session finds
        no room that passes the checks. Rooms are first fit, the old room first.
        shortcut: a lab block's rooms are chosen greedily member by member, so a start
        whose only room tuple needs another order is missed; search room tuples like
        backtracking._gen_room_tuples if lab moves are seen failing for rooms alone.
        """
        st = self.state
        old = [(sid, st.slot_assignment[sid], st.room_assignment[sid], st.occupied[sid])
               for sid, _ in plan]
        for sid, *_ in old:
            self._take(sid)
        for i, (sid, start) in enumerate(plan):
            if not self._place(sid, start, old[i][2]):
                for done, _ in plan[:i]:
                    self._take(done)
                for item in old:
                    self._put(*item)
                return None
        q = self.quality
        moved = [(sid, slots) for sid, _, _, slots in old]
        for sid, slots in moved:
            q.lift(sid, slots)
        new = [(sid, st.occupied[sid]) for sid, _ in plan]
        for sid, slots in new:
            q.drop(sid, slots)
        before, after = q.units(moved), q.units(new)
        saved = q.recount(tuple(a | b for a, b in zip(before, after, strict=True)))
        return old, new, saved

    def _undo(self, record: tuple[Any, ...]) -> None:
        old, new, saved = record
        q = self.quality
        for sid, slots in new:
            self._take(sid)
            q.lift(sid, slots)
        for sid, start, room, slots in old:
            self._put(sid, start, room, slots)
            q.drop(sid, slots)
        q.restore(saved)

    def _kempe(self) -> tuple[Any, ...] | None:
        """Interchange two starts along a Kempe chain (DSGT, CE201; CE303 local search).

        Take a random unit (a session or a lab block) at start ``t1`` and a start ``t2``
        it allows. The chain is the connected part of the conflict graph, grown from that
        unit, whose sessions start at ``t1`` or ``t2``, a lab block joining whole. Every
        chain session at ``t1`` moves to ``t2`` and every one at ``t2`` to ``t1``: the
        two-colour interchange of graph colouring, which a single move or a pairwise swap
        cannot make when three or more sessions are in the way. A chain reaching a session
        that never moves (a fixed slot) or longer than :data:`KEMPE_MAX` is not tried.
        """
        rng = self.rng
        pick = rng.randrange(len(self.singles) + len(self.blocks))
        first = (self.unit_of[self.singles[pick]] if pick < len(self.singles)
                 else self.blocks[pick - len(self.singles)].session_ids)
        here = self.state.slot_assignment[first[0]]
        options = [s for s in self._starts(first) if s != here]
        if not options:
            return None
        return self._interchange(first, options[rng.randrange(len(options))])

    def _starts(self, unit: tuple[str, ...]) -> list[SlotId]:
        """The starts a unit allows: a session's domain starts, or a block's shared ones."""
        if len(unit) == 1 and unit[0] not in self.state.session_to_block:
            return list(self.rooms_at[unit[0]])
        return self.block_starts[self.state.session_to_block[unit[0]].id]

    def _gap_directed(self) -> tuple[Any, ...] | None:
        """A move aimed at a student gap (CE303: a guided neighbourhood).

        Pick an idle period of some cohort and day, then a unit holding students of that
        cohort: half the time the unit is brought to a start that covers the idle period,
        half the time it is sent to any start it allows; it gets there by ejecting what is
        in the way (:meth:`_eject`, probability :data:`P_EJECT`) or along a Kempe chain.
        Random proposals almost never hit the one start that closes a gap in a week this
        full; these aim at it.
        """
        rng, q = self.rng, self.quality
        gaps = [k for k, n in q.gap.items() if n]
        if not gaps:
            return None
        cohort, day = gaps[rng.randrange(len(gaps))]
        units = self.units_of_cohort.get(cohort, [])
        if not units:
            return None
        unit = units[rng.randrange(len(units))]
        here = self.state.slot_assignment[unit[0]]
        if rng.random() < 0.5:
            idle = q.idle(cohort, day)
            period = idle[rng.randrange(len(idle))]
            options = [s for s in self._starts(unit) if s != here and s.day == day and period in
                       [x.period for x in _occupied_slots(self.state, unit[0], s) or ()]]
        else:
            options = [s for s in self._starts(unit) if s != here]
        if not options:
            return None
        target = options[rng.randrange(len(options))]
        if rng.random() < P_EJECT:
            return self._eject(unit, target)
        return self._interchange(unit, target)

    def _interchange(self, first: tuple[str, ...], t2: SlotId) -> tuple[Any, ...] | None:
        """Move *first* to *t2* along the Kempe chain of its start and *t2*."""
        st = self.state
        t1 = st.slot_assignment[first[0]]
        there = self.at_start.get(t1, set()) | self.at_start.get(t2, set())
        chain, seen = list(first), set(first)
        for sid in chain:  # grows while it is walked: breadth-first search
            for n in self.neighbours[sid]:
                if n in seen or n not in there:
                    continue
                unit = self.unit_of.get(n)
                if unit is None or len(chain) + len(unit) > KEMPE_MAX:
                    return None
                chain.extend(unit)
                seen.update(unit)
        plan = [(sid, t2 if st.slot_assignment[sid] == t1 else t1) for sid in chain]
        if any(start not in self.rooms_at[sid] for sid, start in plan):
            return None
        return self._try(plan)

    def _eject(self, first: tuple[str, ...], t2: SlotId) -> tuple[Any, ...] | None:
        """Move *first* to *t2*; the sessions in its way take the slots it leaves.

        An ejection chain of length one (CE303 local search): every placed conflict
        neighbour the new placement would overlap must be a movable session outside any
        lab block, at most two of them, and each moves to a start among the slots *first*
        vacates, in slot order. So a lab block and one or two lectures trade places, which
        a Kempe chain cannot when their durations differ.
        """
        st = self.state
        new = set(_occupied_slots(st, first[0], t2) or ())
        ejected = sorted({n for sid in first for n in self.neighbours[sid] if n not in first
                          and not new.isdisjoint(st.occupied[n])})
        if len(ejected) > 2 or any(self.unit_of.get(n) != (n,) for n in ejected):
            return None
        vacated = sorted(st.occupied[first[0]])
        plan = [(sid, t2) for sid in first]
        for n in ejected:
            free = [v for v in vacated if v in self.rooms_at[n]]
            if not free:
                return None
            plan.append((n, free[0]))
            vacated.remove(free[0])
        return self._try(plan)

    def propose(self) -> tuple[str, tuple[Any, ...] | None]:
        """One random proposal, applied if it is valid: (kind, undo record or None)."""
        rng, st = self.rng, self.state
        if not self.singles and not self.blocks:
            return "move", None  # nothing may move: every session is fixed
        draw = rng.random()
        if draw < P_GAP:
            return "gap", self._gap_directed()
        draw = rng.random()
        if draw < P_KEMPE:
            return "kempe", self._kempe()
        if self.singles and draw < P_KEMPE + P_SWAP:
            a = self.singles[rng.randrange(len(self.singles))]
            if not self.partners[a]:
                return "swap", None
            b = self.partners[a][rng.randrange(len(self.partners[a]))]
            sa, sb = st.slot_assignment[a], st.slot_assignment[b]
            if sa == sb or sb not in self.rooms_at[a] or sa not in self.rooms_at[b]:
                return "swap", None
            return "swap", self._try([(a, sb), (b, sa)])
        pick = rng.randrange(len(self.singles) + len(self.blocks))
        if pick < len(self.singles):
            sid = self.singles[pick]
            starts = [s for s in self.rooms_at[sid] if s != st.slot_assignment[sid]]
            if not starts:
                return "move", None
            return "move", self._try([(sid, starts[rng.randrange(len(starts))])])
        block = self.blocks[pick - len(self.singles)]
        here = st.slot_assignment[block.session_ids[0]]
        starts = [s for s in self.block_starts[block.id] if s != here]
        if not starts:
            return "lab_block", None
        start = starts[rng.randrange(len(starts))]
        return "lab_block", self._try([(sid, start) for sid in block.session_ids])


def _search(payload: dict[str, Any], solution: dict[str, Any], seed: int) -> _Search:
    graph = build_conflict_graph(payload)
    state = _new_state(graph, payload)
    _build_initial_domains(state)
    for item in solution["assignment"]:
        sid = item["session_id"]
        start = SlotId(item["day"], item["period"])
        room = item["sub_room_id"] or item["room_id"]
        slots = _occupied_slots(state, sid, start)
        assert slots is not None  # the input passed validate_solution
        _assign(state, sid, start, room, slots)

    rooms_at: dict[str, dict[SlotId, list[str]]] = {}
    for sid, domain in state.domains.items():
        by_start: dict[SlotId, list[str]] = {}
        for start, room in domain:
            by_start.setdefault(start, []).append(room)
        rooms_at[sid] = {s: sorted(by_start[s]) for s in sorted(by_start)}

    sessions = graph.sessions
    singles = sorted(sid for sid, s in sessions.items()
                     if sid not in state.session_to_block and s.fixed_slot is None)
    blocks = sorted((b for b in state.lab_blocks if b.session_ids and all(
        sessions[sid].fixed_slot is None for sid in b.session_ids)), key=lambda b: b.id)
    block_starts = {
        b.id: sorted(set.intersection(*(set(rooms_at[sid]) for sid in b.session_ids)))
        for b in blocks
    }
    partners = {
        a: [b for b in singles if b != a and (
            sessions[a].cohort_id == sessions[b].cohort_id
            or sessions[a].faculty_id == sessions[b].faculty_id)]
        for a in singles
    }
    unit_of = {sid: (sid,) for sid in singles}
    unit_of.update({sid: b.session_ids for b in blocks for sid in b.session_ids})
    neighbours = {sid: tuple(sorted(graph.adjacency[sid])) for sid in sessions}
    quality = _quality(payload, state)
    units_of_cohort = {
        c: sorted({u for sid, u in unit_of.items() if sessions[sid].cohort_id in others})
        for c, others in quality.shares.items()
    }
    at_start: dict[SlotId, set[str]] = {}
    for sid, start in state.slot_assignment.items():
        at_start.setdefault(start, set()).add(sid)
    return _Search(state, quality, random.Random(seed), rooms_at, singles, blocks,
                   block_starts, partners, unit_of, neighbours, units_of_cohort, at_start)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def improve(
    payload: dict[str, Any],
    solution: dict[str, Any],
    *,
    max_moves: int = DEFAULT_MAX_MOVES,
    seed: int = 0,
    time_limit_s: float | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A ``solution.v2`` timetable at least as good as *solution*, never invalid.

    Call it after :func:`solver.backtracking.backtrack_solve` (Track B's backend does).
    See the module docstring for the moves, the objective and the search.

    Parameters
    ----------
    payload:
        The edge-list payload (``edge_list_v1``) *solution* solves. Not modified.
    solution:
        A solved ``solution.v1`` or ``solution.v2`` payload; only its ``assignment``,
        ``displaced`` and ``metadata`` are read. Not modified.
    max_moves:
        Proposals to make, valid or not: the stopping rule, so a fixed seed and budget
        give the same timetable on every machine.
    seed:
        Seed of the search's ``random.Random``.
    time_limit_s:
        Safety cap on wall-clock time; ``None`` for none. A run it stops early is not
        reproducible.
    stats:
        If given, filled with what the run did: proposals, valid proposals and accepted
        moves per kind, improvements, the proposal that found the best, the penalty
        before and after, and whether the time cap stopped it.

    Returns
    -------
    dict
        ``solution.v2``, status ``solved``: the best timetable seen, scored by
        :func:`solver.scoring.score`; ``displaced`` as given; ``metadata`` as given but
        for ``algorithm`` (the input's, then this step with its seed and budget),
        ``runtime_ms`` (the input's plus this step's) and ``slots_used``.

    Raises
    ------
    ValueError
        If *solution* is not solved, or breaks a hard constraint of *payload*.
    """
    started = time.perf_counter()
    if solution.get("status") != "solved":
        raise ValueError("improve needs a solved timetable to start from")
    violations = validate_solution(payload, solution)
    if violations:
        raise ValueError(f"the timetable to improve is not valid: {violations[0].detail}")
    if max_moves < 0:
        raise ValueError(f"max_moves must be at least 0, got {max_moves}")

    search = _search(payload, solution, seed)
    st, q = search.state, search.quality
    start_starts = dict(st.slot_assignment)
    if _raw(score(payload, start_starts)) != q.raw():
        raise RuntimeError("incremental quality disagrees with solver.scoring at the start")

    deadline = None if time_limit_s is None else started + time_limit_s
    temperatures = [T_START]
    for _ in range(STAGES - 1):  # repeated multiplication: IEEE 754 rounds it alike everywhere
        temperatures.append(temperatures[-1] * COOLING)
    current = best = q.penalty()
    best_raw = q.raw()
    best_place = (dict(st.slot_assignment), dict(st.room_assignment))
    kinds = ("move", "swap", "lab_block", "kempe", "gap")
    counts: dict[str, list[int]] = {k: [0, 0, 0] for k in kinds}
    improvements, best_at, timed_out, done = 0, 0, False, 0
    for done in range(1, max_moves + 1):
        if deadline is not None and done % _CLOCK_EVERY == 0 and time.perf_counter() > deadline:
            timed_out, done = True, done - 1
            break
        temperature = temperatures[(done - 1) * STAGES // max_moves]
        kind, record = search.propose()
        counts[kind][0] += 1
        if record is None:
            continue
        counts[kind][1] += 1
        penalty = q.penalty()
        if penalty <= current or search.rng.random() < _exp((current - penalty) / temperature):
            counts[kind][2] += 1
            current = penalty
            if current < best:
                best, best_raw, best_at, improvements = current, q.raw(), done, improvements + 1
                best_place = (dict(st.slot_assignment), dict(st.room_assignment))
        else:
            search._undo(record)

    starts, rooms = best_place
    parent = {rid: room.parent_room_id for rid, room in st.rooms.items()}
    assignment = [
        {"session_id": sid, "day": slot.day, "period": slot.period,
         "room_id": parent[rooms[sid]] or rooms[sid],
         "sub_room_id": rooms[sid] if parent[rooms[sid]] else None}
        for sid, slot in sorted(starts.items())
    ]
    quality = score(payload, starts)
    if _raw(quality) != best_raw:
        raise RuntimeError("incremental quality disagrees with solver.scoring at the end")
    occupied = {s for sid, start in starts.items() for s in _occupied_slots(st, sid, start) or ()}
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
                         f"seed={seed}, moves={max_moves})",
            "runtime_ms": meta["runtime_ms"] + (time.perf_counter() - started) * 1000,
            "slots_used": len(occupied),
        },
    }
    violations = validate_solution(payload, result)
    if violations:
        raise RuntimeError(f"local search produced an invalid timetable: {violations[0].detail}")
    if stats is not None:
        stats.update({
            "proposals": done,
            "by_kind": {k: dict(zip(("proposed", "valid", "accepted"), v, strict=True))
                        for k, v in counts.items()},
            "improvements": improvements,
            "best_at_proposal": best_at,
            "penalty_before": 100.0 - score(payload, start_starts)["score"],
            "penalty_after": best,
            "timed_out": timed_out,
        })
    return result
