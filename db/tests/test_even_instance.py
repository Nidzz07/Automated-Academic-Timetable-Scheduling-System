"""The real EVEN SE+TE instance in the database: seed (ingestion.seed_even) and
export (db.export_edge_list), on the real files and the LOCAL Docker Postgres.

One scratch database is migrated to head (so migration 0005 is exercised), given
the reference and legend seeds, then the instance built in memory by
``ingestion.emit_v2`` (data/generated is gitignored). Skips without a local
database, like db/tests/test_models.py; a skip is not a pass.
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession

from db.export_edge_list import OUT_DIR, SCHEMA, dumps, export
from db.local_guard import local_database_url
from db.models import (
    Base,
    FacultyUnavailability,
    PinnedBlock,
    PinnedKind,
    Room,
    Timetable,
)
from db.models import Session as SessionRow
from ingestion.emit_v2 import Instance, build, summary
from ingestion.lab_tt import load_lab_capacities
from ingestion.seed_even import TIMETABLE_NAME, seed_even
from ingestion.seed_legends import seed_legend_data
from ingestion.seed_reference import SeedBlocked, seed_reference_data

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "postgres"})
DB_NAME = "chronos_even_instance_test"


def _base_url() -> str:
    override = os.environ.get("CHRONOS_TEST_DATABASE_URL")
    if override:
        return override
    port = os.environ.get("CHRONOS_DB_PORT", "5432")
    return f"postgresql+psycopg2://chronos:chronos@127.0.0.1:{port}/chronos"


def _host_of(url: str) -> str:
    match = re.search(r"@([^/:?]+)", url)
    return match.group(1) if match else ""


def _with_database(url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?|$)", f"/{name}\\1", url)


BASE_URL = _base_url()
if _host_of(BASE_URL) not in LOCAL_HOSTS:
    pytest.skip(f"refusing to seed non-local host {_host_of(BASE_URL)!r}", allow_module_level=True)


def _admin():
    return create_engine(_with_database(BASE_URL, "postgres"), isolation_level="AUTOCOMMIT")


def _drop(conn) -> None:
    conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                      "WHERE datname = :n AND pid <> pg_backend_pid()"), {"n": DB_NAME})
    conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))


try:
    with _admin().connect() as _probe:
        _probe.execute(text("SELECT 1"))
except OperationalError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"local Postgres not reachable ({exc.__class__.__name__})",
                allow_module_level=True)


@pytest.fixture(scope="module")
def inst() -> Instance:
    return build()


@pytest.fixture(scope="module")
def engine(inst: Instance):
    from alembic import command
    from alembic.config import Config

    with _admin().connect() as conn:
        _drop(conn)
        conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    url = _with_database(BASE_URL, DB_NAME)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(repo, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo, "migrations"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    eng = create_engine(url)
    with OrmSession(eng) as session, session.begin():
        seed_reference_data(session)
        seed_legend_data(session)
        seed_even(session, inst.payload, inst.side_file("ingestion_v2_even.json"))
    yield eng
    eng.dispose()
    with _admin().connect() as conn:
        _drop(conn)


@pytest.fixture(scope="module")
def exported(engine) -> tuple[dict, dict]:
    with OrmSession(engine) as session:
        return export(session)


def _snapshot(engine) -> dict[str, list[tuple]]:
    with engine.connect() as conn:
        return {t.name: [tuple(r) for r in conn.execute(
                    select(t).order_by(*t.primary_key.columns))]
                for t in Base.metadata.sorted_tables}


# --------------------------------------------------------------------------- #
# Seeder
# --------------------------------------------------------------------------- #


def test_seeded_rows(engine, inst: Instance) -> None:
    s = summary(inst)
    with OrmSession(engine) as session:
        tt = session.scalar(select(Timetable).where(Timetable.name == TIMETABLE_NAME))
        assert (tt.semester_id, tt.term_code.value, tt.academic_year) == (None, "EVEN", "2025-2026")
        rows = list(session.scalars(select(SessionRow).where(SessionRow.timetable_id == tt.id)))
        assert len(rows) == sum(s["sessions_by_type"].values())
        assert Counter(r.frozen_by for r in rows if r.frozen_by) == Counter(
            s["frozen_sessions_by_decision"])
        assert all(r.faculty_id for r in rows)  # D38: nobody teacherless
        assert sorted(r.code for r in tt.rooms) == [
            "507", "509", "601", "603", "604", "605", "606", "607B", "608", "609", "701", "702",
            "703"]
        # Room rows are reference data: 509 keeps classrooms.xlsx's 20 seats; its two
        # lab_capacities.yaml places are sub-rooms (D27).
        r509 = next(r for r in tt.rooms if r.code == "509")
        assert (r509.capacity, sorted(s.label for s in r509.sub_rooms)) == (20, ["1", "2"])
        pins = list(session.scalars(select(PinnedBlock).where(PinnedBlock.timetable_id == tt.id)))
        kinds = Counter(p.kind for p in pins)
        assert kinds[PinnedKind.OUT_OF_SCOPE] == s["side_blocks_by_decision"]["D35"]
        [exam] = [p for p in pins if p.kind is PinnedKind.EXAM]
        assert (exam.day, exam.period, exam.sub_room.label, exam.faculty_id) == (2, 3, "2", None)
        dcs = next(p for p in pins if p.kind is PinnedKind.OUT_OF_SCOPE and p.day == 1
                   and p.label.startswith("DCS"))
        assert (dcs.faculty.full_name, dcs.room.code, dcs.period) == ("Sudhir Dhage", "604", 5)
        off = list(session.scalars(select(FacultyUnavailability)))
        assert {(u.faculty.full_name, u.day) for u in off} == {("Swapnali Kurhade", 0)}
        assert len(off) == s["faculty_unavailable_slots"]


def test_seeding_twice_changes_nothing(engine, inst: Instance) -> None:
    before = _snapshot(engine)
    with OrmSession(engine) as session, session.begin():
        seed_even(session, inst.payload, inst.side_file("ingestion_v2_even.json"))
    assert _snapshot(engine) == before


def test_stale_rows_are_removed(engine, inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    gone = payload["observed_sessions"].pop()
    with OrmSession(engine) as session, session.begin():
        counts = seed_even(session, payload, inst.side_file("x"))
        assert counts["deleted_sessions"] == 1
        assert session.scalar(select(SessionRow).where(
            SessionRow.source_ref == gone["id"])) is None
        session.rollback()


def test_missing_room_stops_the_seed(engine, inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    payload["rooms"][0]["code"] = "999"
    with OrmSession(engine) as session, session.begin():
        with pytest.raises(SeedBlocked, match="room 999"):
            seed_even(session, payload, inst.side_file("x"))
        session.rollback()
    assert _snapshot(engine)["room"] != []


def test_non_local_database_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.supabase.co:5432/postgres")
    monkeypatch.delenv("CHRONOS_ALLOW_REMOTE_DB", raising=False)
    with pytest.raises(SystemExit, match="not local"):
        local_database_url()


# --------------------------------------------------------------------------- #
# Exporter
# --------------------------------------------------------------------------- #


def test_edge_list_validates(exported) -> None:
    edge_list, _ = exported
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(edge_list)) == []


def test_counts_equal_the_instance_summary(exported, inst: Instance) -> None:
    edge_list, display = exported
    s = summary(inst)
    by_type = s["sessions_by_type"]
    assert len(edge_list["sessions"]) == by_type["lecture"] + by_type["tutorial"] + \
        by_type["practical"]
    assert Counter(x["requires_lab"] for x in edge_list["sessions"]) == {
        True: by_type["practical"], False: by_type["lecture"] + by_type["tutorial"]}
    assert len(edge_list["lab_blocks"]) == s["lab_blocks"]
    refs = {kind: {p.get("source_ref") for p in display["pins"] if p["kind"] == kind}
            for kind in {p["kind"] for p in display["pins"]}}
    assert len(refs["frozen"]) == s["frozen_sessions"]
    label_only = sum(len(refs[k]) for k in ("mdm", "hss", "llc", "activity", "project"))
    assert label_only + len(refs["out_of_scope"]) + len(refs["exam"]) == \
        s["frozen_pinned_blocks"] + sum(s["side_blocks_by_decision"].values())
    assert len(refs["lunch"]) == 1 and sum(p["kind"] == "lunch" for p in display["pins"]) == 10
    assert len(display["pins"]) == len(edge_list["pinned_occupancy"])
    rooms = edge_list["rooms"]
    assert sum(r["parent_room_id"] is None for r in rooms) == s["rooms"]["class"] + \
        s["rooms"]["lab"]
    assert sum(r["parent_room_id"] is not None for r in rooms) == s["rooms"]["sub_rooms"]
    assert sum(len(f["unavailable_slots"]) for f in edge_list["faculty_availability"]) == \
        s["faculty_unavailable_slots"]


def test_every_cohort_of_a_year_is_in_its_lunch_pins(exported) -> None:
    edge_list, display = exported
    lunch = {"SE": 5, "TE": 4}
    named = {x["cohort_id"] for x in edge_list["sessions"]} | {
        c for p in edge_list["pinned_occupancy"] for c in p["cohort_ids"]}
    for year, period in lunch.items():
        pins = [p for p, d in zip(edge_list["pinned_occupancy"], display["pins"], strict=True)
                if d["kind"] == "lunch" and d["year"] == year]
        assert sorted(p["day"] for p in pins) == [0, 1, 2, 3, 4]
        assert {p["period"] for p in pins} == {period}
        mine = {c for c in named if year in display["cohorts"][c]["years"]}
        assert mine and all(mine <= set(p["cohort_ids"]) for p in pins)
        assert all(p["faculty_ids"] == p["room_ids"] == [] for p in pins)


def test_candidate_rooms_respect_d8_d10_and_capacity(exported) -> None:
    edge_list, _ = exported
    rooms = {r["id"]: r for r in edge_list["rooms"]}
    labs = {lab["room"] for lab in load_lab_capacities()["labs"] if lab["btech_use"]}
    for s in edge_list["sessions"]:
        fits = [r for r in rooms.values() if r["capacity"] >= s["cohort_size"]
                and (r["is_lab"] or not s["requires_lab"])]
        assert fits, s["id"]
        for r in fits:
            parent = rooms[r["parent_room_id"]] if r["parent_room_id"] else r
            if s["requires_lab"]:
                assert r["is_lab"] and parent["code"] in labs  # D8
            else:  # lectures and division tutorials (D23): a 6th/7th-floor classroom (D10)
                assert not r["is_lab"] and parent["code"][0] in "67" and r["capacity"] >= 80


def test_structure_the_solver_reads(exported) -> None:
    edge_list, _ = exported
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    assert len(sessions) == len(edge_list["sessions"])
    available = {f["faculty_id"] for f in edge_list["faculty_availability"]}
    assert {s["faculty_id"] for s in sessions.values()} <= available
    for blk in edge_list["lab_blocks"]:
        assert {sessions[sid]["duration_periods"] for sid in blk["session_ids"]} == \
            {blk["duration_periods"]}
    assert all(e["u"] in sessions and e["v"] in sessions for e in edge_list["edges"])
    teaching = set(edge_list["slot_grid"]["teaching_periods"])
    assert all(p["period"] in teaching for p in edge_list["pinned_occupancy"])
    room_ids = {r["id"] for r in edge_list["rooms"]}
    assert all(set(p["room_ids"]) <= room_ids for p in edge_list["pinned_occupancy"])


def test_display_feeds_the_ui(exported) -> None:
    edge_list, display = exported
    cohorts = display["cohorts"]
    # batches: unique readable labels, and each division's batch ids
    batches = {cid: c for cid, c in cohorts.items() if c["type"] == "batch"}
    assert cohorts["coh-se-a-a"]["label"] == "SE-Comp A batch A"
    assert len({c["label"] for c in batches.values()}) == len(batches) == 32
    # S14r: every cohort's label is unique and readable, never an id; lab groups that share
    # a name get the batch letter their cells print, else their printed slots
    labels = [c["label"] for c in cohorts.values()]
    assert len(set(labels)) == len(labels) == len(cohorts)
    assert not any("coh-" in label or "grp-" in label for label in labels)
    assert {cohorts[cid]["label"] for cid in (
        "coh-grp-mdm-dbms-lab-t7-r8-c1", "coh-grp-mdm-dbms-lab-t7-r8-c2",
        "coh-grp-mdm-iii-lab-cc-lab-t11-r8-c2", "coh-grp-mdm-iii-lab-cc-lab-t8-r8-c3")} == {
        "MDM-DBMS, Mon P7\u2013P8", "MDM-DBMS, Tue P7\u2013P8",
        "MDM-III Lab (CC) batch A", "MDM-III Lab (CC) batch B"}
    assert all(c["label"] == c["name"] for c in cohorts.values() if c["type"] == "division")
    assert sorted(b for ids in display["batches"].values() for b in ids) == sorted(batches)
    assert {cohorts[d]["type"] for d in display["batches"]} == {"division"}
    assert display["batches"]["coh-te-b"] == ["coh-te-b-a", "coh-te-b-b", "coh-te-b-c",
                                              "coh-te-b-d"]
    # initials per year (D38: SD and SM name different people in SE and TE; D25 SRD)
    initials = display["initials"]
    assert set(initials) == set(display["faculty"])
    assert initials["fac-sonali-dudhihalli"] == {"SE": ["SD"]}
    assert initials["fac-surekha-dholay"] == {"TE": ["SD"], "unscoped": ["SRD"]}
    assert initials["fac-suman-m"] == {"SE": ["SM"]}
    assert initials["fac-sudeep-mali"] == {"TE": ["SM"]}
    assert initials["fac-amey-ganesh-nile"]["SE"] == initials["fac-amey-ganesh-nile"]["TE"] == [
        "AGN"]
    # pins: one unique label per pinned block, and pins[i] still describes pinned_occupancy[i]
    blocks = {p.get("source_ref") or (p["label"], occ["day"]): p["unique_label"]
              for p, occ in zip(display["pins"], edge_list["pinned_occupancy"], strict=True)}
    assert len(set(blocks.values())) == len(blocks)
    assert {"MDM-DBMS /RS, Mon P7\u2013P8, 603", "MDM-DBMS /RS, Tue P7\u2013P8, 603",
            "SE lunch, Mon P5", "LLC, Thu P9, SE-Comp A"} <= set(blocks.values())
    for p, occ in zip(display["pins"], edge_list["pinned_occupancy"], strict=True):
        assert p["unique_label"].startswith(p["label"])
        if p["unique_label"] != p["label"]:
            assert f", {display['days'][occ['day']][:3]} P" in p["unique_label"]
        # S14r: every pin with a teacher names them; initials only as the label prints them
        assert [f["id"] for f in p["faculty"]] == occ["faculty_ids"]
        for f in p["faculty"]:
            assert f["name"] == display["faculty"][f["id"]]
            assert all(re.search(rf"\b{i}\b", p["label"]) for i in f["initials"])


def test_pin_teachers_by_name(exported) -> None:
    edge_list, display = exported
    teachers = {(p["label"], f["name"], tuple(f["initials"]))
                for p in display["pins"] for f in p["faculty"]}
    # D38: SM and SD name different people in SE and TE; D25: SRD; D44: legend-only faculty
    assert {("PCS / A / SM / 607-B", "Suman M.", ("SM",)),
            ("PCS / A / SD / 609", "Sonali Dudhihalli", ("SD",)),
            ("DL / PE-I-B / SRD 702-B", "Surekha Dholay", ("SRD",)),
            ("PCS / A / DN / 605", "Deepak Nair", ("DN",)),
            ("FOM - II / AsT /307", "Asma Tambe", ("AsT",)),
            ("PSOOP / A1 / 003", "Pramod Bide", ())} <= teachers
    # names carry a title for no one: the faculty sheets give none (S14r)
    assert not any(re.match(r"(Prof|Dr)\.", name) for name in display["faculty"].values())
    # pins whose teacher the seed could not name keep none (reported, never guessed)
    unnamed = {p["label"] for p, occ in zip(display["pins"], edge_list["pinned_occupancy"],
                                            strict=True) if not occ["faculty_ids"]}
    assert {"PCS /SV / 507 new", "DAA | LAB EXAM ESE | SE COMP NR"} <= unnamed


def test_re_export_is_byte_identical_and_committed(engine, exported) -> None:
    with OrmSession(engine) as session:
        again = export(session)
    assert [dumps(x) for x in again] == [dumps(x) for x in exported]
    for name, data in zip(("edge_list.json", "display.json"), exported, strict=True):
        assert (OUT_DIR / name).read_text(encoding="utf-8") == dumps(data), (
            f"{name} is stale: run python -m ingestion.seed_even and python -m db.export_edge_list")


def test_rooms_are_not_rewritten(engine) -> None:
    with OrmSession(engine) as session:
        assert session.query(Room).filter(Room.code == "509").count() == 1
