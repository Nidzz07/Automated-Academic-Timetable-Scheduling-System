"""S14f / D53: qualifications.json is generated from SPIT's faculty-subject sheets."""

from __future__ import annotations

import json

import pytest

from ingestion.qualifications import DEFAULT_OUT, INSTANCE_DIR, build, dumps, session_type


@pytest.fixture(scope="module")
def built() -> dict:
    return build()


def test_committed_file_is_fresh(built: dict) -> None:
    assert DEFAULT_OUT.read_text(encoding="utf-8") == dumps(built), (
        "qualifications.json is stale: run python -m ingestion.qualifications")


def test_every_instance_subject_is_covered(built: dict) -> None:
    display = json.loads((INSTANCE_DIR / "display.json").read_text(encoding="utf-8"))
    assert set(built["subjects"]) == set(display["subjects"])
    for sid, entry in built["subjects"].items():
        assert entry["code"] == display["subjects"][sid]["code"]
        assert {f["faculty_id"] for f in entry["faculty"]} <= set(display["faculty"])
    without = [s for s, e in built["subjects"].items() if not e["faculty"]]
    assert built["subjects_without_qualified_faculty"] == without


def test_rows_of_the_sheets(built: dict) -> None:
    # Faculty___Subjects.xlsx: "Swapnali Kurhade | OS"; class_tt maps OS to CE206
    os_ = built["subjects"]["subj-ce206"]
    assert os_["sheet_codes"] == ["OS"]
    assert {"faculty_id": "fac-swapnali-kurhade", "session_type": None} in os_["faculty"]
    # "Devop" reaches CE308 only through the hand-reviewed alias
    assert built["subjects"]["subj-ce308"]["sheet_codes"] == ["Devop"]
    assert "SMCS" in built["sheet_codes_not_in_instance"]  # CE205 is not in the instance


@pytest.mark.parametrize("code, kind", [
    ("ET Lab", "lab"), ("MDM-III Lab (CC)", "lab"), ("MDM-III Theory (CC)", "theory"),
    ("OS", None), ("MDM-I (DBMS)", None),
])
def test_session_type_only_where_the_sheet_says(code: str, kind: str | None) -> None:
    assert session_type(code) == kind


def test_an_unknown_name_is_listed_never_guessed() -> None:
    display = json.loads((INSTANCE_DIR / "display.json").read_text(encoding="utf-8"))
    renamed = {fid: name for fid, name in display["faculty"].items()}
    renamed["fac-swapnali-kurhade"] = "Dr. Swapnali Kurhade"  # no longer the sheet spelling
    built = build(display | {"faculty": renamed})
    assert {"name": "Swapnali Kurhade", "sheet_codes": ["OS"]} in built["unmatched_names"]
    ids = {f["faculty_id"] for f in built["subjects"]["subj-ce206"]["faculty"]}
    assert "fac-swapnali-kurhade" not in ids
