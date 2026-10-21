"""Explain an infeasible instance: a minimal conflicting set and a verified fix (S14b).

:func:`explain` takes an instance already proven infeasible (a pre-solve
certificate or an exhausted search, ROADMAP D21) and returns its ``solution.v2``
diagnosis with ``method = "mus"`` when the set is proven minimal.

**Constraint groups.** A member is one piece of the ``edge_list_v1`` payload
that can be switched off as data:

* ``pin.<i>`` - ``pinned_occupancy[i]``, one cell (PINNED_BLOCK). The edge list
  gives pins no id; ``display.json`` ``pins[i]`` names entry ``i`` (D41).
* ``unavailable.<faculty>.<day>`` - one faculty member's unavailable slots on
  one day (FACULTY_UNAVAILABLE).
* ``fixed.<session>`` - a ``fixed_slot`` (FIXED_SLOT).
* ``lab_block.<id>`` - a lab block's members starting together (LAB_CONTIGUITY).
* ``faculty_clash.<f>[.<g>]`` / ``cohort_clash.<c>[.<d>]`` - the FACULTY or
  COHORT edges between the sessions of one faculty (cohort) or one pair
  (FACULTY_CLASH, COHORT_CLASH; ROOM edges likewise, by session pair).
* ``room_capacity.<room>`` (ROOM_CAPACITY) and ``room_type.<room>`` for a
  non-lab room (ROOM_TYPE).
* ``change`` - in a repair, the change itself (:func:`solver.repair.apply_change`).

Everything else is background and always holds: the sessions and their
lengths, the grid, and one session per room or sub-room per period.

**Checks.** A check solves the instance with only some groups kept:
pre-solve first (the fast check), then backtracking with a node budget
(:data:`MUS_NODES`, the full check). Before searching from scratch it reuses a
known timetable (the one being repaired, or an earlier witness): as it is if
it breaks no kept group, else repaired locally with only the sessions in the
way free. Any timetable taken as proof passes
:func:`solver.validate.validate_solution`. The outcome is proven infeasible,
feasible, or unknown when the budget runs out - and unknown is never read as
either (ROADMAP D33).

**Deletion-based extraction** (deletion filter, Chinneck and Dravnieks 1991;
constraint satisfaction, Artificial Intelligence and Soft Computing CE303).
Start from a set proven infeasible and try to remove members: a removal whose
check is still infeasible is kept, anything else (feasible or unknown) puts the
members back. Chunks go first, halving down to single members - the
divide-and-conquer of QuickXplain (Junker 2004) - with pre-solve alone as their
check, and the last pass tries every remaining member alone with the full
check. Room groups get their own pass after the rest: without them every room
suits every session and each check is slow. Removing constraints never turns a feasible instance
infeasible, so a member whose removal was feasible stays necessary as the set
shrinks: if no single-member check was unknown, the set is a minimal
unsatisfiable subset. If one was, the set is still proven infeasible but not
proven minimal; it goes out as ``method = "presolve"`` (proven, not minimal,
D43) when pre-solve proved it, and otherwise the input diagnosis is returned
unchanged: ``solution.v2`` has no method for "proven by search, not minimal".
Members tried first leave the set first, so groups only a person can change
(clashes, capacity, contiguity) are tried before data a coordinator can relax.

**Start.** Shrinking every group costs one check each; first the groups that
touch the sessions the proof names (or a given *initial* set) are checked
alone, and the shrinking starts from them if that check is infeasible.

**Relaxations** (relaxation_actions_v2.json). A member's single-member check
found a timetable that breaks only that member - its witness, as in model
rotation (Marques-Silva and Lynce 2011). The witness says which entity of a pin
to free and which unavailable slots a teacher would need. Candidate actions are
tried smallest first (slots freed, then the contract's action order) on the
whole instance, and the first one whose re-solve finds a timetable that
:func:`solver.validate.validate_solution` accepts is the
``suggested_relaxation`` (``verification: restored``). The change itself is
never relaxed: it is what was asked for. If none restores, the relaxation is
MANUAL. Stdlib only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from solver.backtracking import (
    BacktrackResult,
    _contiguous_start_slots,
    backtrack_solve,
    parse_rooms,
)
from solver.graph import build_conflict_graph
from solver.slots import SlotGrid, SlotId
from solver.validate import validate_solution

__all__ = ["MUS_NODES", "apply_action", "explain"]

# Search nodes per check or verification; running out makes it unknown. A backtrack-free
# solve of the real EVEN instance takes about 150.
MUS_NODES = 300
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
CHANGE = "change"
# Tried for removal first = likeliest to leave the set: MANUAL-only kinds first. Room groups
# go in a second pass: without them every room suits every session and each check is slow.
KINDS = ("COHORT_CLASH", "FACULTY_CLASH", "ROOM_CLASH", "LAB_CONTIGUITY", "PINNED_BLOCK",
         "FACULTY_UNAVAILABLE", "FIXED_SLOT", "ROOM_CAPACITY", "ROOM_TYPE")
LAST = frozenset({"ROOM_CAPACITY", "ROOM_TYPE"})
ACTIONS = ("UNFIX_SLOT", "RELAX_FACULTY_AVAILABILITY", "RELAX_PINNED_BLOCK", "RECLASSIFY_ROOM")
EDGE_KINDS = {"FACULTY": ("FACULTY_CLASH", "faculty_id"), "COHORT": ("COHORT_CLASH", "cohort_id"),
              "ROOM": ("ROOM_CLASH", "id")}

Cell = tuple[int, int]


def _cells(cells: list[Cell] | tuple[Cell, ...]) -> str:
    return ", ".join(f"{DAYS[d]} P{p}" for d, p in cells)


@dataclass(frozen=True, slots=True)
class _Group:
    id: str
    kind: str
    entity_ids: tuple[str, ...]
    slots: tuple[Cell, ...]
    text: str


def apply_action(payload: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    """A copy of *payload* with one ``solution.v2`` relaxation action applied.

    Raises:
        ValueError: for MANUAL or an unknown action type - nothing to apply.
    """
    kind, params = action["action_type"], action["params"]
    out = dict(payload)
    if kind == "RELAX_PINNED_BLOCK":
        cell = (params["slot"]["day"], params["slot"]["period"])
        key = f"{params['entity_kind']}_ids"
        out["pinned_occupancy"] = [
            {**p, key: [x for x in p[key] if x != params["entity_id"]]}
            if (p["day"], p["period"]) == cell else p
            for p in payload["pinned_occupancy"]
        ]
    elif kind == "RELAX_FACULTY_AVAILABILITY":
        cells = {(s["day"], s["period"]) for s in params["slots"]}
        out["faculty_availability"] = [
            {**a, "unavailable_slots": [s for s in a["unavailable_slots"]
                                        if (s["day"], s["period"]) not in cells]}
            if a["faculty_id"] == params["faculty_id"] else a
            for a in payload["faculty_availability"]
        ]
    elif kind == "UNFIX_SLOT":
        out["sessions"] = [{**s, "fixed_slot": None} if s["id"] == params["session_id"] else s
                           for s in payload["sessions"]]
    elif kind == "RECLASSIFY_ROOM":
        out["rooms"] = [{**r, "is_lab": params["is_lab"]} if r["id"] == params["room_id"] else r
                        for r in payload["rooms"]]
    else:
        raise ValueError(f"cannot apply action {kind!r}")
    return out


class _Problem:
    """The instance as constraint groups that can each be switched off."""

    def __init__(self, payload: dict[str, Any], change: dict[str, Any] | None) -> None:
        from solver.repair import _room_of, apply_change  # repair imports this module

        self.base, self.change = payload, change
        self.full = payload if change is None else apply_change(payload, change)
        self.forced = ({change["session_id"]: _room_of(change)}
                       if change is not None and change["kind"] == "move_session" else {})
        self.sessions = {s["id"]: s for s in self.full["sessions"]}
        self.parent = {r["id"]: r["parent_room_id"] for r in self.full["rooms"]}
        self.base_unavailable = {(a["faculty_id"], s["day"], s["period"])
                                 for a in payload["faculty_availability"]
                                 for s in a["unavailable_slots"]}
        self.biggest = max((s["cohort_size"] for s in payload["sessions"]), default=0)
        self.edge_keys: dict[str, tuple[str, list[str]]] = {}
        self.edge_group = [self._edge_group(e) for e in self.full["edges"]]
        found = self._groups()
        found.sort(key=lambda g: KINDS.index("FIXED_SLOT") + 0.5 if g.id == CHANGE
                   else KINDS.index(g.kind))
        self.groups = {g.id: g for g in found}  # in deletion order
        # known timetables, each with the groups it breaks and through which sessions
        self.models: list[tuple[BacktrackResult, dict[str, set[str]]]] = []
        self.prefer: dict[str, tuple[SlotId, str]] = {}  # tried first in every search (known)
        self.checks = self.nodes = 0

    def _edge_group(self, edge: dict[str, Any]) -> str:
        kind, attr = EDGE_KINDS[edge["reason"]]
        key = sorted({self.sessions[edge["u"]][attr], self.sessions[edge["v"]][attr]})
        gid = ".".join([kind.lower(), *key])
        self.edge_keys[gid] = (kind, key)
        return gid

    def _groups(self) -> list[_Group]:
        base, groups = self.base, []
        for gid, (kind, key) in self.edge_keys.items():
            whose = {"FACULTY_CLASH": "taught by", "COHORT_CLASH": "of",
                     "ROOM_CLASH": "sharing a room:"}[kind]
            groups.append(_Group(gid, kind, tuple(key), (),
                                 f"Sessions {whose} {' and '.join(key)} may not overlap."))
        labs = any(s["requires_lab"] for s in base["sessions"])
        for r in base["rooms"]:
            if r["capacity"] < self.biggest:
                groups.append(_Group(f"room_capacity.{r['id']}", "ROOM_CAPACITY", (r["id"],), (),
                                     f"Room {r['id']} seats {r['capacity']}."))
            if labs and not r["is_lab"]:
                groups.append(_Group(f"room_type.{r['id']}", "ROOM_TYPE", (r["id"],), (),
                                     f"Room {r['id']} is not a lab, so no lab session may use it."))
        for b in base["lab_blocks"]:
            groups.append(_Group(f"lab_block.{b['id']}", "LAB_CONTIGUITY",
                                 (b["id"], *b["session_ids"]), (),
                                 f"Lab block {b['id']}: {', '.join(b['session_ids'])} start "
                                 "together and run over the same contiguous periods."))
        for i, p in enumerate(base["pinned_occupancy"]):
            ids = (*p["faculty_ids"], *p["room_ids"], *p["cohort_ids"])
            if ids:
                cell = ((p["day"], p["period"]),)
                groups.append(_Group(f"pin.{i}", "PINNED_BLOCK", ids, cell,
                                     f"Pinned occupancy {i} holds {', '.join(ids)} at "
                                     f"{_cells(cell)}."))
        for a in base["faculty_availability"]:
            fid = a["faculty_id"]
            for day in sorted({s["day"] for s in a["unavailable_slots"]}):
                cells = tuple(sorted((s["day"], s["period"]) for s in a["unavailable_slots"]
                                     if s["day"] == day))
                groups.append(_Group(f"unavailable.{fid}.{day}", "FACULTY_UNAVAILABLE", (fid,),
                                     cells, f"{fid} is unavailable at {_cells(cells)}."))
        for s in base["sessions"]:
            if s["fixed_slot"] is not None:
                cell = ((s["fixed_slot"]["day"], s["fixed_slot"]["period"]),)
                groups.append(_Group(f"fixed.{s['id']}", "FIXED_SLOT", (s["id"],), cell,
                                     f"{s['id']} is fixed to start at {_cells(cell)}."))
        if self.change is not None:
            groups.append(self._change_group())
        return groups

    def _change_group(self) -> _Group:
        change = self.change
        assert change is not None
        cells = tuple(sorted({(s["day"], s["period"]) for s in change.get("slots", [])}))
        if change["kind"] == "faculty_unavailable":
            fid = change["faculty_id"]
            cells = tuple(c for c in cells if (fid, *c) not in self.base_unavailable)
            return _Group(CHANGE, "FACULTY_UNAVAILABLE", (fid,), cells,
                          f"The change: {fid} is unavailable at {_cells(cells)}.")
        if change["kind"] == "room_unavailable":
            return _Group(CHANGE, "PINNED_BLOCK", (change["room_id"],), cells,
                          f"The change: room {change['room_id']} is closed at {_cells(cells)}.")
        sid, room = change["session_id"], self.forced[change["session_id"]]
        start = SlotId(change["day"], change["period"])
        chain = next((c for c in _contiguous_start_slots(
            SlotGrid.from_payload(self.full["slot_grid"]), self.sessions[sid]["duration_periods"])
            if c[0] == start), (start,))
        cells = tuple((s.day, s.period) for s in chain)
        return _Group(CHANGE, "FIXED_SLOT", (sid, room), cells,
                      f"The change: {sid} is moved to {_cells(cells)} in {room}.")

    def instance(self, drop: set[str]) -> tuple[dict[str, Any], dict[str, str]]:
        """The payload with the groups in *drop* switched off, and the forced rooms."""
        full, keep_change, pins = self.full, CHANGE not in drop, len(self.base["pinned_occupancy"])
        sessions = []
        for s, b in zip(full["sessions"], self.base["sessions"], strict=True):
            if keep_change and s["fixed_slot"] != b["fixed_slot"]:
                fixed = s["fixed_slot"]
            else:
                fixed = None if f"fixed.{s['id']}" in drop else b["fixed_slot"]
            sessions.append(s if fixed == s["fixed_slot"] else {**s, "fixed_slot": fixed})
        payload = {
            **full,
            "sessions": sessions,
            "edges": [e for e, g in zip(full["edges"], self.edge_group, strict=True)
                      if g not in drop],
            "rooms": [{**r, "is_lab": r["is_lab"] or f"room_type.{r['id']}" in drop,
                       "capacity": (max(r["capacity"], self.biggest)
                                    if f"room_capacity.{r['id']}" in drop else r["capacity"])}
                      for r in full["rooms"]],
            "lab_blocks": [b for b in full["lab_blocks"] if f"lab_block.{b['id']}" not in drop],
            "pinned_occupancy": [p for i, p in enumerate(full["pinned_occupancy"])
                                 if (f"pin.{i}" not in drop if i < pins else keep_change)],
            "faculty_availability": [
                {**a, "unavailable_slots": [
                    s for s in a["unavailable_slots"]
                    if (f"unavailable.{a['faculty_id']}.{s['day']}" not in drop
                        if (a["faculty_id"], s["day"], s["period"]) in self.base_unavailable
                        else keep_change)]}
                for a in full["faculty_availability"]],
        }
        return payload, (self.forced if keep_change else {})

    def solve(self, payload: dict[str, Any], forced: dict[str, str], node_limit: int,
              deadline: float | None, starts: dict[str, SlotId] | None = None,
              rooms: dict[str, str] | None = None) -> BacktrackResult:
        """Pre-solve, then backtracking within *node_limit*, *starts* and *rooms*
        frozen; a timetable found is validated."""
        left = None if deadline is None else max(0.0, deadline - time.perf_counter())
        held = {**(rooms or {}), **forced}
        result = backtrack_solve(build_conflict_graph(payload), payload, seed_assignment=starts,
                                 seed_rooms=held or None,
                                 prefer=self.prefer or None, node_limit=node_limit,
                                 time_limit_s=left)
        self.checks += 1
        self.nodes += result.nodes_explored
        if result.solved:
            found = {"status": "solved",
                     "assignment": result._placements(result.assignment, result.room_assignment)}
            violations = validate_solution(payload, found)
            if violations:
                raise AssertionError(
                    f"check broke a hard rule: {[v.to_dict() for v in violations]}")
        return result

    def check(self, keep: list[str], node_limit: int, deadline: float | None) -> BacktrackResult:
        """Solve with only *keep* on (see :meth:`search`)."""
        payload, forced = self.instance(set(self.groups) - set(keep))
        return self.search(payload, forced, keep, node_limit, deadline)

    def search(self, payload: dict[str, Any], forced: dict[str, str], keep: list[str],
               node_limit: int, deadline: float | None) -> BacktrackResult:
        """Solve *payload*, which holds at most the groups in *keep*.

        A known timetable that breaks none of *keep* (and that the validator
        accepts) answers at once. Otherwise pre-solve runs alone; with a node
        budget, the known timetable that breaks *keep* through the fewest
        sessions is then repaired locally - those sessions free, then also
        their conflict neighbours, everything else frozen (freeze and expand,
        as :mod:`solver.repair`) - and only then is the whole instance
        searched. A frozen search that fails proves nothing; pre-solve and the
        last search are the only proofs.
        """
        best: tuple[BacktrackResult, set[str]] | None = None
        for model, broken in reversed(self.models):
            culprits = set().union(*(broken[g] for g in keep if g in broken))
            if not culprits and _fits(payload, forced, model):
                return model
            if best is None or len(culprits) < len(best[1]):
                best = (model, culprits)
        result = self.solve(payload, forced, 0, deadline)
        if result.outcome == "infeasible" or not node_limit:
            return result
        if best is not None:
            model, free = best
            graph = build_conflict_graph(payload)
            block_of = {s: b["session_ids"] for b in payload["lab_blocks"]
                        for s in b["session_ids"]}
            for _ in range(2):
                free = {m for s in free for m in block_of.get(s, (s,))}
                frozen = sorted(set(model.assignment) - free)
                result = self.solve(payload, forced, node_limit, deadline,
                                    {s: model.assignment[s] for s in frozen},
                                    {s: model.room_assignment[s] for s in frozen})
                if result.solved:
                    break
                free = free | {n for s in free for n in graph.neighbours(s)}
            else:
                result = self.solve(payload, forced, node_limit, deadline)
        else:
            result = self.solve(payload, forced, node_limit, deadline)
        if result.solved:
            self.models.append((result, self.broken(result)))
        return result

    def known(self, timetable: dict[str, Any]) -> None:
        """Remember a solved ``solution.v2`` timetable as a model for later checks."""
        grid = SlotGrid.from_payload(self.full["slot_grid"])
        chains = {(c[0], n): c for n in {s["duration_periods"] for s in self.sessions.values()}
                  for c in _contiguous_start_slots(grid, n)}
        starts = {i["session_id"]: SlotId(i["day"], i["period"]) for i in timetable["assignment"]}
        model = BacktrackResult(
            assignment=starts, solved=True, nodes_explored=0, rooms=parse_rooms(self.full),
            room_assignment={i["session_id"]: i["sub_room_id"] or i["room_id"]
                             for i in timetable["assignment"]},
            occupied={sid: chains[(st, self.sessions[sid]["duration_periods"])]
                      for sid, st in starts.items()},
        )
        self.models.append((model, self.broken(model)))
        self.prefer = {sid: (st, model.room_assignment[sid]) for sid, st in starts.items()}

    def broken(self, model: BacktrackResult) -> dict[str, set[str]]:
        """Group -> the sessions through which *model* breaks it (a filter and a
        starting point: :func:`_fits` and the solver have the last word)."""
        rooms = {r["id"]: r for r in self.full["rooms"]}
        out: dict[str, set[str]] = {}
        for gid, group in self.groups.items():
            here = self._at(gid, model)
            if group.kind == "PINNED_BLOCK" and gid != CHANGE:
                hit = {sid for sid, _, _ in self._pin_hits(gid, model)}
            elif group.kind == "FACULTY_UNAVAILABLE":
                hit = {sid for sid, _ in here
                       if self.sessions[sid]["faculty_id"] == group.entity_ids[0]}
            elif group.kind == "PINNED_BLOCK":  # the change: a closed room
                units = {group.entity_ids[0], *(r for r, p in self.parent.items()
                                                if p == group.entity_ids[0])}
                hit = {sid for sid, _ in here if model.room_assignment[sid] in units}
            elif group.kind == "FIXED_SLOT":
                sid, (d, p) = group.entity_ids[0], group.slots[0]
                wrong = model.assignment[sid] != SlotId(d, p) or (
                    gid == CHANGE and model.room_assignment[sid] != self.forced[sid])
                hit = {sid} if wrong else set()
            elif group.kind == "LAB_CONTIGUITY":
                members = group.entity_ids[1:]
                hit = set(members) if len({model.assignment[s] for s in members}) > 1 else set()
            elif group.kind in LAST:
                lab = group.kind == "ROOM_TYPE"
                hit = {sid for sid, r in model.room_assignment.items() if r == group.entity_ids[0]
                       and (self.sessions[sid]["requires_lab"] if lab
                            else rooms[r]["capacity"] < self.sessions[sid]["cohort_size"])}
            else:
                continue  # clash groups below
            if hit:
                out[gid] = hit
        occupied = {sid: set(cells) for sid, cells in model.occupied.items()}
        for e, gid in zip(self.full["edges"], self.edge_group, strict=True):
            if not occupied[e["u"]].isdisjoint(occupied[e["v"]]):
                out.setdefault(gid, set()).update((e["u"], e["v"]))
        return out

    def relevant(self, infeasible: dict[str, Any]) -> list[list[str]]:
        """Start sets to try, smallest first: groups touching the sessions the proof
        names (pre-solve) or left unplaced (search), their teachers and cohorts, and
        every room. For a load or Hall certificate a pin can only matter outside the
        slots it counts as free, and through a teacher or cohort, so the first set
        keeps just those pins."""
        diagnosis = infeasible["diagnosis"]
        members = diagnosis["minimal_conflicting_set"]
        ids = ({e for m in members for e in m["entity_ids"]}
               if diagnosis["method"] == "presolve" else set(diagnosis["unplaced_session_ids"]))
        hint = {sid for sid in ids if sid in self.sessions}
        if not hint or len(hint) == len(self.sessions):
            return []
        people = ({self.sessions[s]["faculty_id"] for s in hint}
                  | {self.sessions[s]["cohort_id"] for s in hint})
        touch = hint | people | set(self.parent)
        broad = [gid for gid, g in self.groups.items()
                 if gid == CHANGE or not touch.isdisjoint(g.entity_ids)]
        if diagnosis["method"] != "presolve" or members[0]["kind"] not in (
                "FACULTY_CLASH", "COHORT_CLASH"):
            return [broad]
        free = {(s["day"], s["period"]) for s in members[0]["slots"]}
        narrow = [gid for gid in broad if self.groups[gid].kind != "PINNED_BLOCK" or gid == CHANGE
                  or (not people.isdisjoint(self.groups[gid].entity_ids)
                      and not free.issuperset(self.groups[gid].slots))]
        return [narrow, broad]

    def _at(self, gid: str, witness: BacktrackResult | None) -> list[tuple[str, Cell]]:
        """(session, cell) for every session *witness* places in a cell of group *gid*."""
        if witness is None:
            return []
        cells = self.groups[gid].slots
        return [(sid, (s.day, s.period)) for sid, occupied in sorted(witness.occupied.items())
                for s in occupied if (s.day, s.period) in cells]

    def taught(self, gid: str, witness: BacktrackResult | None) -> list[Cell]:
        """Cells of unavailability group *gid* at which *witness* has that faculty teach."""
        fid = self.groups[gid].entity_ids[0]
        return sorted({c for sid, c in self._at(gid, witness)
                       if self.sessions[sid]["faculty_id"] == fid})

    def _pin_hits(self, gid: str, witness: BacktrackResult) -> list[tuple[str, str, str]]:
        """(session, entity kind, id) for every use *witness* makes of pin *gid* at its cell."""
        pin, out = self.full["pinned_occupancy"][int(gid.split(".")[1])], []
        for sid, _ in self._at(gid, witness):
            session, room = self.sessions[sid], witness.room_assignment[sid]
            if session["faculty_id"] in pin["faculty_ids"]:
                out.append((sid, "faculty", session["faculty_id"]))
            if session["cohort_id"] in pin["cohort_ids"]:
                out.append((sid, "cohort", session["cohort_id"]))
            out += [(sid, "room", x) for x in pin["room_ids"]
                    if room in (x, self.parent.get(x)) or x == self.parent.get(room)]
        return out

    def used(self, gid: str, witness: BacktrackResult | None) -> list[tuple[str, str]]:
        """(entity kind, id) of pin *gid* that *witness* uses at the pin's cell."""
        if witness is None:
            return []
        return sorted({(kind, entity) for _, kind, entity in self._pin_hits(gid, witness)})

    def candidates(self, gid: str, witness: BacktrackResult | None) -> list[dict[str, Any]]:
        """Typed relaxation actions for group *gid*, from its witness where one is needed."""
        group = self.groups[gid]
        if gid == CHANGE:
            return []
        if group.kind == "FIXED_SLOT":
            return [{"action_type": "UNFIX_SLOT", "params": {"session_id": group.entity_ids[0]}}]
        if group.kind == "ROOM_TYPE":
            return [{"action_type": "RECLASSIFY_ROOM",
                     "params": {"room_id": group.entity_ids[0], "is_lab": True}}]
        if group.kind == "FACULTY_UNAVAILABLE":
            taught = self.taught(gid, witness)
            options = [taught] if taught and len(taught) < len(group.slots) else []
            return [{"action_type": "RELAX_FACULTY_AVAILABILITY",
                     "params": {"faculty_id": group.entity_ids[0],
                                "slots": [{"day": d, "period": p} for d, p in cells]}}
                    for cells in [*options, list(group.slots)]]
        if group.kind == "PINNED_BLOCK":
            ((d, p),) = group.slots
            return [{"action_type": "RELAX_PINNED_BLOCK",
                     "params": {"slot": {"day": d, "period": p}, "entity_kind": kind,
                                "entity_id": entity}}
                    for kind, entity in self.used(gid, witness)]
        return []

    def member(self, gid: str, witness: BacktrackResult | None) -> dict[str, Any]:
        """The group as a ``minimal_conflicting_set`` entry; its witness says what it stops."""
        group = self.groups[gid]
        text = group.text
        if group.kind == "PINNED_BLOCK" and gid != CHANGE and (used := self.used(gid, witness)):
            text += (" Without it a timetable exists that uses it for "
                     f"{', '.join(e for _, e in used)}.")
        elif group.kind == "FACULTY_UNAVAILABLE" and (taught := self.taught(gid, witness)):
            text += (f" Without it a timetable exists in which {group.entity_ids[0]} teaches at "
                     f"{_cells(taught)}.")
        return {"constraint_id": gid, "kind": group.kind, "description": text,
                "entity_ids": list(group.entity_ids),
                "slots": [{"day": d, "period": p} for d, p in group.slots]}


def _fits(payload: dict[str, Any], forced: dict[str, str], model: BacktrackResult) -> bool:
    """True when *model* is a valid timetable for *payload* with the *forced* rooms."""
    found = {"status": "solved",
             "assignment": model._placements(model.assignment, model.room_assignment)}
    return (all(model.room_assignment[sid] == room for sid, room in forced.items())
            and not validate_solution(payload, found))


def _say(action: dict[str, Any]) -> str:
    params = action["params"]
    match action["action_type"]:
        case "UNFIX_SLOT":
            return f"Release {params['session_id']} from its fixed slot."
        case "RELAX_FACULTY_AVAILABILITY":
            cells = [(s["day"], s["period"]) for s in params["slots"]]
            return f"Make {params['faculty_id']} available at {_cells(cells)}."
        case "RELAX_PINNED_BLOCK":
            cell = [(params["slot"]["day"], params["slot"]["period"])]
            return (f"Free {params['entity_kind']} {params['entity_id']} from the pinned "
                    f"occupancy at {_cells(cell)}.")
        case _:
            return f"Classify room {params['room_id']} as a lab."


def explain(
    payload: dict[str, Any],
    infeasible: dict[str, Any] | None,
    *,
    change: dict[str, Any] | None = None,
    initial: list[str] | None = None,
    timetable: dict[str, Any] | None = None,
    node_limit: int = MUS_NODES,
    time_limit_s: float | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The ``solution.v2`` diagnosis of an infeasible instance, explained.

    Parameters
    ----------
    payload:
        The ``edge_list_v1`` instance (in a repair, before the change).
    infeasible:
        Its infeasible ``solution.v2`` result (``presolve`` or
        ``search_exhaustion``), the proof everything starts from. ``None``: the
        *initial* set must prove itself; if its check is not infeasible the
        result is ``None``.
    change:
        A :func:`solver.repair.apply_change` change; it is one group, never relaxed.
    initial:
        Group ids to start from (``pin.<i>``, ...); the change is added. Used
        only if its check is infeasible.
    timetable:
        A solved ``solution.v2`` known to satisfy every group but the change
        (in a repair, the timetable being repaired); checks it satisfies need
        no search.
    node_limit:
        Search nodes per check and per verification (:data:`MUS_NODES`).
    time_limit_s:
        Wall-clock cap on the whole explanation, ``None`` for none; a check it
        cuts short is unknown.
    stats:
        If given, filled with ``groups``, ``start`` (size of the start set),
        ``checks``, ``nodes``, ``unknown`` (members not proven necessary),
        ``proven_minimal``, ``set``, ``witnesses`` (per member, the placements
        of a timetable that keeps every other member) and ``relaxations``
        (every action tried, with its verification).

    Returns
    -------
    dict or None
        ``method = "mus"`` if proven minimal, ``"presolve"`` if only proven
        infeasible by pre-solve, else *infeasible* unchanged (see the module
        docstring).
    """
    started = time.perf_counter()
    deadline = None if time_limit_s is None else started + time_limit_s
    problem = _Problem(payload, change)
    if timetable is not None:
        problem.known(timetable)
    everything = list(problem.groups)
    core, proof = everything, None
    if infeasible is not None:
        proof = "presolve" if infeasible["diagnosis"]["method"] == "presolve" else "search"
    if initial is not None:
        starts = [[g for g in everything if g in {*initial, CHANGE}]]
    elif infeasible is not None:
        starts = problem.relevant(infeasible)
    else:
        raise ValueError("explain needs a proof (infeasible) or an initial set")
    for start in starts:
        if len(start) < len(everything):
            result = problem.check(start, node_limit, deadline)
            if result.outcome == "infeasible":
                core, proof = start, "presolve" if result.certificate else "search"
                break
    if proof is None:
        return None
    started_with = len(core)

    # --- deletion: chunks, halving, then one member at a time; room groups in a second pass
    witness: dict[str, BacktrackResult] = {}
    unknown: set[str] = set()
    for last in (False, True):
        todo = [g for g in core if (problem.groups[g].kind in LAST) == last]
        size = max(1, len(todo) // 2)
        while True:
            i = 0
            while i < len(todo):
                chunk = set(todo[i:i + size])
                trial = [g for g in core if g not in chunk]
                # chunks: pre-solve only (0 nodes); keeping a chunk is always sound
                result = problem.check(trial, node_limit if size == 1 else 0, deadline)
                if result.outcome == "infeasible":
                    core, proof = trial, "presolve" if result.certificate else "search"
                    todo = [g for g in todo if g not in chunk]
                    continue
                if size == 1:
                    if result.solved:
                        witness[todo[i]] = result
                    else:
                        unknown.add(todo[i])
                i += size
            if size == 1:
                break
            size //= 2
    proven = not unknown

    if stats is not None:
        stats.update(groups=len(everything), start=started_with, unknown=sorted(unknown),
                     proven_minimal=proven, set=list(core), relaxations=[],
                     witnesses={g: w._placements(w.assignment, w.room_assignment)
                                for g, w in witness.items() if g in core})
    if not core or not (proven or proof == "presolve"):
        if stats is not None:
            stats.update(checks=problem.checks, nodes=problem.nodes)
        return infeasible

    # --- relaxations, smallest first, until one restores feasibility
    tried: dict[str, tuple[int, int, str, dict[str, Any]]] = {}
    for gid in core:
        for action in problem.candidates(gid, witness.get(gid)):
            key = json.dumps(action, sort_keys=True)
            size_of = len(action["params"].get("slots", [None]))
            tried.setdefault(key, (size_of, ACTIONS.index(action["action_type"]), gid, action))
    chosen = None
    attempts = []
    for _, _, gid, action in sorted(tried.values(), key=lambda t: (t[:3], json.dumps(t[3]))):
        began = time.perf_counter()
        result = problem.search(apply_action(problem.full, action), problem.forced, everything,
                                node_limit, deadline)
        status = {"solved": "restored", "infeasible": "still_infeasible",
                  "timeout": "timeout"}[result.outcome]
        attempt = {"constraint_id": gid, "description": _say(action), "action": action,
                   "verification": {"status": status,
                                    "runtime_ms": (time.perf_counter() - began) * 1000}}
        attempts.append(attempt)
        if status == "restored":
            chosen = attempt
            break
    if chosen is None:
        chosen = {"constraint_id": core[0],
                  "description": ("No single change to one of these constraints was verified "
                                  "to restore feasibility; a person has to decide what to change."),
                  "action": {"action_type": "MANUAL", "params": {}},
                  "verification": {"status": "not_attempted", "runtime_ms": None}}

    method = "mus" if proven else "presolve"
    keep_partial = method == "mus" and infeasible is not None
    diagnosis = {
        "method": method,
        "minimal_conflicting_set": [problem.member(g, witness.get(g)) for g in core],
        "suggested_relaxation": chosen,
        "partial_placement": infeasible["diagnosis"]["partial_placement"] if keep_partial else [],
        "unplaced_session_ids": (infeasible["diagnosis"]["unplaced_session_ids"] if keep_partial
                                 else [s["id"] for s in payload["sessions"]]),
    }
    metadata = dict(infeasible["metadata"]) if infeasible is not None else {
        "algorithm": "", "runtime_ms": 0.0, "sessions_total": len(problem.sessions),
        "sessions_assigned": 0, "slots_used": None, "backtracks": 0}
    tag = "mus-extraction(deletion-based" + ("" if proven else ", not proven minimal") + ")"
    metadata.update(
        algorithm=f"{metadata['algorithm']} + {tag}" if metadata["algorithm"] else tag,
        runtime_ms=metadata["runtime_ms"] + (time.perf_counter() - started) * 1000,
        backtracks=(metadata["backtracks"] or 0) + problem.nodes,
    )
    if not keep_partial:
        metadata["sessions_assigned"] = 0
    if stats is not None:
        stats.update(checks=problem.checks, nodes=problem.nodes, relaxations=attempts)
    return {"schema_version": "solution.v2", "status": "infeasible", "diagnosis": diagnosis,
            "metadata": metadata}
