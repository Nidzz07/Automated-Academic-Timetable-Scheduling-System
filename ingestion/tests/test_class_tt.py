"""Tests for the EVEN class-timetable parser, against the real .docx.

Pinned cells were checked by eye against the document. The invariant tests
prove nothing is dropped: every non-empty line of every parsed grid cell is
an entry (or a note attached to one), and every table is either parsed or
listed as skipped with a reason.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from ingestion.class_tt import (
    DEFAULT_REPORT,
    ELECTIVE_REASON,
    EVEN_CLASS_FILE,
    HAND_REVIEWED_ALIASES,
    SUBJECT_ALIASES,
    ClassTimetable,
    Entry,
    FacultyIndex,
    build,
    faculty_index,
    parse_class_timetable,
    period_of,
    to_json,
)
from ingestion.docx_reader import logical_cells, open_document, walk_body
from ingestion.scheme import load_scheme

PARSED = [0, 2, 4, 6, 8, 10, 12, 14]


@pytest.fixture(scope="module")
def faculty() -> FacultyIndex:
    return faculty_index()


@pytest.fixture(scope="module")
def tt(faculty: FacultyIndex) -> ClassTimetable:
    return parse_class_timetable(faculty=faculty)


def _at(tt: ClassTimetable, table: int, row: int, col: int) -> list[Entry]:
    return [e for e in tt.entries if (e.table, e.row, e.col) == (table, row, col)]


# --------------------------------------------------------------------------- #
# Time grid
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "period"),
    [
        ("9.00-10.00", 0),
        ("\n9.00-10.00", 0),
        ("11:00-11:15", 2),
        ("11.15-12.15", 3),
        ("12.15-1.15", 4),
        ("1.15-2.15", 5),
        ("5.15-6:15", 9),
        ("9.30-10.30", None),
        ("Time", None),
    ],
)
def test_period_of(text: str, period: int | None) -> None:
    assert period_of(text) == period


# --------------------------------------------------------------------------- #
# Tables and coverage
# --------------------------------------------------------------------------- #


def test_only_se_and_te_grids_are_parsed(tt: ClassTimetable) -> None:
    assert [t.index for t in tt.tables if t.parsed] == PARSED
    assert [t.division for t in tt.tables if t.parsed] == [
        "SE-Comp A", "SE-Comp B", "SE-Comp C", "SE-Comp D",
        "TE-Comp A", "TE Comp- B", "TE Comp - C", "TE Comp - D",
    ]
    assert len(tt.tables) == 21
    skipped = {t.index: t.skip_reason for t in tt.tables if not t.parsed}
    assert all(skipped.values())
    assert "D2" in skipped[17] and "D2" in skipped[19]  # BE, M.Tech
    assert all("legend" in skipped[i] for i in (1, 3, 5, 7, 9, 11, 13, 15, 16, 18, 20))


def test_every_cell_line_is_accounted_for(tt: ClassTimetable) -> None:
    tables = [el for kind, el in walk_body(open_document(EVEN_CLASS_FILE)) if kind == "table"]
    for index in PARSED:
        cells, _, _ = logical_cells(tables[index])
        expected = 0
        for c in cells:
            if c.row and c.col and "BREAK" not in "".join(c.text.split()).upper():
                expected += sum(1 for line in c.text.split("\n") if line.strip())
        mine = [e for e in tt.entries if e.table == index]
        got = sum(e.raw.count("\n") + 1 for e in mine)
        assert got == expected, index


def test_no_time_is_off_grid_and_breaks_are_where_d6_says(tt: ClassTimetable) -> None:
    kinds = {a.kind for a in tt.anomalies}
    assert not kinds & {"time_off_grid", "lunch_mismatch", "coffee_mismatch", "grid_shape"}
    for division, marked in tt.breaks.items():
        assert marked == {"coffee": [2], "lunch": [5 if division.startswith("SE") else 4]}


# --------------------------------------------------------------------------- #
# Pinned cells
# --------------------------------------------------------------------------- #


def test_se_a_lab_block(tt: ClassTimetable) -> None:
    # SE-Comp A, Monday 11.15-1.15: four parallel batch practicals.
    lines = _at(tt, 0, 4, 1)
    assert [e.raw for e in lines] == [
        "OS / A / AGN / 702-A",
        "DAA / B / NR / 603-2",
        "CCN / C / JS / 606-4",
        "PCS / D / DN / 608",
    ]
    for e in lines:
        assert (e.day, e.periods, e.start_period, e.duration) == ("Monday", [3, 4], 3, 2)
        assert e.time_raw == ["11.15-12.15", "12.15-1.15"]
        assert e.session_type == "practical" and not e.excluded
    os_, daa, _, pcs = lines
    assert (os_.scheme_code, os_.batch, os_.room_raw) == ("CE206", "A", "702-A")
    # AGN is not in SE-Comp A's own legend: flagged, never borrowed from SE-Comp B.
    assert (os_.faculty_status, os_.faculty_candidates) == ("not_in_division_legend", [])
    assert daa.faculty_candidates == ["Nataasha Raul"]
    assert (pcs.scheme_code, pcs.faculty_candidates) == ("AS201", ["Dr. Deepak Nair"])


def test_se_a_lecture(tt: ClassTimetable) -> None:
    [e] = _at(tt, 0, 1, 2)
    assert (e.raw, e.day, e.start_period, e.duration) == ("OS / KKD / 002", "Tuesday", 0, 1)
    assert (e.session_type, e.batch, e.faculty_candidates) == ("lecture", None, ["Kailas Devadkar"])


def test_te_practical_after_te_lunch(tt: ClassTimetable) -> None:
    # TE-Comp A Tuesday 1.15-3.15: P5 is a teaching period for TE (lunch is P4).
    lines = _at(tt, 8, 6, 2)
    assert {e.scheme_code for e in lines} == {"CE307", "CE306", "CE308"}
    for e in lines:
        assert (e.periods, e.duration, e.session_type) == ([5, 6], 2, "practical")


def test_division_wide_tutorial_is_flagged(tt: ClassTimetable) -> None:
    [e] = _at(tt, 0, 1, 4)  # 'PCS / DN / 002', Thursday 9-10
    assert (e.session_type, e.batch) == ("tutorial", None)
    flagged = [a for a in tt.anomalies if a.kind == "division_wide_tutorial"]
    assert len(flagged) == 8  # PCS in each SE division, DevOps in each TE division


def test_unresolved_initials_are_never_resolved(tt: ClassTimetable) -> None:
    srd = [e for e in tt.entries if e.faculty_initials_raw == "SRD"]
    assert srd and all(e.faculty_status == "not_in_division_legend" for e in srd)
    assert all(e.faculty_candidates == [] for e in srd)


# --------------------------------------------------------------------------- #
# Exclusions (D3)
# --------------------------------------------------------------------------- #


def test_labels_are_excluded_with_reasons(tt: ClassTimetable) -> None:
    reasons = {e.exclude_reason for e in tt.entries if e.excluded}
    for needle in ("minor (MDM)", "HSSM", "LLC", "project", "student activity", "elective"):
        assert any(needle in (r or "") for r in reasons), needle
    [mdm] = _at(tt, 8, 2, 1)  # TE-Comp A Monday: the minor's notes stay with it
    assert mdm.raw.splitlines()[1:] == [
        "( Except SPJIMR)",
        "Note: Barclays Minor in Banking is from 10.00am to 12.00pm in online mode",
    ]


def test_electives_include_lecture_lines_without_marker(tt: ClassTimetable) -> None:
    dl = [e for e in tt.entries if e.raw == "DL / SJ / 508"]
    assert dl and all(e.exclude_reason == ELECTIVE_REASON for e in dl)
    assert all(e.excluded for e in tt.entries if e.elective_group)


def test_fom_ii_is_unmatched_not_guessed(tt: ClassTimetable) -> None:
    fom = [e for e in tt.entries if e.subject_raw == "FOM - II"]
    assert len(fom) == 12
    assert all(e.scheme_code is None and e.exclude_reason.startswith("unmatched") for e in fom)


def test_non_ce_teacher_is_excluded(faculty: FacultyIndex) -> None:
    scope = next(s for s in faculty.by_scope if s.division == "SE-Comp A")
    by_scope = {**faculty.by_scope, scope: {**faculty.by_scope[scope], "KKD": ["Not CE"]}}
    tt = parse_class_timetable(faculty=dataclasses.replace(faculty, by_scope=by_scope))
    kkd = [e for e in tt.entries if e.division == "SE-Comp A" and e.faculty_initials_raw == "KKD"]
    assert kkd and all(e.exclude_reason == "teacher not in the CE faculty list - D3" for e in kkd)


def test_ambiguous_initials_keep_every_candidate(faculty: FacultyIndex) -> None:
    scope = next(s for s in faculty.by_scope if s.division == "SE-Comp A")
    both = ["Dr. Deepak Nair", "Jignesh Sisodia"]
    by_scope = {**faculty.by_scope, scope: {**faculty.by_scope[scope], "DN": both}}
    tt = parse_class_timetable(faculty=dataclasses.replace(faculty, by_scope=by_scope))
    dn = [e for e in tt.entries if e.division == "SE-Comp A" and e.faculty_initials_raw == "DN"]
    assert dn and all(e.faculty_status == "ambiguous" and e.faculty_candidates == both for e in dn)
    # Both candidates are CE faculty, so the if_ce_faculty course stays in scope.
    assert not any(e.excluded for e in dn)
    assert sum(a.kind == "ambiguous_initials" for a in tt.anomalies) == len(dn)


# --------------------------------------------------------------------------- #
# Cross-check, aliases, output
# --------------------------------------------------------------------------- #


def test_hours_match_scheme(tt: ClassTimetable) -> None:
    assert [a for a in tt.anomalies if a.kind in ("hours_mismatch", "practical_block")] == []


def test_aliases_are_scheme_acronyms() -> None:
    names = {c.code: c.name for c in load_scheme().courses()}
    for alias, code in SUBJECT_ALIASES.items():
        if alias in HAND_REVIEWED_ALIASES:
            continue
        words = [w for w in re.split(r"\s+", names[code]) if w not in ("and", "in", "of")]
        assert alias == "".join(w[0].upper() for w in words), alias


def test_json_is_deterministic(tt: ClassTimetable, faculty: FacultyIndex) -> None:
    assert to_json(tt) == to_json(parse_class_timetable(faculty=faculty))


def test_committed_report_is_current() -> None:
    assert DEFAULT_REPORT.read_text(encoding="utf-8") == build()[1]
