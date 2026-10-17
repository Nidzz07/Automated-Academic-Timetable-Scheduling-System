"""Tests for the combined EVEN anomaly report, on the real files."""

from __future__ import annotations

import json
import re

import pytest

from ingestion.anomalies import DEFAULT_REPORT, Anomaly, Sources, build, to_json


@pytest.fixture(scope="module")
def built() -> tuple[Sources, list[Anomaly], str]:
    return build()


def test_committed_report_is_current(built) -> None:
    assert DEFAULT_REPORT.read_text(encoding="utf-8") == built[2]


def test_every_anomaly_is_complete(built) -> None:
    _, anomalies, _ = built
    for a in anomalies:
        assert a.category and a.source_file and a.location and a.message
        assert a.resolution == "needs human" or re.fullmatch(r"D\d+", a.resolution), a


def _resolutions(anomalies: list[Anomaly], category: str) -> set[str]:
    return {a.resolution for a in anomalies if a.category == category}


def test_decisions_applied(built) -> None:
    _, anomalies, _ = built
    assert _resolutions(anomalies, "division_wide_tutorial") == {"D23"}
    assert _resolutions(anomalies, "unmatched_subject") == {"D26"}
    assert _resolutions(anomalies, "parallel_division_sessions") == {"D26"}
    assert _resolutions(anomalies, "frozen_d26") == {"D26"}
    assert _resolutions(anomalies, "excluded_item") == {"D24", "D26"}
    srd = [a for a in anomalies if a.category == "initials_not_in_division_legend"
           and a.message.startswith("SRD ")]
    assert len(srd) == 4 and {a.resolution for a in srd} == {"D25"}
    # D38: every other initial missing from its division's legend.
    assert _resolutions(anomalies, "initials_not_in_division_legend") == {"D25", "D38"}
    assert _resolutions(anomalies, "initials_resolved_d38") == {"D38"}
    assert _resolutions(anomalies, "frozen_d44") == {"D44"}
    assert len([a for a in anomalies if a.category == "frozen_d44"]) == 20
    assert _resolutions(anomalies, "out_of_scope_in_lab") == {"D35"}
    assert _resolutions(anomalies, "frozen_out_of_scope") == {"D35"}
    assert _resolutions(anomalies, "frozen_faculty_tt_mdm") == {"D24"}
    assert _resolutions(anomalies, "frozen_exam") == {"D37"}
    assert _resolutions(anomalies, "faculty_day_off") == {"D36"}
    assert _resolutions(anomalies, "unknown_room_usage") == {"D42"}


def test_lecture_rooms(built) -> None:
    _, anomalies, _ = built
    rooms = {a.location: a.resolution for a in anomalies
             if a.category == "lecture_room_excluded"}
    assert rooms == {"room 002": "D10", "room 202": "D29", "room 203": "D10", "room 307": "D29",
                     "room 508": "D10"}
    [total] = [a for a in anomalies if a.category == "lecture_room_total"]
    # D44 freezes the PCS tutorials; D42 makes 605 and 609 classrooms.
    assert total.message.startswith("53 of 60 ")


def test_json_counts(built) -> None:
    _, anomalies, _ = built
    data = json.loads(to_json(anomalies))
    assert data["counts"]["total"] == len(anomalies) == len(data["anomalies"])
    assert set(data["anomalies"][0]) == {"category", "source_file", "location", "message",
                                         "resolution"}
