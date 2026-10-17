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
    assert s["sessions_by_type"] == {"frozen": 54, "lecture": 56, "practical": 112, "tutorial": 8}
    assert s["sessions_faculty"] == {"resolved": 218, "ambiguous": 0, "unresolved": 12}
    assert s["faculty"] == 41
    assert s["rooms"] == {"class": 2, "unknown": 2, "lab": 9, "sub_rooms": 12}
    assert s["lab_batch_place_periods"]["places_per_period"] == 16
    assert s["classroom_periods"]["demand"] == 64
    assert s["lab_batch_place_periods"]["demand"] == 224


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
    assert len(tutorials) == 8
    assert all(r["cohort_id"].count("-") == 2 and r["duration_periods"] == 1 for r in tutorials)


def test_frozen_items(inst: Instance) -> None:
    ids = {r["id"] for r in inst.payload["observed_sessions"]} | \
        {b["id"] for b in inst.payload["pinned_blocks"]}
    assert all(f["id"] in ids for f in inst.frozen)
    assert {f["resolution"] for f in inst.frozen} == {"D24", "D26"}
    smcs = [f for f in inst.frozen if f["label"].startswith("SMCS")]
    assert len(smcs) == 12  # D26: SMCS frozen in all four SE divisions
    # An elective printed in all four TE grids is one session.
    nlp = [r for r in inst.payload["observed_sessions"]
           if r["source_cell"].startswith("NLP / PE-I-A / RK")]
    assert len(nlp) == 1


def test_srd_is_a_manual_mapping(inst: Instance) -> None:
    [row] = [r for r in inst.payload["faculty_initials"] if r["source"] == "manual"]
    assert (row["initials"], row["faculty_id"], row["division_id"]) == \
        ("SRD", "fac-surekha-dholay", None)


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
