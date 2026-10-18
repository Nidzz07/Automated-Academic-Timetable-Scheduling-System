"""Tests for the EVEN faculty-timetable parser and the load check, on the real files."""

from __future__ import annotations

import pytest

from ingestion.class_tt import faculty_index, parse_class_timetable
from ingestion.faculty import FacultyTimetable, parse_faculty_timetable, parse_load_line
from ingestion.lab_tt import cross_check, parse_lab_timetable, room_inventory


@pytest.fixture(scope="module")
def ft() -> FacultyTimetable:
    faculty = faculty_index()
    class_tt = parse_class_timetable(faculty=faculty)
    lab = parse_lab_timetable(class_tt=class_tt, faculty=faculty, inventory=room_inventory())
    cross_check(class_tt, lab)
    return parse_faculty_timetable(class_tt, lab, faculty)


def _page(ft: FacultyTimetable, name: str):
    [page] = [p for p in ft.pages if p.name_raw == name]
    return page


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("6T+ 8P =14", (6, 8, 14)),
        ("6T +8P =14", (6, 8, 14)),
        ("4T + 14P=18", (4, 14, 18)),
        ("18P = 18", (None, 18, 18)),
        ("2T", (2, None, None)),
        ("Computer Engineering Department", None),
        ("", None),
    ],
)
def test_parse_load_line(text: str, parsed) -> None:
    assert parse_load_line(text) == parsed


def test_pages(ft: FacultyTimetable) -> None:
    assert len(ft.pages) == 32
    assert all(p.member for p in ft.pages)  # every page name is in the 41-member list
    p = _page(ft, "Prasenjit Bhavathankar")
    assert (p.load_raw, p.theory, p.practical, p.total) == ("6T+ 8P =14", 6, 8, 14)
    assert len(p.sessions) == 7
    # One paragraph holds "18P=18" and the next page's first line.
    assert _page(ft, "Azman Qureshi").load_raw == "18P=18"
    no_line = {p.name_raw for p in ft.pages if p.load_raw is None}
    assert no_line == {"D. R. Kalbande", "Dayanand Ambawade"}


def test_day_off_reported(ft: FacultyTimetable) -> None:
    assert _page(ft, "Swapnali Kurhade").days_off == ["Monday"]
    assert [f.resolution for f in ft.findings if f.category == "faculty_day_off"] == ["D36"]


def test_loads_follow_d11_and_d23(ft: FacultyTimetable) -> None:
    # Three SE A & B lectures print as 6T; five practicals as 10P (D11).
    kkd = ft.loads["Kailas Devadkar"]
    assert (kkd.lecture, kkd.practical, kkd.theory, kkd.practical_total) == (6, 10, 6, 10)
    # DevOps tutorial: 1 h per division (D23), four divisions.
    assert ft.loads["Reeta Koshy"].tutorial == 4
    # SRD attributed through D25: matches the printed 4T+8P.
    srd = ft.loads["Surekha Dholay"]
    assert (srd.theory, srd.practical_total) == (4, 8)
    assert not any(f.location.endswith("Surekha Dholay") and f.category == "load_mismatch"
                   for f in ft.findings)


def test_findings(ft: FacultyTimetable) -> None:
    categories = {f.category for f in ft.findings}
    assert {"load_mismatch", "load_above_16", "missing_workload", "no_faculty_page"} <= categories
    above = {f.location for f in ft.findings if f.category == "load_above_16"}
    assert "t10 Jyoti Ramteke" in above  # printed 3T+14P=17
    assert all(f.resolution == "D11" for f in ft.findings if f.category == "load_above_16")
    unmatched_pages = [f for f in ft.findings if f.category == "page_name_unmatched"]
    assert not unmatched_pages
