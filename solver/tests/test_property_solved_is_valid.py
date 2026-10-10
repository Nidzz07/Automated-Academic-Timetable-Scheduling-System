"""Property: a timetable the solver reports as solved is conflict-free.

Small random instances are generated from a fixed seed, so every run checks
the same instances and any failure reproduces by index
(``generate_instance(random.Random(SEED + index))``).  The generator covers the
features the two section 5.1 bugs lived in: multi-period labs, lab blocks that
may span the short break, standalone multi-period sessions, fixed slots
(sometimes deliberately inside unavailable or pinned slots), faculty
unavailability, pinned faculty/room/cohort blocks, sub-rooms, and capacity and
room-type pressure.

For every instance:

* backtracking: whenever it returns solved, ``validate_solution(...) == []``,
  and the solution payload conforms to ``solution_v1``;
* Welsh-Powell: whenever it places every session, ``validate_slot_placements``
  (the room-free half of the validator - colouring assigns no rooms) must
  hold, on the full generator and on the single-period subclass.  Before the
  2026-10-06 fix it did not (338 of 394 complete colourings were invalid); the
  validator was never loosened.

Each generated edge list is itself validated against ``edge_list_v1``.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from solver.backtracking import backtrack_solve
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.slots import TEACHING_PERIODS, SlotId, all_slots
from solver.validate import validate_slot_placements, validate_solution

#: Fixed seed for the generator. Instance i uses random.Random(SEED + i).
SEED = 20261003
#: Number of generated instances per property.
N_INSTANCES = 400

REPO = Path(__file__).resolve().parents[2]


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((REPO / "contracts" / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


# ======================================================================
# Generator
# ======================================================================

_COHORT_SIZE = {"D": 70, "E": 60, "D-A": 18, "D-B": 18, "D-C": 18}
_PARENT_COHORT = {"D-A": "D", "D-B": "D", "D-C": "D"}


def _cohorts_overlap(a: str, b: str) -> bool:
    """Same cohort, or a batch and its division (the data layer's COHORT edges)."""
    return a == b or _PARENT_COHORT.get(a) == b or _PARENT_COHORT.get(b) == a


def _slot_dict(slot: SlotId) -> dict[str, int]:
    return {"day": slot.day, "period": slot.period}


def generate_instance(
    rng: random.Random,
    *,
    multi_period: bool = True,
    blocks: bool = True,
    fixed: bool = True,
) -> dict[str, Any]:
    """One small edge_list_v1 payload.

    Only one or two days are open, so the search stays small and sessions are
    forced to interact.  The flags switch off feature families for the
    Welsh-Powell subclass test.
    """
    days = [0] if rng.random() < 0.6 else [0, 1]
    open_slots = [SlotId(d, p) for d in days for p in TEACHING_PERIODS]
    closed = [s for s in all_slots() if s.day not in days]

    faculty = [f"f{i}" for i in range(rng.randint(2, 5))]

    rooms: list[dict[str, Any]] = [
        {"id": "R1", "code": "R1", "capacity": 80, "is_lab": False, "parent_room_id": None},
        {"id": "R2", "code": "R2", "capacity": rng.choice([40, 75]), "is_lab": False,
         "parent_room_id": None},
        {"id": "L", "code": "L", "capacity": 60, "is_lab": True, "parent_room_id": None},
    ]
    for suffix in ["A", "B", "C"][: rng.randint(1, 3)]:
        rooms.append({"id": f"L-{suffix}", "code": f"L-{suffix}", "capacity": 20,
                      "is_lab": True, "parent_room_id": "L"})
    if rng.random() < 0.5:
        rooms.append({"id": "S", "code": "S", "capacity": 20, "is_lab": True,
                      "parent_room_id": None})
    if rng.random() < 0.5:  # an 'unsure' room: arrives as is_lab = false under v1
        rooms.append({"id": "U", "code": "605", "capacity": 25, "is_lab": False,
                      "parent_room_id": None})

    sessions: list[dict[str, Any]] = []

    def add(sid: str, fac: str, cohort: str, duration: int, lab: bool) -> None:
        sessions.append({
            "id": sid, "subject_id": f"subj-{sid}", "faculty_id": fac, "cohort_id": cohort,
            "session_type": "lab" if lab else "theory", "duration_periods": duration,
            "cohort_size": _COHORT_SIZE[cohort], "requires_lab": lab, "fixed_slot": None,
        })

    for i in range(rng.randint(2, 5)):
        duration = 2 if multi_period and rng.random() < 0.15 else 1
        add(f"t{i}", rng.choice(faculty), rng.choice(["D", "E", "D-A", "D-B"]),
            duration, False)
    if multi_period:
        for i in range(rng.randint(0, 2)):
            add(f"x{i}", rng.choice(faculty), rng.choice(["D-A", "D-B", "D-C"]), 2, True)

    lab_blocks: list[dict[str, Any]] = []
    if blocks and rng.random() < 0.6:
        batches = ["D-A", "D-B", "D-C"][: rng.randint(2, 3)]
        if rng.random() < 0.1:  # occasionally a shared faculty member: unplaceable
            block_faculty = [faculty[0]] * len(batches)
        else:
            block_faculty = rng.sample(faculty * 2, len(batches))
        member_ids = []
        for batch, fac in zip(batches, block_faculty, strict=True):
            sid = f"b-{batch}"
            add(sid, fac, batch, 2, True)
            member_ids.append(sid)
        lab_blocks.append({"id": "blk", "session_ids": member_ids, "duration_periods": 2,
                           "must_be_contiguous": True})

    if fixed:
        for s in sessions:
            if rng.random() < 0.15:
                s["fixed_slot"] = _slot_dict(rng.choice(open_slots))

    unavailable = {f: list(closed) + rng.sample(open_slots, rng.randint(0, 3))
                   for f in faculty}

    pinned: list[dict[str, Any]] = []
    for _ in range(rng.randint(0, 2)):
        slot = rng.choice(open_slots)
        kind = rng.choice(["faculty_ids", "room_ids", "cohort_ids"])
        pin: dict[str, Any] = {**_slot_dict(slot), "faculty_ids": [], "room_ids": [],
                               "cohort_ids": []}
        pool = {"faculty_ids": faculty, "room_ids": [r["id"] for r in rooms],
                "cohort_ids": list(_COHORT_SIZE)}[kind]
        pin[kind] = [rng.choice(pool)]
        pinned.append(pin)

    edges: list[dict[str, str]] = []
    for i, a in enumerate(sessions):
        for b in sessions[i + 1:]:
            if a["faculty_id"] == b["faculty_id"]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "FACULTY"})
            if _cohorts_overlap(a["cohort_id"], b["cohort_id"]):
                edges.append({"u": a["id"], "v": b["id"], "reason": "COHORT"})
            if (not a["requires_lab"] and not b["requires_lab"]
                    and a["cohort_size"] > 40 and b["cohort_size"] > 40
                    and rng.random() < 0.2):
                edges.append({"u": a["id"], "v": b["id"], "reason": "ROOM"})

    return {
        "schema_version": "edge_list.v1",
        "slot_grid": {
            "days": 5, "periods_per_day": 10, "teaching_periods": list(TEACHING_PERIODS),
            "adjacency": [[a, b] for a, b in pairwise(TEACHING_PERIODS)],
        },
        "sessions": sessions,
        "edges": edges,
        "rooms": rooms,
        "faculty_availability": [
            {"faculty_id": f, "unavailable_slots": [_slot_dict(s) for s in sorted(set(u))]}
            for f, u in unavailable.items()
        ],
        "lab_blocks": lab_blocks,
        "pinned_occupancy": pinned,
    }


def _instances(**flags: bool) -> list[dict[str, Any]]:
    return [generate_instance(random.Random(SEED + i), **flags) for i in range(N_INSTANCES)]


# ======================================================================
# Backtracking
# ======================================================================


def test_backtracking_solved_implies_valid() -> None:
    coverage: Counter[str] = Counter()
    for index, edge_list in enumerate(_instances()):
        _validator("edge_list_v1.schema.json").validate(edge_list)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        solution = result.to_solution_dict()
        _validator("solution_v1.schema.json").validate(solution)
        if not result.solved:
            coverage["infeasible"] += 1
            continue

        violations = validate_solution(edge_list, solution)
        assert violations == [], (
            f"instance {index} (random.Random({SEED} + {index})) reported solved "
            f"but violates: {[v.to_dict() for v in violations]}"
        )

        coverage["solved"] += 1
        sessions = {s["id"]: s for s in edge_list["sessions"]}
        for item in solution["assignment"]:
            s = sessions[item["session_id"]]
            if s["duration_periods"] > 1 and item["period"] == 1:
                coverage["double spanning short break"] += 1
            if s["duration_periods"] > 1 and item["period"] == 4:
                coverage["double spanning lunch"] += 1
            if item["sub_room_id"] is not None:
                coverage["sub-room used"] += 1
            if s["fixed_slot"] is not None:
                coverage["fixed slot honoured"] += 1
        if edge_list["lab_blocks"]:
            coverage["lab block placed"] += 1
        if edge_list["pinned_occupancy"]:
            coverage["with pinned blocks"] += 1
        if any(s["duration_periods"] > 1 and not s["requires_lab"]
               for s in edge_list["sessions"]):
            coverage["standalone multi-period theory"] += 1

    # The property is only as strong as what it exercised.
    assert coverage["solved"] >= N_INSTANCES // 5, coverage
    assert coverage["infeasible"] >= 1, coverage
    for feature in ["double spanning short break", "double spanning lunch", "sub-room used",
                    "fixed slot honoured", "lab block placed", "with pinned blocks",
                    "standalone multi-period theory"]:
        assert coverage[feature] >= 5, (feature, coverage)


# ======================================================================
# Welsh-Powell
# ======================================================================


def _colouring_violations(**flags: bool) -> tuple[int, Counter[str], list[int]]:
    """(complete colourings, violation kinds, failing instance indices)."""
    complete = 0
    kinds: Counter[str] = Counter()
    failing: list[int] = []
    for index, edge_list in enumerate(_instances(**flags)):
        assignment, unplaced = welsh_powell(build_conflict_graph(edge_list))
        if unplaced:
            continue
        complete += 1
        starts = {sid: (slot.day, slot.period) for sid, slot in assignment.items()}
        violations = validate_slot_placements(edge_list, starts)
        if violations:
            failing.append(index)
            kinds.update(v.kind for v in violations)
    return complete, kinds, failing


def test_welsh_powell_valid_on_its_supported_subclass() -> None:
    """Single-period, no lab blocks, no fixed slots: what colouring handles."""
    complete, kinds, failing = _colouring_violations(
        multi_period=False, blocks=False, fixed=False
    )
    assert complete >= N_INSTANCES // 5
    assert failing == [], (kinds, failing[:10])


def test_welsh_powell_full_generator_is_valid() -> None:
    """Formerly a strict xfail: colouring checked only start slots, coloured
    lab-block members independently and placed fixed slots unconditionally."""
    complete, kinds, failing = _colouring_violations()
    # A colouring that placed nothing would pass vacuously; require real coverage.
    assert complete >= N_INSTANCES // 5, complete
    assert failing == [], (
        f"{len(failing)} of {complete} complete colourings violate: {dict(kinds)}"
    )
