"""Deterministic synthetic ``edge_list_v1`` instances for benchmarking.

:func:`generate` turns an :class:`InstanceConfig` and an integer seed into an
edge-list payload that validates against ``contracts/edge_list_v1.schema.json``.
The same config and seed always give byte-identical JSON (:func:`to_json`): all
randomness comes from one ``random.Random(seed)``, and no set or dict is
iterated in an order that depends on Python's hash seed.

Every preset is synthetic and sized for scaling tests only - none of them is
SPIT data. The one parameter taken from a real file is the ``large`` preset's
room inventory, copied from ``data/real/classrooms.xlsx``. Every other
parameter of every preset (divisions, batches, students per division, theory
hours, lab blocks, faculty, pins, unavailable slots, combined lectures, and the
``small``/``medium`` rooms) is synthetic.

What an instance contains
~~~~~~~~~~~~~~~~~~~~~~~~~

* **Divisions and batches.** Each division ``dNN`` has ``batches_per_division``
  batches ``dNN-bK``; a batch is contained in its division.
* **Theory.** Each division has ``theory_subjects_per_division`` subjects of
  ``hours_per_theory_subject`` single-period sessions, all taught by one
  faculty member.
* **Lab blocks.** Each division has ``lab_blocks_per_division`` blocks. A block
  holds one lab session per batch - a different subject and a different
  faculty member for each batch - all ``lab_block_duration`` periods long and
  bound to one start by a ``lab_blocks`` entry (``must_be_contiguous``).
* **Combined lectures.** ``combined_lectures`` single-period lectures for the
  union of two divisions (``CombinedDivisions``), carrying the summed strength.
* **Rooms.** Physical rooms from ``rooms``; a room with sub-room capacities is
  split into sub-rooms ``RNN-K`` that carry ``parent_room_id``.
* **Pinned blocks.** ``pinned_slots_per_division`` slots per division (MDM, HSS
  and the like) held for the division, all its batches and every combined
  cohort it belongs to.
* **Faculty unavailability.** ``unavailable_slots_per_faculty`` random teaching
  slots per faculty member.

Conflict edges are derived the way the data layer would:

* ``FACULTY`` - same faculty member;
* ``COHORT`` - the two cohorts share at least one batch (same cohort, batch
  inside a division, a combined cohort and either of its divisions);
* ``ROOM`` - both sessions fit exactly one room or sub-room, and it is the
  same one. Rare by construction; the solver assigns rooms itself.

Faculty are assigned least-loaded first (ties broken by a seeded shuffle), so
weekly loads stay within a few hours of each other. Nothing here guarantees
feasibility, except the one thing
``oversubscribe_division`` guarantees: infeasibility (see :func:`_oversubscribe`).

Slot grid: the canonical SPIT grid from :mod:`solver.slots` - wall-clock
periods 0-9, teaching periods ``[0, 1, 3, 4, 6, 7, 8, 9]``, period 2 the short
break and period 5 lunch.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from solver.slots import DAYS, PERIODS_PER_DAY, TEACHING_PERIODS, SlotId, all_slots

__all__ = [
    "PRESETS",
    "InstanceConfig",
    "RoomSpec",
    "division_demand",
    "generate",
    "to_json",
]


@dataclass(frozen=True, slots=True)
class RoomSpec:
    """One physical room. ``sub_rooms`` lists sub-room capacities, if split."""

    capacity: int
    is_lab: bool
    sub_rooms: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class InstanceConfig:
    """Scale and shape of a synthetic instance."""

    name: str
    divisions: int
    batches_per_division: int
    division_size: int
    theory_subjects_per_division: int
    hours_per_theory_subject: int
    lab_blocks_per_division: int
    lab_block_duration: int
    faculty: int
    rooms: tuple[RoomSpec, ...]
    pinned_slots_per_division: int
    unavailable_slots_per_faculty: int
    combined_lectures: int = 0
    #: Add theory to division 0 until it needs one more period than it has.
    oversubscribe_division: bool = False
    description: str = field(default="", compare=False)

    @property
    def batch_size(self) -> int:
        return self.division_size // self.batches_per_division


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

_SMALL_ROOMS = (
    RoomSpec(80, False),
    RoomSpec(80, False),
    RoomSpec(40, True, (20, 20)),
    RoomSpec(20, True),
)

_MEDIUM_ROOMS = (
    RoomSpec(160, False),
    RoomSpec(80, False),
    RoomSpec(80, False),
    RoomSpec(80, False),
    RoomSpec(60, True, (20, 20, 20)),
    RoomSpec(60, True, (20, 20, 20)),
    RoomSpec(20, True),
    RoomSpec(20, True),
)

#: The real CE room inventory from data/real/classrooms.xlsx (20 rows), with
#: synthetic ids. "used as" maps to is_lab as under edge_list_v1 (decision log
#: 2026-09-25): class -> false; lab, "as a lab", "Mtech lab" -> true;
#: "unsure" (605, 609) -> false. Sub-rooms from the separation column.
#: The only real data in any preset; everything else in "large" is synthetic.
_LARGE_ROOMS = (
    RoomSpec(80, False),  # 601 class
    RoomSpec(60, True, (20, 20, 20)),  # 603 lab, 20-20-20
    RoomSpec(20, True),  # 604 lab
    RoomSpec(80, False),  # 605 unsure
    RoomSpec(40, True, (20, 20)),  # 606 lab, 20-20
    RoomSpec(20, True),  # 607B lab
    RoomSpec(20, True),  # 607A Mtech lab
    RoomSpec(20, True),  # 608 lab
    RoomSpec(80, False),  # 609 unsure
    RoomSpec(160, False),  # 508 class
    RoomSpec(160, False),  # 002 class
    RoomSpec(20, True),  # 509 lab
    RoomSpec(70, True),  # 003 lab
    RoomSpec(40, True),  # 703 as a lab
    RoomSpec(60, True, (20, 20, 20)),  # 702 lab, 20-20-20
    RoomSpec(80, False),  # 701 class
    RoomSpec(160, False),  # 507 class
    RoomSpec(20, True),  # 507 as a lab (the duplicate row)
    RoomSpec(160, False),  # 203 class
    RoomSpec(160, False),  # 103 class
)

PRESETS: dict[str, InstanceConfig] = {
    "small": InstanceConfig(
        name="small",
        description="Smoke test: 2 divisions, 12 sessions.",
        divisions=2,
        batches_per_division=2,
        division_size=40,
        theory_subjects_per_division=2,
        hours_per_theory_subject=2,
        lab_blocks_per_division=1,
        lab_block_duration=2,
        faculty=6,
        rooms=_SMALL_ROOMS,
        pinned_slots_per_division=1,
        unavailable_slots_per_faculty=2,
    ),
    "medium": InstanceConfig(
        name="medium",
        description="4 divisions x 4 batches, synthetic.",
        divisions=4,
        batches_per_division=4,
        division_size=72,
        theory_subjects_per_division=4,
        hours_per_theory_subject=3,
        lab_blocks_per_division=2,
        lab_block_duration=2,
        faculty=16,
        rooms=_MEDIUM_ROOMS,
        pinned_slots_per_division=2,
        unavailable_slots_per_faculty=3,
        combined_lectures=1,
    ),
    "large": InstanceConfig(
        name="large",
        description=(
            "Synthetic scaling test, not SPIT data: 10 divisions x 4 batches, 41 "
            "faculty, ~240 sessions; only the 20 rooms are real (classrooms.xlsx)."
        ),
        divisions=10,
        batches_per_division=4,
        division_size=72,
        theory_subjects_per_division=4,
        hours_per_theory_subject=3,
        lab_blocks_per_division=3,
        lab_block_duration=2,
        faculty=41,
        rooms=_LARGE_ROOMS,
        pinned_slots_per_division=2,
        unavailable_slots_per_faculty=4,
        combined_lectures=2,
    ),
    "infeasible": InstanceConfig(
        name="infeasible",
        description=(
            "The small preset with division 0 over-subscribed: it needs one "
            "more period than it has free (ROADMAP Phase 5 edge case)."
        ),
        divisions=2,
        batches_per_division=2,
        division_size=40,
        theory_subjects_per_division=2,
        hours_per_theory_subject=2,
        lab_blocks_per_division=1,
        lab_block_duration=2,
        faculty=6,
        rooms=_SMALL_ROOMS,
        pinned_slots_per_division=1,
        unavailable_slots_per_faculty=2,
        oversubscribe_division=True,
    ),
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def _slot(slot: SlotId) -> dict[str, int]:
    return {"day": slot.day, "period": slot.period}


class _FacultyPool:
    """Least-loaded assignment with a seeded, deterministic tie-break."""

    def __init__(self, ids: list[str], rng: random.Random) -> None:
        self.ids = ids
        order = list(ids)
        rng.shuffle(order)
        self._rank = {fid: i for i, fid in enumerate(order)}
        self.load = dict.fromkeys(ids, 0)

    def take(self, hours: int, exclude: tuple[str, ...] = ()) -> str:
        candidates = [fid for fid in self.ids if fid not in exclude]
        if not candidates:
            raise ValueError("not enough faculty for a lab block of distinct teachers")
        chosen = min(candidates, key=lambda fid: (self.load[fid], self._rank[fid]))
        self.load[chosen] += hours
        return chosen


def _division_ids(config: InstanceConfig) -> list[str]:
    return [f"d{k:02d}" for k in range(config.divisions)]


def _batch_ids(division: str, config: InstanceConfig) -> list[str]:
    return [f"{division}-b{j}" for j in range(config.batches_per_division)]


def _combined_pairs(config: InstanceConfig) -> list[tuple[str, str]]:
    """Division pairs (0,1), (2,3), ... wrapping around, one per combined lecture."""
    divisions = _division_ids(config)
    if config.combined_lectures and len(divisions) < 2:
        raise ValueError("combined lectures need at least two divisions")
    pairs = []
    for c in range(config.combined_lectures):
        a = (2 * c) % len(divisions)
        b = (2 * c + 1) % len(divisions)
        pairs.append((divisions[a], divisions[b]))
    return pairs


def generate(config: InstanceConfig, seed: int) -> dict[str, Any]:
    """Build one ``edge_list_v1`` payload. Pure function of (config, seed)."""
    rng = random.Random(seed)
    teaching = all_slots()

    faculty_ids = [f"f{i:02d}" for i in range(config.faculty)]
    pool = _FacultyPool(faculty_ids, rng)

    divisions = _division_ids(config)
    batches = {d: _batch_ids(d, config) for d in divisions}
    pairs = _combined_pairs(config)
    combined_ids = [f"c-{a}-{b}" for a, b in pairs]

    # cohort id -> the batches it covers (sorted list, so nothing iterates a set)
    covers: dict[str, list[str]] = {}
    size: dict[str, int] = {}
    for d in divisions:
        covers[d] = list(batches[d])
        size[d] = config.division_size
        for b in batches[d]:
            covers[b] = [b]
            size[b] = config.batch_size
    for cid, (a, b) in zip(combined_ids, pairs, strict=True):
        covers[cid] = sorted(batches[a] + batches[b])
        size[cid] = 2 * config.division_size

    sessions: list[dict[str, Any]] = []
    lab_blocks: list[dict[str, Any]] = []

    def add(subject: str, faculty: str, cohort: str, duration: int, lab: bool) -> str:
        sid = f"s{len(sessions):04d}"
        sessions.append({
            "id": sid,
            "subject_id": subject,
            "faculty_id": faculty,
            "cohort_id": cohort,
            "session_type": "lab" if lab else "theory",
            "duration_periods": duration,
            "cohort_size": size[cohort],
            "requires_lab": lab,
            "fixed_slot": None,
        })
        return sid

    for d in divisions:
        for t in range(config.theory_subjects_per_division):
            teacher = pool.take(config.hours_per_theory_subject)
            for _ in range(config.hours_per_theory_subject):
                add(f"{d}-th{t}", teacher, d, 1, False)
        for blk in range(config.lab_blocks_per_division):
            taken: tuple[str, ...] = ()
            members = []
            for j, b in enumerate(batches[d]):
                teacher = pool.take(config.lab_block_duration, exclude=taken)
                taken += (teacher,)
                members.append(add(f"{d}-lab{blk}-{j}", teacher, b, config.lab_block_duration,
                                   True))
            lab_blocks.append({
                "id": f"{d}-blk{blk}",
                "session_ids": members,
                "duration_periods": config.lab_block_duration,
                "must_be_contiguous": True,
            })
    for c, cid in enumerate(combined_ids):
        add(f"comb{c}", pool.take(1), cid, 1, False)

    # Pinned blocks: per division, held for the division, its batches and every
    # combined cohort containing it.
    pinned: list[dict[str, Any]] = []
    for d in divisions:
        holders = [d, *batches[d], *(cid for cid, pair in zip(combined_ids, pairs, strict=True)
                                     if d in pair)]
        for slot in sorted(rng.sample(teaching, config.pinned_slots_per_division)):
            pinned.append({**_slot(slot), "faculty_ids": [], "room_ids": [],
                           "cohort_ids": holders})

    if config.oversubscribe_division:
        _oversubscribe(divisions[0], sessions, lab_blocks, pinned, add, pool)

    unavailable = {
        fid: sorted(rng.sample(teaching, config.unavailable_slots_per_faculty))
        for fid in faculty_ids
    }

    rooms = _rooms(config)
    edges = _edges(sessions, covers, rooms)

    return {
        "schema_version": "edge_list.v1",
        "slot_grid": {
            "days": DAYS,
            "periods_per_day": PERIODS_PER_DAY,
            "teaching_periods": list(TEACHING_PERIODS),
            "adjacency": [[a, b] for a, b in pairwise(TEACHING_PERIODS)],
        },
        "sessions": sessions,
        "edges": edges,
        "rooms": rooms,
        "faculty_availability": [
            {"faculty_id": fid, "unavailable_slots": [_slot(s) for s in unavailable[fid]]}
            for fid in faculty_ids
        ],
        "lab_blocks": lab_blocks,
        "pinned_occupancy": pinned,
    }


def division_demand(edge_list: dict[str, Any], division: str) -> tuple[int, int]:
    """(periods the division must be taught, slots it has free) in *edge_list*.

    Counts every session whose cohort covers one of the division's batches,
    once per lab block (a block's members run side by side), against the 40
    teaching slots minus the slots pinned for the division. Every counted unit
    conflicts with every other one - they all share a batch of the division -
    so demand > free slots is a certificate of infeasibility.

    Relies on the generator's id scheme (``dNN-bK`` batches, ``c-dA-dB``
    combined cohorts); it is a benchmark helper, not a general checker.
    """
    def touches(cohort: str) -> bool:
        return cohort == division or cohort.startswith(f"{division}-b") or (
            cohort.startswith("c-") and division in cohort.split("-")[1:]
        )

    in_block = {sid for blk in edge_list["lab_blocks"] for sid in blk["session_ids"]}
    demand = sum(
        s["duration_periods"]
        for s in edge_list["sessions"]
        if touches(s["cohort_id"]) and s["id"] not in in_block
    )
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    for blk in edge_list["lab_blocks"]:
        if any(touches(sessions[sid]["cohort_id"]) for sid in blk["session_ids"]):
            demand += blk["duration_periods"]
    pinned = {
        (p["day"], p["period"])
        for p in edge_list["pinned_occupancy"]
        if division in p["cohort_ids"]
    }
    return demand, len(all_slots()) - len(pinned)


def _oversubscribe(
    division: str,
    sessions: list[dict[str, Any]],
    lab_blocks: list[dict[str, Any]],
    pinned: list[dict[str, Any]],
    add: Callable[[str, str, str, int, bool], str],
    pool: _FacultyPool,
) -> None:
    """Add single-period theory to *division* until demand = free slots + 1.

    Pigeonhole: every unit counted by :func:`division_demand` occupies its own
    periods of the division's week, so one period too many cannot be placed,
    whatever the rooms or faculty.
    """
    snapshot = {"sessions": sessions, "lab_blocks": lab_blocks, "pinned_occupancy": pinned}
    demand, free = division_demand(snapshot, division)
    extra = 0
    while demand <= free:
        add(f"{division}-extra{extra}", pool.take(1), division, 1, False)
        extra += 1
        demand += 1


def _rooms(config: InstanceConfig) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    for i, spec in enumerate(config.rooms):
        rid = f"R{i:02d}"
        rooms.append({"id": rid, "code": f"{'L' if spec.is_lab else 'C'}{i:02d}",
                      "capacity": spec.capacity, "is_lab": spec.is_lab, "parent_room_id": None})
        for k, cap in enumerate(spec.sub_rooms, start=1):
            rooms.append({"id": f"{rid}-{k}", "code": f"{rid}-{k}", "capacity": cap,
                          "is_lab": spec.is_lab, "parent_room_id": rid})
    return rooms


def _edges(
    sessions: list[dict[str, Any]],
    covers: dict[str, list[str]],
    rooms: list[dict[str, Any]],
) -> list[dict[str, str]]:
    def suitable(s: dict[str, Any]) -> list[str]:
        return [
            r["id"] for r in rooms
            if r["capacity"] >= s["cohort_size"] and (r["is_lab"] or not s["requires_lab"])
        ]

    only_room = {}
    for s in sessions:
        fits = suitable(s)
        only_room[s["id"]] = fits[0] if len(fits) == 1 else None

    edges: list[dict[str, str]] = []
    for i, a in enumerate(sessions):
        covers_a = covers[a["cohort_id"]]
        for b in sessions[i + 1:]:
            if a["faculty_id"] == b["faculty_id"]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "FACULTY"})
            if any(batch in covers_a for batch in covers[b["cohort_id"]]):
                edges.append({"u": a["id"], "v": b["id"], "reason": "COHORT"})
            if only_room[a["id"]] is not None and only_room[a["id"]] == only_room[b["id"]]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "ROOM"})
    return edges


def to_json(edge_list: dict[str, Any]) -> str:
    """Canonical serialisation: the byte-identity guarantee is on this string."""
    return json.dumps(edge_list, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
