"""Seed the real EVEN 2025-26 SE+TE instance into the database (ROADMAP S9).

Reads ``data/generated/ingestion_v2_even.json`` (``python -m ingestion.emit_v2``)
and its D39 side file ``ingestion_v2_even.frozen.json``, and writes:

- the EVEN 2025-26 timetable record (status ``observed``, term-wide: SE and TE
  share faculty and rooms) and the rooms it may use (D8, D10, D42);
- programme, semesters, divisions and batches (D5), and the elective and other
  group cohorts with their member batches;
- lab sub-rooms per lab_capacities.yaml (509-1/2 and 703-A/B are not in
  classrooms.xlsx; D27, D30);
- faculty under their Faculty___Subjects.xlsx names with their legend aliases
  (D45), printed load lines, and initials (legend, D25, D38);
- subjects; observed sessions with type and duration, frozen ones marked with
  their decision (D24, D26, D44); lab blocks;
- pinned blocks: coffee, each division's lunch, label-only frozen items, and the
  side file's blocks with their teacher and room (D35, D24, D37);
- faculty unavailability (D36).

Rooms are institute reference data: they must already be seeded from
classrooms.xlsx (``seed_reference_data``); a payload room the database lacks
stops the seed. Room rows are never changed, so a later reference re-seed (keyed
on code, capacity and used_as) cannot duplicate them.

Everything is keyed on natural keys or on the payload's ids (``source_ref``),
so running the seed twice leaves identical rows; rows of this timetable the
payload no longer has are deleted. The CLI runs in one transaction and refuses
any non-local database (:mod:`db.local_guard`).

Run from the repo root::

    python -m ingestion.seed_even
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from db.local_guard import local_database_url
from db.models import (
    Batch,
    Cohort,
    CombinedDivisions,
    Department,
    Division,
    ElectiveGroup,
    Faculty,
    FacultyAlias,
    FacultyInitials,
    FacultySource,
    FacultyUnavailability,
    LabBlock,
    MappingSource,
    PinnedBlock,
    PinnedKind,
    Programme,
    Room,
    RoomUsedAs,
    Semester,
    SessionType,
    Subject,
    SubjectSessionType,
    SubRoom,
    TermCode,
    Timetable,
    TimetableStatus,
)
from db.models import Session as SessionRow
from ingestion.emit_v2 import DEFAULT_JSON, FROZEN_JSON
from ingestion.initials_legend import name_key
from ingestion.seed_reference import SeedBlocked, seed_institute_and_department

TIMETABLE_NAME = "CE EVEN 2025-26 SE+TE (observed)"

#: ingestion.v2 room_type -> the classrooms.xlsx 'used as' values it covers. An
#: 'unsure' room is a classroom under D42.
_USED_AS = {
    "class": {RoomUsedAs.CLASS, RoomUsedAs.UNSURE},
    "lab": {RoomUsedAs.LAB, RoomUsedAs.AS_A_LAB, RoomUsedAs.MTECH_LAB},
    "unknown": {RoomUsedAs.UNSURE},
}
_GROUP_TYPES = {"elective": ElectiveGroup, "combined": CombinedDivisions}


def load_files(payload_path: Path = DEFAULT_JSON, side_path: Path = FROZEN_JSON):
    return (json.loads(payload_path.read_text(encoding="utf-8")),
            json.loads(side_path.read_text(encoding="utf-8")))


def _get(session: Session, model, **keys):
    return session.scalar(select(model).filter_by(**keys))


def seed_even(session: Session, payload: dict, side: dict) -> dict[str, int]:
    """Write the instance; returns row counts per kind. Raises SeedBlocked."""
    _institute, department = seed_institute_and_department(session)
    semester = payload["semester"]
    term = TermCode(semester["code"])

    timetable = _get(session, Timetable, department_id=department.id, name=TIMETABLE_NAME)
    if timetable is None:
        timetable = Timetable(department_id=department.id, name=TIMETABLE_NAME)
        session.add(timetable)
    timetable.semester_id = None
    timetable.term_code = term
    timetable.academic_year = semester["academic_year"]
    timetable.status = TimetableStatus.OBSERVED
    session.flush()

    rooms, sub_rooms = _rooms(session, timetable, payload)
    cohorts = _cohorts(session, department, payload, term, semester["academic_year"])
    faculty = _faculty(session, department, payload, side)
    _initials(session, payload, faculty, cohorts)
    subjects = _subjects(session, department, payload)

    frozen_by = {f["id"]: f["resolution"] for f in side["frozen"]
                 if f["kind"] == "observed_session"}
    sessions = {s.source_ref: s for s in session.scalars(
        select(SessionRow).where(SessionRow.timetable_id == timetable.id))}
    for row in payload["observed_sessions"]:
        s = sessions.get(row["id"])
        if s is None:
            s = sessions[row["id"]] = SessionRow(timetable_id=timetable.id, source_ref=row["id"])
            session.add(s)
        sub = sub_rooms.get(row["sub_room_id"])
        s.department_id = department.id
        s.cohort_id = cohorts[row["cohort_id"]].id
        s.subject_id = subjects[row["subject_id"]].id
        s.faculty_id = faculty[row["faculty_id"]].id if row["faculty_id"] else None
        s.sub_room_id = sub.id if sub else None
        s.room_id = None if sub else rooms[row["room_id"]].id if row["room_id"] else None
        s.day, s.period, s.duration_periods = row["day"], row["period"], row["duration_periods"]
        s.session_type = SessionType(row["session_type"])
        s.source_cell = row["source_cell"]
        s.frozen_by = frozen_by.get(row["id"])
    session.flush()

    blocks = {b.source_ref: b for b in session.scalars(
        select(LabBlock).where(LabBlock.id.in_(
            select(SessionRow.lab_block_id).where(SessionRow.timetable_id == timetable.id))))}
    member_of = {sid: blk["id"] for blk in payload["lab_blocks"]
                 for sid in blk["parallel_session_ids"]}
    for blk in payload["lab_blocks"]:
        lab = blocks.get(blk["id"])
        if lab is None:
            lab = blocks[blk["id"]] = LabBlock(source_ref=blk["id"])
            session.add(lab)
        lab.department_id = department.id
        lab.division_id = cohorts[_division_cohort(payload, blk["division_id"])].id
        lab.day, lab.start_period = blk["day"], blk["start_period"]
        lab.duration_periods = blk["duration_periods"]
        lab.must_be_contiguous = True
    session.flush()
    for ref, s in sessions.items():
        s.lab_block_id = blocks[member_of[ref]].id if ref in member_of else None

    pins = _pins(session, department, timetable, payload, side, cohorts, faculty, rooms,
                 sub_rooms)
    unavailable = _unavailability(session, timetable, side, faculty)

    # Rows of this timetable the payload no longer has.
    stale = set(sessions) - {row["id"] for row in payload["observed_sessions"]}
    session.execute(delete(SessionRow).where(SessionRow.timetable_id == timetable.id,
                                             SessionRow.source_ref.in_(stale)))
    for ref in set(blocks) - {blk["id"] for blk in payload["lab_blocks"]}:
        session.delete(blocks[ref])
    session.flush()
    return {
        "sessions": len(payload["observed_sessions"]),
        "frozen_sessions": len(frozen_by),
        "lab_blocks": len(payload["lab_blocks"]),
        "pinned_blocks": pins,
        "faculty_unavailable_slots": unavailable,
        "rooms": len(rooms),
        "sub_rooms": len(sub_rooms),
        "cohorts": len(cohorts),
        "faculty": len(faculty),
        "deleted_sessions": len(stale),
    }


def _division_cohort(payload: dict, division_id: str) -> str:
    """The cohort id of a payload division ('div-se-a' -> 'coh-se-a')."""
    batches = {b["id"] for b in payload["batches"] if b["division_id"] == division_id}
    [cid] = [c["id"] for c in payload["cohorts"]
             if c["cohort_type"] == "division" and set(c["member_batch_ids"]) == batches]
    return cid


def _rooms(session: Session, timetable: Timetable, payload: dict):
    rooms: dict[str, Room] = {}
    sub_rooms: dict[str, SubRoom] = {}
    for r in payload["rooms"]:
        found = [row for row in session.scalars(select(Room).where(Room.code == r["code"]))
                 if row.used_as in _USED_AS[r["room_type"]]]
        if len(found) != 1:
            raise SeedBlocked(
                f"room {r['code']} ({r['room_type']}): {len(found)} matching rows in the "
                "database; run seed_reference_data (classrooms.xlsx) first")
        room = rooms[r["id"]] = found[0]
        for sub in r["sub_rooms"]:
            label = sub["code"].removeprefix(f"{r['code']}-")
            row = _get(session, SubRoom, room_id=room.id, label=label)
            if row is None:
                row = SubRoom(room_id=room.id, label=label, capacity=sub["capacity"])
                session.add(row)
            row.capacity = sub["capacity"]
            sub_rooms[sub["id"]] = row
    timetable.rooms = sorted(rooms.values(), key=lambda room: room.id)
    session.flush()
    return rooms, sub_rooms


def _cohorts(session: Session, department: Department, payload: dict, term: TermCode,
             academic_year: str) -> dict[str, Cohort]:
    p = payload["programmes"][0]
    programme = _get(session, Programme, department_id=department.id, code=p["code"])
    if programme is None:
        programme = Programme(department_id=department.id, code=p["code"], name=p["name"])
        session.add(programme)
        session.flush()

    cohorts: dict[str, Cohort] = {}
    batch_rows: dict[str, Batch] = {}
    for d in payload["divisions"]:
        semester = _get(session, Semester, programme_id=programme.id,
                        number=d["semester_number"], academic_year=academic_year)
        if semester is None:
            semester = Semester(department_id=department.id, programme_id=programme.id,
                                number=d["semester_number"], term_code=term,
                                academic_year=academic_year)
            session.add(semester)
            session.flush()
        elif semester.term_code is not term:
            raise SeedBlocked(f"semester {semester.number} {academic_year} is stored as "
                              f"{semester.term_code.value}, the payload says {term.value}")
        division = _get(session, Division, semester_id=semester.id, label=d["label"])
        if division is None:
            division = Division(department_id=department.id, semester_id=semester.id,
                                label=d["label"])
            session.add(division)
        division.strength = d["strength"]
        division.source_ref = _division_cohort(payload, d["id"])
        session.flush()
        cohorts[division.source_ref] = division
        for b in (b for b in payload["batches"] if b["division_id"] == d["id"]):
            batch = _get(session, Batch, division_id=division.id, label=b["label"])
            if batch is None:
                batch = Batch(department_id=department.id, division_id=division.id,
                              label=b["label"])
                session.add(batch)
            batch.strength = b["strength"]
            batch_rows[b["id"]] = batch
    session.flush()

    for c in payload["cohorts"]:
        if c["cohort_type"] == "batch":
            [bid] = c["member_batch_ids"]
            batch_rows[bid].source_ref = c["id"]
            cohorts[c["id"]] = batch_rows[bid]
        elif c["cohort_type"] in _GROUP_TYPES:
            model = _GROUP_TYPES[c["cohort_type"]]
            # shortcut: group ids are unique per department while only EVEN is seeded;
            # scope them by semester when a second term's payload is seeded.
            group = _get(session, model, department_id=department.id, source_ref=c["id"])
            if group is None:
                group = model(department_id=department.id, source_ref=c["id"])
                session.add(group)
            group.label = c["label"]
            members = [batch_rows[b] for b in c["member_batch_ids"]]
            group.member_batches = members
            group.member_divisions = sorted({b.division for b in members}, key=lambda d: d.id)
            cohorts[c["id"]] = group
    session.flush()
    missing = {c["id"] for c in payload["cohorts"]} - set(cohorts)
    if missing:
        raise SeedBlocked(f"cohorts with no database row: {sorted(missing)}")
    return cohorts


def _faculty(session: Session, department: Department, payload: dict,
             side: dict) -> dict[str, Faculty]:
    meta = {f["id"]: f for f in side["faculty"]}
    existing = {name_key(f.full_name): f for f in session.scalars(
        select(Faculty).where(Faculty.department_id == department.id))}
    out: dict[str, Faculty] = {}
    for f in payload["faculty"]:
        row = existing.get(name_key(f["full_name"]))
        if row is None:
            row = Faculty(department_id=department.id, full_name=f["full_name"])
            session.add(row)
        row.full_name = f["full_name"]  # D45: the canonical spelling
        row.source = row.source or FacultySource(meta[f["id"]]["source"])
        row.theory_hours = f["theory_hours"]
        row.practical_hours = f["practical_hours"]
        row.total_hours = f["total_hours"]
        session.flush()
        for alias in meta[f["id"]]["aliases"]:
            if _get(session, FacultyAlias, faculty_id=row.id, alias=alias["alias"]) is None:
                session.add(FacultyAlias(faculty_id=row.id, alias=alias["alias"],
                                         source=MappingSource(alias["source"])))
        out[f["id"]] = row
    session.flush()
    return out


def _initials(session: Session, payload: dict, faculty: dict[str, Faculty],
              cohorts: dict[str, Cohort]) -> None:
    for r in payload["faculty_initials"]:
        division = cohorts[_division_cohort(payload, r["division_id"])] \
            if r["division_id"] else None
        keys = {"faculty_id": faculty[r["faculty_id"]].id, "initials": r["initials"],
                "semester_id": division.semester_id if division else None,
                "division_id": division.id if division else None}
        row = _get(session, FacultyInitials, **keys)
        if row is None:
            row = FacultyInitials(**keys, source=MappingSource(r["source"]))
            session.add(row)
        row.is_ambiguous = r["is_ambiguous"]
    session.flush()


def _subjects(session: Session, department: Department, payload: dict) -> dict[str, Subject]:
    out: dict[str, Subject] = {}
    for s in payload["subjects"]:
        row = _get(session, Subject, department_id=department.id, code=s["code"])
        if row is None:
            row = Subject(department_id=department.id, code=s["code"], name=s["name"])
            session.add(row)
        # Filled where unknown; a spreadsheet subject's name is kept as seeded.
        row.session_type = row.session_type or SubjectSessionType(s["session_type"])
        out[s["id"]] = row
    session.flush()
    return out


def _pins(session: Session, department: Department, timetable: Timetable, payload: dict,
          side: dict, cohorts: dict[str, Cohort], faculty: dict[str, Faculty],
          rooms: dict[str, Room], sub_rooms: dict[str, SubRoom]) -> int:
    existing = {p.source_ref: p for p in session.scalars(
        select(PinnedBlock).where(PinnedBlock.timetable_id == timetable.id))}
    wanted = [
        {**b, "faculty_id": None, "room_id": None, "sub_room_id": None}
        for b in payload["pinned_blocks"]
    ] + [{**b, "cohort_id": None} for b in side["blocks"]]
    for b in wanted:
        if len(b["label"]) > 255:
            raise SeedBlocked(f"{b['id']}: label longer than 255 characters")
        pin = existing.get(b["id"])
        if pin is None:
            pin = existing[b["id"]] = PinnedBlock(timetable_id=timetable.id, source_ref=b["id"])
            session.add(pin)
        # The coffee break holds no cohort: institute-wide, no department.
        pin.department_id = department.id if b["cohort_id"] or b["kind"] != "break" else None
        pin.cohort_id = cohorts[b["cohort_id"]].id if b["cohort_id"] else None
        pin.faculty_id = faculty[b["faculty_id"]].id if b["faculty_id"] else None
        sub = sub_rooms.get(b["sub_room_id"])
        pin.sub_room_id = sub.id if sub else None
        pin.room_id = None if sub else rooms[b["room_id"]].id if b["room_id"] else None
        pin.label, pin.kind = b["label"], PinnedKind(b["kind"])
        pin.day, pin.period, pin.duration_periods = b["day"], b["period"], b["duration_periods"]
    for ref in set(existing) - {b["id"] for b in wanted}:
        session.delete(existing[ref])
    session.flush()
    return len(wanted)


def _unavailability(session: Session, timetable: Timetable, side: dict,
                    faculty: dict[str, Faculty]) -> int:
    wanted = {(faculty[u["faculty_id"]].id, u["day"], p): u["label"]
              for u in side["unavailability"] for p in u["periods"]}
    rows = {(r.faculty_id, r.day, r.period): r for r in session.scalars(
        select(FacultyUnavailability).where(FacultyUnavailability.timetable_id == timetable.id))}
    for key, label in wanted.items():
        row = rows.get(key)
        if row is None:
            fid, day, period = key
            row = FacultyUnavailability(timetable_id=timetable.id, faculty_id=fid, day=day,
                                        period=period)
            session.add(row)
        row.reason = label
    for key in set(rows) - set(wanted):
        session.delete(rows[key])
    session.flush()
    return len(wanted)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="ingestion.v2 payload")
    parser.add_argument("--frozen", type=Path, default=FROZEN_JSON, help="D39 side file")
    args = parser.parse_args(argv)
    payload, side = load_files(args.json, args.frozen)
    engine = create_engine(local_database_url())
    with Session(engine) as session, session.begin():
        counts = seed_even(session, payload, side)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
