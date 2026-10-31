"""Export a seeded timetable as an edge_list_v1 payload, from the database only (S9).

Writes ``data/instances/even-2025-26/edge_list.json`` (the real instance
snapshot, committed) and the D41 display sidecar ``display.json`` beside it.
Both are deterministic: the same database gives byte-identical files.

- ``slot_grid``: data/reference/time_grid.yaml, Mon-Fri; every period but the
  coffee break is a teaching period ([0, 1, 3, 4, 5, 6, 7, 8, 9]) and adjacency
  joins consecutive teaching periods, so a lab may span the coffee break but no
  pair skips a lunch (proposal row 8 assessment; D6, D7).
- ``rooms``: the timetable's room set (D8 labs, D10 and D42 classrooms) with
  their sub-rooms. A lab with sub-rooms seats the sum of them, which is its D8
  batch count x 20 (D27: 509 holds 2 batches although classrooms.xlsx says 20).
- ``sessions``: the timetable's sessions the solver places (``frozen_by`` null),
  with duration, type, cohort, teacher and size. Lectures and the division-wide
  tutorials (D23) need a non-lab room seating 80, practicals a lab: the
  candidate rooms follow from ``requires_lab`` and ``cohort_size``.
- ``lab_blocks``: the timetable's lab blocks over those sessions.
- ``edges``: FACULTY (same teacher), COHORT (shared batch, so division-batch
  too) and ROOM (both sessions fit exactly one room, the same), built as
  ``solver.benchmarks.synthetic`` builds them.
- ``faculty_availability``: every teacher the timetable names, with the
  printed unavailable slots (D36).
- ``pinned_occupancy``: one entry per day and period of each year's lunch
  listing every cohort of that year (proposal row 8, caveat 1: the solver
  matches a pin's cohort by exact id); and of every frozen session (D24, D26,
  D44), label-only pinned block and out-of-scope, faculty-page or exam block
  (D35, D24, D37), with its teacher, room and every cohort sharing a batch with
  its cohort. The coffee break needs no pin: it is not a teaching period.

The sidecar (D41, not a contract) gives names for the ids, each pin's kind and
label in ``pinned_occupancy`` order, and the period clock times. For the UI
(S12e) it also gives each batch a unique label ("SE-Comp A batch A"), each
division's batch ids, each teacher's initials per year from the
faculty_initials rows scoped to the timetable's divisions (D38, D45; unscoped
manual rows under "unscoped", since they name no year), and each pin a
``unique_label``: its label, plus its slot and room when another block shares
the label, plus its cohort when that is still not enough.

S14r: every cohort gets a unique ``label``: a division its name, a batch its
division and letter, any other group its name, plus, when another group shares
it, the batch letter its printed cells give (lab notation ``SUBJECT / BATCH /
...``), then its printed slots; never an id. Each pin lists its ``faculty``
(the edge list's ``faculty_ids``) with the name Faculty___Subjects.xlsx spells
(D45; D25, D38, D44 resolutions) and the initials its printed label shows for
them. Names carry no title ("Prof.", "Dr."): the faculty sheets give none, and
only some legends do.

Run from the repo root::

    python -m db.export_edge_list
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from itertools import pairwise
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.local_guard import REPO_ROOT, local_database_url
from db.models import (
    Batch,
    Cohort,
    Division,
    Faculty,
    FacultyUnavailability,
    PinnedBlock,
    PinnedKind,
    RoomUsedAs,
    Timetable,
)
from db.models import Session as SessionRow
from ingestion.emit_v2 import slug
from ingestion.initials_legend import name_key
from ingestion.seed_even import TIMETABLE_NAME

SCHEMA = REPO_ROOT / "contracts" / "edge_list_v1.schema.json"
TIME_GRID = REPO_ROOT / "data" / "reference" / "time_grid.yaml"
OUT_DIR = REPO_ROOT / "data" / "instances" / "even-2025-26"
_LAB_USES = {RoomUsedAs.LAB, RoomUsedAs.AS_A_LAB, RoomUsedAs.MTECH_LAB}


def load_grid() -> dict:
    with TIME_GRID.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def faculty_id(f: Faculty) -> str:
    return f"fac-{slug(name_key(f.full_name))}"


def plain_name(full_name: str) -> str:
    """The name without a leading "Prof." or "Dr." (legend-only names carry one)."""
    return re.sub(r"^(Prof|Dr)\.\s+", "", full_name)


def batch_letters(cell: str) -> set[str]:
    """The batch letters a printed cell names: a field that is one letter A-D."""
    return {f.strip() for f in cell.split("/") if f.strip() in ("A", "B", "C", "D")}


def export(session: Session, name: str = TIMETABLE_NAME) -> tuple[dict, dict]:
    """``(edge_list, display)`` for the named timetable."""
    timetable = session.scalar(select(Timetable).where(Timetable.name == name))
    if timetable is None:
        raise SystemExit(f"no timetable named {name!r}; run python -m ingestion.seed_even")
    grid = load_grid()
    coffee = grid["coffee_period"]
    teaching = [p["period"] for p in grid["periods"] if p["period"] != coffee]

    def covered(start: int, duration: int) -> list[int]:
        return [p for p in teaching if p >= start][:duration]

    # ---- rooms ---------------------------------------------------------------
    rooms, room_ids, sub_ids = [], {}, {}
    for room in sorted(timetable.rooms, key=lambda r: r.code):
        rid = room_ids[room.id] = f"room-{room.code.lower()}"
        subs = sorted(room.sub_rooms, key=lambda s: s.label)
        is_lab = room.used_as in _LAB_USES
        rooms.append({"id": rid, "code": room.code,
                      "capacity": sum(s.capacity for s in subs) if subs else room.capacity,
                      "is_lab": is_lab, "parent_room_id": None})
        for s in subs:
            code = f"{room.code}-{s.label}"
            sub_ids[s.id] = f"sub-{code.lower()}"
            rooms.append({"id": sub_ids[s.id], "code": code, "capacity": s.capacity,
                          "is_lab": is_lab, "parent_room_id": rid})
    if len({r["id"] for r in rooms}) != len(rooms):
        raise SystemExit("two rooms of the timetable share a code")

    # ---- cohorts: batch sets and years ----------------------------------------
    rows = list(session.scalars(select(SessionRow).where(SessionRow.timetable_id == timetable.id)
                                .order_by(SessionRow.source_ref)))
    pins = list(session.scalars(select(PinnedBlock).where(PinnedBlock.timetable_id == timetable.id)
                                .order_by(PinnedBlock.source_ref)))
    used = {r.cohort for r in rows} | {p.cohort for p in pins if p.cohort}
    divisions = {c if isinstance(c, Division) else c.division for c in used
                 if isinstance(c, Division | Batch)}
    universe = used | divisions | {b for d in divisions for b in d.batches}

    def batches_of(c: Cohort) -> frozenset[int]:
        if isinstance(c, Division):
            return frozenset(b.id for b in c.batches)
        if isinstance(c, Batch):
            return frozenset({c.id})
        return frozenset(b.id for b in c.member_batches)

    covers = {c: batches_of(c) for c in universe}
    year_of_batch = {b.id: b.division.label[:2] for c in universe for b in
                     (c.batches if isinstance(c, Division) else [c] if isinstance(c, Batch)
                      else c.member_batches)}
    years = {c: sorted({year_of_batch[b] for b in covers[c]}) for c in universe}
    cohort_id = {c: c.source_ref for c in universe}
    if None in cohort_id.values():
        raise SystemExit("a cohort of the timetable has no source_ref")

    def overlapping(c: Cohort) -> list[str]:
        return sorted(cohort_id[o] for o in universe if covers[o] & covers[c])

    def cohort_label(c: Cohort) -> str:  # every division's batches are labelled "A".."D"
        return f"{c.division.label} batch {c.label}" if isinstance(c, Batch) else c.label

    # ---- sessions, lab blocks, edges ------------------------------------------
    placed = [r for r in rows if r.frozen_by is None]
    if any(r.faculty is None for r in placed):
        raise SystemExit("a session the solver places has no teacher")
    sessions = [{
        "id": r.source_ref, "subject_id": f"subj-{slug(r.subject.code)}",
        "faculty_id": faculty_id(r.faculty), "cohort_id": cohort_id[r.cohort],
        "session_type": r.session_type.value, "duration_periods": r.duration_periods,
        "cohort_size": r.cohort.strength, "requires_lab": r.session_type.value == "lab",
        "fixed_slot": None,
    } for r in placed]
    blocks: dict[str, dict] = {}
    for r in placed:
        if r.lab_block is not None:
            blk = blocks.setdefault(r.lab_block.source_ref, {
                "id": r.lab_block.source_ref, "session_ids": [],
                "duration_periods": r.lab_block.duration_periods, "must_be_contiguous": True})
            blk["session_ids"].append(r.source_ref)
    lab_blocks = [blocks[k] for k in sorted(blocks)]

    cohort_of = {s["id"]: r.cohort for s, r in zip(sessions, placed, strict=True)}

    def suitable(s: dict) -> list[str]:
        return [room["id"] for room in rooms if room["capacity"] >= s["cohort_size"]
                and (room["is_lab"] or not s["requires_lab"])]

    only_room = {s["id"]: (fits[0] if len(fits := suitable(s)) == 1 else None)
                 for s in sessions}
    edges = []
    for i, a in enumerate(sessions):
        for b in sessions[i + 1:]:
            if a["faculty_id"] == b["faculty_id"]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "FACULTY"})
            if covers[cohort_of[a["id"]]] & covers[cohort_of[b["id"]]]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "COHORT"})
            if only_room[a["id"]] is not None and only_room[a["id"]] == only_room[b["id"]]:
                edges.append({"u": a["id"], "v": b["id"], "reason": "ROOM"})

    # ---- pins ------------------------------------------------------------------
    pinned: list[dict] = []
    shown: list[dict] = []
    #: one per pinned block: its display entry, its slot and room, its own cohort
    pin_blocks: list[tuple[dict, list[str], str | None]] = []
    room_code = {r["id"]: r["code"] for r in rooms}

    def slot_text(day: int, periods: list[int]) -> str:
        span = f"P{periods[0]}" + (f"\u2013P{periods[-1]}" if len(periods) > 1 else "")
        return f"{grid['days'][day][:3]} {span}"

    def teacher(faculty: Faculty | None, label: str) -> list[dict]:
        """The pin's teacher (its faculty_ids), named, with the initials its label shows."""
        if faculty is None:
            return []
        words = set(re.findall(r"[A-Za-z]+", label))
        shown_as = sorted({fi.initials for fi in faculty.initials if not fi.is_ambiguous}
                          & words)
        return [{"id": faculty_id(faculty), "name": plain_name(faculty.full_name),
                 "initials": shown_as}]

    def pin(day: int, periods: list[int], faculty: Faculty | None, room_ref: str | None,
            cohorts: list[str], about: dict, owner: Cohort | None = None) -> None:
        about["faculty"] = teacher(faculty, about["label"])
        for period in periods:
            pinned.append({"day": day, "period": period,
                           "faculty_ids": [faculty_id(faculty)] if faculty else [],
                           "room_ids": [room_ref] if room_ref else [], "cohort_ids": cohorts})
            shown.append(about)
        pin_blocks.append((about, [slot_text(day, periods)]
                           + ([room_code[room_ref]] if room_ref else []),
                           cohort_label(owner) if owner else None))

    def room_ref(room_id: int | None, sub_room_id: int | None) -> str | None:
        return sub_ids.get(sub_room_id) or room_ids.get(room_id)

    lunch = {(p.day, p.period, y) for p in pins if p.kind is PinnedKind.BREAK and p.cohort
             for y in years[p.cohort]}
    for day, period, year in sorted(lunch):
        if grid["lunch_period"][year] != period:
            raise SystemExit(f"{year} lunch at P{period}; time_grid.yaml says "
                             f"P{grid['lunch_period'][year]}")
        everyone = sorted(cohort_id[c] for c in universe if year in years[c])
        pin(day, [period], None, None, everyone,
            {"kind": "lunch", "label": f"{year} lunch", "year": year})
    for r in rows:
        if r.frozen_by is not None:
            pin(r.day, covered(r.period, r.duration_periods), r.faculty,
                room_ref(r.room_id, r.sub_room_id), overlapping(r.cohort),
                {"kind": "frozen", "label": r.source_cell, "decision": r.frozen_by,
                 "source_ref": r.source_ref}, r.cohort)
    for p in pins:
        if p.kind is PinnedKind.BREAK:
            continue
        pin(p.day, covered(p.period, p.duration_periods), p.faculty,
            room_ref(p.room_id, p.sub_room_id), overlapping(p.cohort) if p.cohort else [],
            {"kind": p.kind.value, "label": p.label, "source_ref": p.source_ref}, p.cohort)

    # A label several blocks share gets their slot and room, then their own cohort.
    repeated = Counter(about["label"] for about, _, _ in pin_blocks)
    for about, where, _ in pin_blocks:
        about["unique_label"] = ", ".join([about["label"], *where]) \
            if repeated[about["label"]] > 1 else about["label"]
    repeated = Counter(about["unique_label"] for about, _, _ in pin_blocks)
    for about, _, owner in pin_blocks:
        if repeated[about["unique_label"]] > 1 and owner:
            about["unique_label"] += f", {owner}"
    alike = [k for k, n in Counter(a["unique_label"] for a, _, _ in pin_blocks).items() if n > 1]
    if alike:
        raise SystemExit(f"pinned blocks no slot, room or cohort tells apart: {alike[:5]}")

    # ---- faculty availability ---------------------------------------------------
    off = sorted(session.scalars(select(FacultyUnavailability).where(
        FacultyUnavailability.timetable_id == timetable.id)), key=lambda u: (u.day, u.period))
    named = {r.faculty for r in rows if r.faculty} | {p.faculty for p in pins if p.faculty} | {
        u.faculty for u in off}
    names = {faculty_id(f): f.full_name for f in named}
    # Legend and D38 rows are scoped to a division, so to its year (D38: SD, SM differ by year).
    initials: dict[str, dict[str, set[str]]] = {fid: {} for fid in names}
    for f in named:
        for fi in f.initials:
            if fi.is_ambiguous:
                continue
            if fi.division in years:
                scope = years[fi.division][0]
            elif fi.division_id is None and fi.semester_id is None:
                scope = "unscoped"
            else:  # another term's legend
                continue
            initials[faculty_id(f)].setdefault(scope, set()).add(fi.initials)
    unavailable: dict[str, list[dict]] = {fid: [] for fid in names}
    for u in off:
        unavailable[faculty_id(u.faculty)].append({"day": u.day, "period": u.period})

    edge_list = {
        "schema_version": "edge_list.v1",
        "slot_grid": {
            "days": len(grid["days"]), "periods_per_day": len(grid["periods"]),
            "teaching_periods": teaching,
            "adjacency": [list(pair) for pair in pairwise(teaching)],
        },
        "sessions": sessions,
        "edges": edges,
        "rooms": rooms,
        "faculty_availability": [{"faculty_id": fid, "unavailable_slots": slots}
                                 for fid, slots in sorted(unavailable.items())],
        "lab_blocks": lab_blocks,
        "pinned_occupancy": pinned,
    }
    errors = [e.message for e in Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8"))).iter_errors(edge_list)]
    if errors:
        raise SystemExit(f"edge list breaks the contract: {errors[:5]}")

    in_list = {s["cohort_id"] for s in sessions} | {c for p in pinned for c in p["cohort_ids"]}
    by_id = {cohort_id[c]: c for c in universe}
    subjects = {r.subject for r in placed}

    # Every cohort a unique readable label: groups sharing a name add the batch letter
    # their printed cells give, then their printed slots (S14r).
    printed: dict[str, list[tuple[str, str]]] = {}  # cohort id -> (cell, slot) per item
    for item in [*rows, *(p for p in pins if p.kind is not PinnedKind.BREAK and p.cohort)]:
        cell = item.source_cell if isinstance(item, SessionRow) else item.label
        printed.setdefault(cohort_id[item.cohort], []).append(
            (cell or "", slot_text(item.day, covered(item.period, item.duration_periods))))
    def by_letter(cid: str) -> str:
        letters = sorted({x for cell, _ in printed.get(cid, []) for x in batch_letters(cell)})
        return f" batch {'/'.join(letters)}" if letters else ""

    def by_slot(cid: str) -> str:
        return ", " + "; ".join(sorted({slot for _, slot in printed.get(cid, [])}))

    labels = {cid: cohort_label(by_id[cid]) for cid in in_list}
    for qualify in (by_letter, by_slot):
        repeated = Counter(labels.values())
        for cid in labels:
            if repeated[labels[cid]] > 1 and not isinstance(by_id[cid], Division | Batch):
                labels[cid] += qualify(cid)
    if alike := [k for k, n in Counter(labels.values()).items() if n > 1]:
        raise SystemExit(f"cohorts no batch letter or printed slot tells apart: {alike[:5]}")
    display = {
        "note": "D41 display sidecar for edge_list.json: names, pin kinds and labels, clock "
                "times. Not a contract. pins[i] describes pinned_occupancy[i]; its unique_label "
                "tells blocks apart that share a label; its faculty names its teacher with the "
                "initials its label shows. Every cohort's label is unique; batches gives "
                "each division's batch ids; initials are per year, 'unscoped' for manual "
                "mappings with no year. Names carry no title.",
        "generated_by": "python -m db.export_edge_list",
        "timetable": timetable.name,
        "days": grid["days"],
        "periods": [{"period": p["period"], "start": p["start"], "end": p["end"],
                     "teaching": p["period"] != coffee} for p in grid["periods"]],
        "coffee_period": coffee,
        "lunch_period": grid["lunch_period"],
        "faculty": {fid: plain_name(names[fid]) for fid in sorted(unavailable)},
        "initials": {fid: {scope: sorted(initials[fid][scope]) for scope in sorted(initials[fid])}
                     for fid in sorted(initials)},
        "cohorts": {cid: {"name": by_id[cid].label, "type": by_id[cid].cohort_type.value,
                          "years": years[by_id[cid]], "label": labels[cid]}
                    for cid in sorted(in_list)},
        "batches": {cohort_id[d]: sorted(cohort_id[b] for b in d.batches)
                    for d in sorted(divisions, key=lambda d: cohort_id[d])},
        "rooms": {r["id"]: r["code"] for r in rooms},
        "subjects": {f"subj-{slug(s.code)}": {"code": s.code, "name": s.name}
                     for s in sorted(subjects, key=lambda s: s.code)},
        "pins": shown,
    }
    return edge_list, display


def dumps(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def write(edge_list: dict, display: dict, out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for file, data in (("edge_list.json", edge_list), ("display.json", display)):
        (out_dir / file).write_text(dumps(data), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    args = parser.parse_args(argv)
    engine = create_engine(local_database_url())
    with Session(engine) as session:
        edge_list, display = export(session)
    write(edge_list, display, args.out)
    print(f"wrote {args.out / 'edge_list.json'} ({len(edge_list['sessions'])} sessions, "
          f"{len(edge_list['edges'])} edges, {len(edge_list['pinned_occupancy'])} pins)")


if __name__ == "__main__":
    main()
