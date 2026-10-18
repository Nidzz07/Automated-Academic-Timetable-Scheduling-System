"""Tests for the real EVEN SE+TE ingestion.v2 payload. No database is touched."""

from __future__ import annotations

import copy

import pytest

from ingestion.anomalies import load_sources
from ingestion.emit_v2 import (
    Instance,
    InstanceError,
    build,
    covered,
    dumps,
    lunch_violations,
    summary,
    validate,
)


@pytest.fixture(scope="module")
def inst() -> Instance:
    return build(load_sources())


def test_payload_is_valid(inst: Instance) -> None:
    validate(inst.payload)  # raises on any schema, reference or lunch problem


def test_deterministic(inst: Instance) -> None:
    assert dumps(build(inst.sources).payload) == dumps(inst.payload)


def test_summary(inst: Instance) -> None:
    s = summary(inst)
    assert (s["divisions"], s["batches"]) == (8, 32)
    # D44 freezes AS201 PCS (16 practicals, 4 tutorials); D38 leaves nobody teacherless.
    assert s["sessions_by_type"] == {"frozen": 74, "lecture": 56, "practical": 96, "tutorial": 4}
    assert s["sessions_faculty"] == {"resolved": 230, "ambiguous": 0, "unresolved": 0}
    assert s["frozen_sessions_by_decision"] == {"D24": 39, "D26": 15, "D44": 20}
    assert s["side_blocks_by_decision"] == {"D24": 5, "D35": 58, "D37": 1}
    assert s["faculty"] == 41
    assert s["rooms"] == {"class": 4, "unknown": 0, "lab": 9, "sub_rooms": 12}  # D42
    assert s["lab_batch_place_periods"]["places_per_period"] == 16
    assert s["classroom_periods"]["demand"] == 60
    assert s["lab_batch_place_periods"]["demand"] == 192
    assert s["faculty_unavailable_slots"] == 9  # D36: one day, every period but the coffee break


def test_breaks_per_row_8(inst: Instance) -> None:
    breaks = [b for b in inst.payload["pinned_blocks"] if b["kind"] == "break"]
    coffee = [b for b in breaks if b["cohort_id"] is None]
    assert [(b["day"], b["period"]) for b in coffee] == [(d, 2) for d in range(5)]
    lunch = [b for b in breaks if b["cohort_id"] is not None]
    assert len(lunch) == 8 * 5
    assert {b["period"] for b in lunch if b["cohort_id"].startswith("coh-se-")} == {5}
    assert {b["period"] for b in lunch if b["cohort_id"].startswith("coh-te-")} == {4}


def test_tutorials_are_division_wide(inst: Instance) -> None:
    tutorials = [r for r in inst.payload["observed_sessions"] if inst.kinds[r["id"]] == "tutorial"]
    assert len(tutorials) == 4  # DevOps; the PCS tutorials are frozen (D44)
    assert all(r["cohort_id"].count("-") == 2 and r["duration_periods"] == 1 for r in tutorials)


def test_frozen_items(inst: Instance) -> None:
    ids = {r["id"] for r in inst.payload["observed_sessions"]} | \
        {b["id"] for b in inst.payload["pinned_blocks"]}
    assert all(f["id"] in ids for f in inst.frozen)
    assert {f["resolution"] for f in inst.frozen} == {"D24", "D26", "D44"}
    d44 = [f for f in inst.frozen if f["resolution"] == "D44"]
    assert len(d44) == 20 and all(f["label"].startswith("PCS") for f in d44)
    # A frozen practical is in no lab block; a frozen PCS practical holds its batch only.
    blocked = {sid for b in inst.payload["lab_blocks"] for sid in b["parallel_session_ids"]}
    assert not blocked & {f["id"] for f in inst.frozen}
    pcs = next(r for r in inst.payload["observed_sessions"] if r["id"] == d44[1]["id"])
    assert pcs["cohort_id"] == "coh-se-a-d" and pcs["session_type"] == "lab"
    smcs = [f for f in inst.frozen if f["label"].startswith("SMCS")]
    assert len(smcs) == 12  # D26: SMCS frozen in all four SE divisions
    # An elective printed in all four TE grids is one session.
    nlp = [r for r in inst.payload["observed_sessions"]
           if r["source_cell"].startswith("NLP / PE-I-A / RK")]
    assert len(nlp) == 1


def test_manual_initials_d25_d38(inst: Instance) -> None:
    manual = {(r["initials"], r["faculty_id"], r["division_id"])
              for r in inst.payload["faculty_initials"] if r["source"] == "manual"}
    assert manual == {
        ("SRD", "fac-surekha-dholay", None),  # D25
        ("AGN", "fac-amey-ganesh-nile", "div-se-a"), ("AGN", "fac-amey-ganesh-nile", "div-te-b"),
        ("PBB", "fac-prasenjit-bhavathankar", "div-se-a"), ("NR", "fac-nataasha-raul", "div-se-c"),
        ("IS", "fac-isha-sawalkar", "div-se-d"), ("SM", "fac-sudeep-mali", "div-te-b"),
        ("AT", "fac-anuj-tawari", "div-te-c"),
        # MDM lab cells name no division.
        ("RS", "fac-rupali-sawant", None), ("SB", "fac-soni-bhambar", None),
    }
    # D38 keeps initials scoped by year: SM is Suman M. in SE, Sudeep Mali in TE.
    sm = {(r["faculty_id"], r["division_id"][:6]) for r in inst.payload["faculty_initials"]
          if r["initials"] == "SM"}
    assert {f for f, d in sm if d == "div-se"} == {"fac-suman-m"}
    assert {f for f, d in sm if d == "div-te"} == {"fac-sudeep-mali"}


def test_teacherless_session_fails(inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    payload["observed_sessions"][0]["faculty_id"] = None
    with pytest.raises(InstanceError, match="resolves to nobody"):
        validate(payload)


def test_side_file(inst: Instance) -> None:
    side = inst.side_file("ingestion_v2_even.json")
    assert set(side) == {"generated_by", "payload", "note", "frozen", "blocks",
                         "unavailability", "faculty"}
    blocks = side["blocks"]
    # D37: the DAA lab exam holds sub-room 603-2, Wednesday P3-P4, and nothing else.
    [exam] = [b for b in blocks if b["resolution"] == "D37"]
    assert (exam["day"], exam["period"], exam["duration_periods"], exam["sub_room_id"],
            exam["room_id"], exam["faculty_id"]) == (2, 3, 2, "sub-603-2", "room-603", None)
    # D35: M.Tech DCS, printed in all three timetables, is one block in lab 604.
    dcs = next(b for b in blocks if b["day"] == 1 and b["label"].startswith("DCS"))
    assert (dcs["period"], dcs["faculty_id"], dcs["room_id"]) == (5, "fac-sudhir-dhage",
                                                                 "room-604")
    assert len(dcs["sources"]) == 3
    # FE teaching is printed only in the faculty timetable; room 003 is not D10.
    psoop = [b for b in blocks if b["label"].startswith("PSOOP")]
    assert len(psoop) == 27 and all(b["faculty_id"] and b["room_id"] is None for b in psoop)
    assert all(b["faculty_id"] or b["room_id"] or b["sub_room_id"] for b in blocks)
    assert {b["kind"] for b in blocks} == {"out_of_scope", "mdm", "exam"}
    # D36
    assert side["unavailability"] == [{
        "faculty_id": "fac-swapnali-kurhade", "day": 0, "periods": [0, 1, 3, 4, 5, 6, 7, 8, 9],
        "label": "PHD Day OFF", "resolution": "D36",
        "source": "Faculty Individual timetable Even 2025-26.docx t8 Swapnali Kurhade"}]


def test_faculty_names_and_aliases_d45(inst: Instance) -> None:
    meta = {f["full_name"]: f for f in inst.faculty_meta}
    assert sum(f["source"] == "spreadsheet" for f in inst.faculty_meta) == 32
    assert meta["Dr. Deepak Nair"]["source"] == "manual"
    aliases = {name: [a["alias"] for a in f["aliases"]] for name, f in meta.items()
               if f["aliases"]}
    assert aliases == {
        "Amey Ganesh Nile": ["Mr. Amey Nile"], "Anand Godbole": ["Prof. A. A. Godbole"],
        "C R Gajbiye": ["Prof. C. R. Gajbhiye"], "Dayanand Ambawade": ["Dr. D. D. Ambawade"],
        "Prasenjit Bhavathankar": ["Dr. P. B. Bhavathankar"],
        "Prof. Sonali Dudhihalli": ["Prof. Sonali D."],
        "Surekha Dholay": ["Dr. Dholay Surekha Rajesh"],
        "Vaishnavee Rathod": ["Prof. Vaishnavi Rathod"],
        "Vandana Wekhande": ["Prof. Vandana Wekhende"],
    }


def test_covered_skips_coffee_not_lunch() -> None:
    assert covered(1, 2) == [1, 3]
    assert covered(4, 2) == [4, 5]
    assert covered(9, 2) == [9]


def _first(payload: dict, cohort_prefix: str) -> dict:
    return next(r for r in payload["observed_sessions"]
                if r["cohort_id"].startswith(cohort_prefix) and r["session_type"] == "theory")


def test_lunch_rule_rejects_own_year_lunch(inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    assert lunch_violations(payload) == []
    se = _first(payload, "coh-se-")
    se["period"], se["duration_periods"] = 4, 2  # P4-P5: across SE lunch
    te = _first(payload, "coh-te-")
    te["period"] = 4  # TE lunch
    problems = lunch_violations(payload)
    assert len(problems) == 2
    assert any("SE session in its lunch period P5" in p for p in problems)
    assert any("TE session in its lunch period P4" in p for p in problems)
    with pytest.raises(InstanceError, match="lunch"):
        validate(payload)


def test_lunch_rule_allows_other_years_lunch(inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    _first(payload, "coh-se-")["period"] = 4  # TE's lunch, a teaching period for SE
    assert lunch_violations(payload) == []


def test_schema_errors_fail_loudly(inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    del payload["observed_sessions"][0]["source_cell"]
    payload["rooms"][0]["room_type"] = "hall"
    with pytest.raises(InstanceError, match="2 problem"):
        validate(payload)


def test_broken_reference_fails(inst: Instance) -> None:
    payload = copy.deepcopy(inst.payload)
    payload["observed_sessions"][0]["cohort_id"] = "coh-nowhere"
    with pytest.raises(InstanceError, match="coh-nowhere"):
        validate(payload)
