"""Independent hard-constraint checker for a solved timetable.

:func:`validate_solution` takes an edge-list payload (``edge_list_v1``) and a
solution payload (``solution_v1``) and re-checks **every hard constraint from
scratch**. It answers one question: does this timetable break anything the
instance forbids? It is the project's guarantee that "solved" means
conflict-free, so it is written to share nothing with the search:

* It imports **nothing** from ``solver.backtracking``, ``solver.colouring`` or
  ``solver.graph``. A bug in the search's helpers cannot hide in the checker,
  because the checker has its own. Only ``solver.slots`` (the slot vocabulary
  and :func:`~solver.slots.is_adjacent`) is shared.
* It reads plain dicts, not the solver's dataclasses, so it can check a
  timetable that came from anywhere: the backtracker, Welsh-Powell, a
  drag-and-drop edit in the frontend, or a hand-written fixture. It will back
  the backend's ``POST /timetables/{id}/validate``.

Occupancy
~~~~~~~~~

A placement occupies **every** period of its session, not only the first.
``solution_v1`` defines ``period`` as the starting period: a session of
``duration_periods = n`` occupies that period and the next ``n - 1`` periods in
*teaching* order. Consecutive occupied slots must satisfy
:func:`~solver.slots.is_adjacent`, so a double lab starting at period 1 occupies
periods 1 and 3 (across the short break), and one starting at period 9 has no
second period that day.

Checks and their ``kind``
~~~~~~~~~~~~~~~~~~~~~~~~~

The ``kind`` names are the closed enum reconciled in
``docs/contract-change-proposal-v2.md`` section 5.1, so a violation found here
uses the same vocabulary a diagnosis will.

==================== ==========================================================
``FACULTY_CLASH``     a ``FACULTY`` edge whose two sessions share a slot
``COHORT_CLASH``      a ``COHORT`` edge whose two sessions share a slot
``ROOM_CLASH``        a ``ROOM`` edge whose two sessions share a slot
``ROOM_OCCUPANCY``    two sessions in one room or sub-room in one slot, or a
                      whole room in use while one of its sub-rooms is
``ROOM_CAPACITY``     ``cohort_size`` exceeds the capacity of the room used
``ROOM_TYPE``         a ``requires_lab`` session in a room that is not a lab
``FACULTY_UNAVAILABLE`` a slot in the faculty member's ``unavailable_slots``
``PINNED_BLOCK``      a slot ``pinned_occupancy`` holds for the session's
                      faculty, cohort or room (parent/sub-room lockout included)
``LAB_CONTIGUITY``    a lab block whose sessions do not start together, or a
                      multi-period session whose periods cannot form a
                      teaching-adjacent chain from its start
``FIXED_SLOT``        a session with a ``fixed_slot`` placed anywhere else
==================== ==========================================================

``LAB_CONTIGUITY`` also covers a multi-period session that is *not* in a lab
block. ``edge_list_v1`` requires every multi-period session to occupy a
contiguous chain; the reconciled enum has no separate "duration" kind.

Malformed input is an error, not a violation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A violation is a timetable breaking a constraint someone could relax. A
payload that is not a timetable for this instance at all - an unknown or
duplicated session id, a session missing from a solved assignment, an unknown
room, a ``sub_room_id`` that is not a sub-room of ``room_id``, a start period
on a break - raises :class:`ValueError` instead. The teaching grid is not a
constraint kind (proposal section 5.1): nothing can relax it.

Pure stdlib, plain data in and out.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from solver.slots import (
    PERIODS_PER_DAY,
    TEACHING_PERIODS,
    SlotId,
    is_adjacent,
    is_teaching_period,
)

__all__ = [
    "KINDS",
    "Violation",
    "validate_slot_placements",
    "validate_solution",
]

#: The closed constraint vocabulary (proposal section 5.1), in report order.
KINDS: tuple[str, ...] = (
    "FACULTY_CLASH",
    "COHORT_CLASH",
    "ROOM_CLASH",
    "ROOM_OCCUPANCY",
    "ROOM_CAPACITY",
    "ROOM_TYPE",
    "FACULTY_UNAVAILABLE",
    "PINNED_BLOCK",
    "LAB_CONTIGUITY",
    "FIXED_SLOT",
)

_EDGE_KIND: dict[str, str] = {
    "FACULTY": "FACULTY_CLASH",
    "COHORT": "COHORT_CLASH",
    "ROOM": "ROOM_CLASH",
}

_KIND_ORDER: dict[str, int] = {kind: i for i, kind in enumerate(KINDS)}


@dataclass(frozen=True, slots=True)
class Violation:
    """One broken hard constraint.

    ``session_ids`` are the sessions involved, sorted. ``slots`` are the cells
    where the constraint breaks, sorted, on the wall-clock axis. ``entity_ids``
    names the non-session entities involved (faculty, room, cohort), sorted, for
    a UI to highlight. ``detail`` is a short explanation for logs and tests; it
    uses ids, so it is not the coordinator-facing description a diagnosis needs.
    """

    kind: str
    session_ids: tuple[str, ...]
    slots: tuple[SlotId, ...]
    entity_ids: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form, with slots as ``{"day", "period"}`` objects."""
        return {
            "kind": self.kind,
            "session_ids": list(self.session_ids),
            "slots": [{"day": s.day, "period": s.period} for s in self.slots],
            "entity_ids": list(self.entity_ids),
            "detail": self.detail,
        }


def _violation(
    kind: str,
    session_ids: list[str] | tuple[str, ...] | set[str],
    slots: list[SlotId] | tuple[SlotId, ...] | set[SlotId],
    entity_ids: list[str] | tuple[str, ...] | set[str] = (),
    detail: str = "",
) -> Violation:
    return Violation(
        kind=kind,
        session_ids=tuple(sorted(set(session_ids))),
        slots=tuple(sorted(set(slots))),
        entity_ids=tuple(sorted(set(entity_ids))),
        detail=detail,
    )


def _sort_key(v: Violation) -> tuple[Any, ...]:
    return (_KIND_ORDER[v.kind], v.session_ids, v.slots, v.entity_ids, v.detail)


# ---------------------------------------------------------------------------
# Occupancy - this module's own derivation, deliberately not shared
# ---------------------------------------------------------------------------


def _check_grid(edge_list: dict[str, Any]) -> None:
    """Refuse a payload whose slot grid is not the one ``solver.slots`` encodes.

    Occupancy is derived from :func:`~solver.slots.is_adjacent`, which knows only
    the canonical SPIT grid. Validating against a different grid would silently
    check the wrong periods, so it is an error instead.
    """
    grid = edge_list["slot_grid"]
    if grid["periods_per_day"] != PERIODS_PER_DAY or sorted(grid["teaching_periods"]) != sorted(
        TEACHING_PERIODS
    ):
        raise ValueError(
            "slot_grid differs from the canonical grid in solver.slots; "
            "validate_solution cannot check it"
        )
    declared = {tuple(pair) for pair in grid["adjacency"]}
    canonical = set(pairwise(TEACHING_PERIODS))
    if declared != canonical:
        raise ValueError(
            "slot_grid.adjacency differs from teaching-order adjacency in solver.slots; "
            "validate_solution cannot check it"
        )


def _occupied(start: SlotId, duration: int) -> tuple[list[SlotId], bool]:
    """Slots a placement starting at *start* occupies, and whether it fits.

    Walks forward in teaching order from *start*. Returns the slots that exist
    (at least *start*) and ``True`` only when all *duration* periods exist and
    each consecutive pair satisfies :func:`~solver.slots.is_adjacent`.
    """
    slots = [start]
    later = [p for p in TEACHING_PERIODS if p > start.period]
    for period in later[: duration - 1]:
        candidate = SlotId(start.day, period)
        if not is_adjacent(slots[-1], candidate):
            break
        slots.append(candidate)
    return slots, len(slots) == duration


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_slot_placements(
    edge_list: dict[str, Any],
    starts: dict[str, tuple[int, int]],
) -> list[Violation]:
    """Check every hard constraint that does not involve rooms.

    *starts* maps every session id to its ``(day, period)`` starting slot. This
    is the part of :func:`validate_solution` that a slot-only result - such as
    Welsh-Powell colouring, which assigns no rooms - can be held to. It is not a
    weaker check: :func:`validate_solution` runs exactly this, then the room
    checks.

    Checks: conflict edges, faculty availability, pinned faculty/cohort
    occupancy, multi-period contiguity, lab-block joint placement, fixed slots.

    Raises:
        ValueError: on a malformed input (see the module docstring).
    """
    _check_grid(edge_list)
    sessions: dict[str, dict[str, Any]] = {}
    for raw in edge_list["sessions"]:
        if raw["id"] in sessions:
            raise ValueError(f"duplicate session id in edge list: {raw['id']!r}")
        sessions[raw["id"]] = raw

    unknown = sorted(set(starts) - set(sessions))
    if unknown:
        raise ValueError(f"placement for unknown session(s): {unknown}")
    missing = sorted(set(sessions) - set(starts))
    if missing:
        raise ValueError(f"session(s) missing from the assignment: {missing}")

    violations: list[Violation] = []
    occupied: dict[str, list[SlotId]] = {}

    for sid in sorted(sessions):
        day, period = starts[sid]
        start = SlotId(day, period)
        if not is_teaching_period(start.period):
            raise ValueError(f"session {sid!r} starts on non-teaching period {period}")
        duration = sessions[sid]["duration_periods"]
        slots, fits = _occupied(start, duration)
        occupied[sid] = slots
        if not fits:
            violations.append(
                _violation(
                    "LAB_CONTIGUITY",
                    [sid],
                    slots,
                    detail=(
                        f"{sid} needs {duration} contiguous teaching periods from "
                        f"{start}, but only {len(slots)} exist"
                    ),
                )
            )

    # ---- conflict edges: occupied sets must be disjoint ----------------
    for edge in edge_list["edges"]:
        u, v, reason = edge["u"], edge["v"], edge["reason"]
        if u not in sessions or v not in sessions:
            raise ValueError(f"edge references unknown session: {u!r}-{v!r}")
        shared = set(occupied[u]) & set(occupied[v])
        if shared:
            violations.append(
                _violation(
                    _EDGE_KIND[reason],
                    [u, v],
                    shared,
                    detail=f"{u} and {v} share a {reason} edge and overlap",
                )
            )

    # ---- faculty availability -------------------------------------------
    unavailable: dict[str, set[SlotId]] = {}
    for entry in edge_list["faculty_availability"]:
        unavailable.setdefault(entry["faculty_id"], set()).update(
            SlotId(s["day"], s["period"]) for s in entry["unavailable_slots"]
        )
    for sid in sorted(sessions):
        fid = sessions[sid]["faculty_id"]
        bad = set(occupied[sid]) & unavailable.get(fid, set())
        if bad:
            violations.append(
                _violation(
                    "FACULTY_UNAVAILABLE",
                    [sid],
                    bad,
                    [fid],
                    detail=f"{sid} is taught by {fid} in a declared unavailable slot",
                )
            )

    # ---- pinned faculty / cohort ------------------------------------------
    pinned_faculty: dict[SlotId, set[str]] = {}
    pinned_cohort: dict[SlotId, set[str]] = {}
    for pin in edge_list["pinned_occupancy"]:
        slot = SlotId(pin["day"], pin["period"])
        pinned_faculty.setdefault(slot, set()).update(pin["faculty_ids"])
        pinned_cohort.setdefault(slot, set()).update(pin["cohort_ids"])
    for sid in sorted(sessions):
        fid = sessions[sid]["faculty_id"]
        cid = sessions[sid]["cohort_id"]
        for slot in occupied[sid]:
            held = []
            if fid in pinned_faculty.get(slot, set()):
                held.append(fid)
            if cid in pinned_cohort.get(slot, set()):
                held.append(cid)
            if held:
                violations.append(
                    _violation(
                        "PINNED_BLOCK",
                        [sid],
                        [slot],
                        held,
                        detail=f"{sid} uses {slot}, which a pinned block holds for {held}",
                    )
                )

    # ---- lab blocks: one shared start, one shared duration ---------------
    for block in edge_list["lab_blocks"]:
        members = list(block["session_ids"])
        for sid in members:
            if sid not in sessions:
                raise ValueError(f"lab block {block['id']!r} names unknown session {sid!r}")
            if sessions[sid]["duration_periods"] != block["duration_periods"]:
                raise ValueError(
                    f"lab block {block['id']!r} has duration {block['duration_periods']} but "
                    f"member {sid!r} has duration {sessions[sid]['duration_periods']}"
                )
        member_starts = {SlotId(*starts[sid]) for sid in members}
        if len(member_starts) > 1:
            violations.append(
                _violation(
                    "LAB_CONTIGUITY",
                    members,
                    member_starts,
                    [block["id"]],
                    detail=f"lab block {block['id']} members start in different slots",
                )
            )

    # ---- fixed slots -------------------------------------------------------
    for sid in sorted(sessions):
        fixed = sessions[sid]["fixed_slot"]
        if fixed is None:
            continue
        want = SlotId(fixed["day"], fixed["period"])
        got = SlotId(*starts[sid])
        if want != got:
            violations.append(
                _violation(
                    "FIXED_SLOT",
                    [sid],
                    [want, got],
                    detail=f"{sid} is fixed to {want} but starts at {got}",
                )
            )

    violations.sort(key=_sort_key)
    return violations


def validate_solution(
    edge_list: dict[str, Any],
    solution: dict[str, Any],
) -> list[Violation]:
    """Re-check every hard constraint of *solution* against *edge_list*.

    Returns an empty list when the timetable is conflict-free, otherwise every
    violation found, in a deterministic order. A solution whose ``status`` is
    not ``"solved"`` claims no timetable, so there is nothing to check and the
    result is ``[]``.

    Runs :func:`validate_slot_placements`, then the room checks: occupancy with
    parent/sub-room lockout, pinned rooms, capacity and room type.

    Raises:
        ValueError: on a malformed input (see the module docstring).
    """
    if solution["status"] != "solved":
        return []

    sessions = {raw["id"]: raw for raw in edge_list["sessions"]}
    rooms: dict[str, dict[str, Any]] = {}
    for raw in edge_list["rooms"]:
        if raw["id"] in rooms:
            raise ValueError(f"duplicate room id in edge list: {raw['id']!r}")
        rooms[raw["id"]] = raw

    starts: dict[str, tuple[int, int]] = {}
    unit_of: dict[str, str] = {}  # session -> the room or sub-room it occupies
    for item in solution["assignment"]:
        sid = item["session_id"]
        if sid in starts:
            raise ValueError(f"session {sid!r} is placed more than once")
        starts[sid] = (item["day"], item["period"])

        room_id, sub_id = item["room_id"], item["sub_room_id"]
        if room_id not in rooms:
            raise ValueError(f"session {sid!r} placed in unknown room {room_id!r}")
        if rooms[room_id]["parent_room_id"] is not None:
            raise ValueError(
                f"session {sid!r}: room_id {room_id!r} is a sub-room; "
                "room_id must name the physical room"
            )
        if sub_id is not None:
            if sub_id not in rooms:
                raise ValueError(f"session {sid!r} placed in unknown sub-room {sub_id!r}")
            if rooms[sub_id]["parent_room_id"] != room_id:
                raise ValueError(
                    f"session {sid!r}: {sub_id!r} is not a sub-room of {room_id!r}"
                )
        unit_of[sid] = sub_id if sub_id is not None else room_id

    violations = validate_slot_placements(edge_list, starts)

    occupied: dict[str, list[SlotId]] = {
        sid: _occupied(SlotId(*starts[sid]), sessions[sid]["duration_periods"])[0]
        for sid in starts
    }

    def parent(unit: str) -> str | None:
        return rooms[unit]["parent_room_id"]

    def units_collide(a: str, b: str) -> bool:
        """Same unit, or one is the whole room that contains the other."""
        return a == b or parent(a) == b or parent(b) == a

    # ---- room occupancy: pairwise over sessions sharing a slot ------------
    by_slot: dict[SlotId, list[str]] = {}
    for sid in sorted(occupied):
        for slot in occupied[sid]:
            by_slot.setdefault(slot, []).append(sid)
    collisions: dict[tuple[str, str], set[SlotId]] = {}
    for slot, present in by_slot.items():
        for i, a in enumerate(present):
            for b in present[i + 1 :]:
                if units_collide(unit_of[a], unit_of[b]):
                    collisions.setdefault((a, b), set()).add(slot)
    for (a, b), slots in collisions.items():
        violations.append(
            _violation(
                "ROOM_OCCUPANCY",
                [a, b],
                slots,
                [unit_of[a], unit_of[b]],
                detail=f"{a} in {unit_of[a]} and {b} in {unit_of[b]} hold the same space",
            )
        )

    # ---- pinned rooms --------------------------------------------------------
    pinned_rooms: dict[SlotId, set[str]] = {}
    for pin in edge_list["pinned_occupancy"]:
        pinned_rooms.setdefault(SlotId(pin["day"], pin["period"]), set()).update(
            pin["room_ids"]
        )
    for sid in sorted(occupied):
        unit = unit_of[sid]
        for slot in occupied[sid]:
            held = sorted(
                r
                for r in pinned_rooms.get(slot, set())
                if r == unit or r == parent(unit) or (r in rooms and parent(r) == unit)
            )
            if held:
                violations.append(
                    _violation(
                        "PINNED_BLOCK",
                        [sid],
                        [slot],
                        held,
                        detail=f"{sid} in {unit} at {slot}, which a pinned block holds",
                    )
                )

    # ---- capacity and room type ----------------------------------------------
    for sid in sorted(occupied):
        unit = unit_of[sid]
        session = sessions[sid]
        if session["cohort_size"] > rooms[unit]["capacity"]:
            violations.append(
                _violation(
                    "ROOM_CAPACITY",
                    [sid],
                    occupied[sid],
                    [unit],
                    detail=(
                        f"{sid} has {session['cohort_size']} students; "
                        f"{unit} holds {rooms[unit]['capacity']}"
                    ),
                )
            )
        if session["requires_lab"] and not rooms[unit]["is_lab"]:
            violations.append(
                _violation(
                    "ROOM_TYPE",
                    [sid],
                    occupied[sid],
                    [unit],
                    detail=f"{sid} requires a lab; {unit} is not a lab",
                )
            )

    violations.sort(key=_sort_key)
    return violations
