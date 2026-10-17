"""Tests for the EVEN lab-timetable parser and the class-vs-lab cross-check, on the real files.

Pinned cells and printed figures were checked by eye against the document.
"""

from __future__ import annotations

import re

import pytest

from ingestion.class_tt import ClassTimetable, FacultyIndex, faculty_index, parse_class_timetable
from ingestion.docx_reader import logical_cells, open_document, walk_body
from ingestion.lab_tt import (
    LAB_FILE,
    Inventory,
    LabTimetable,
    cross_check,
    d25_member,
    division_key,
    label_key,
    normalise_room,
    parse_lab_timetable,
    room_inventory,
)


@pytest.fixture(scope="module")
def faculty() -> FacultyIndex:
    return faculty_index()


@pytest.fixture(scope="module")
def inventory() -> Inventory:
    return room_inventory()


@pytest.fixture(scope="module")
def class_tt(faculty: FacultyIndex) -> ClassTimetable:
    return parse_class_timetable(faculty=faculty)


@pytest.fixture(scope="module")
def lab(class_tt: ClassTimetable, faculty: FacultyIndex, inventory: Inventory) -> LabTimetable:
    return parse_lab_timetable(class_tt=class_tt, faculty=faculty, inventory=inventory)


def _cell(lab: LabTimetable, label: str, day: str, start: int):
    found = [e for e in lab.entries
             if e.room_label == label and e.day == day and e.periods[0] == start]
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #


def test_inventory_is_d8_labs_plus_d10_classrooms(inventory: Inventory) -> None:
    labs = {r.code: r.parallel for r in inventory.labs()}
    assert labs == {"509": 2, "603": 3, "604": 1, "606": 2, "607B": 1, "608": 1, "702": 3,
                    "703": 2, "507": 1}
    assert sum(labs.values()) == 16  # D8
    assert {r.code: r.room_type for r in inventory.classrooms()} == {
        "601": "class", "605": "unknown", "609": "unknown", "701": "class",
    }
    assert "607A" not in inventory.rooms  # D8: M.Tech only


def test_lab_sub_rooms(inventory: Inventory) -> None:
    subs = {r.code: [c for c, _ in r.sub_rooms] for r in inventory.labs() if r.sub_rooms}
    assert subs == {
        "509": ["509-1", "509-2"], "603": ["603-1", "603-2", "603-3"], "606": ["606-1", "606-2"],
        "702": ["702-A", "702-B", "702-C"], "703": ["703-A", "703-B"],
    }
    assert inventory.rooms["509"].capacity == 40  # D27
    categories = {f.category: f.resolution for f in inventory.findings}
    assert categories["lab_capacity_conflict"] == "D27"
    assert categories["duplicate_room"] == "D8"


@pytest.mark.parametrize(
    ("raw", "room", "sub_room", "resolution"),
    [
        ("607-B", "607B", None, "D30"),
        ("703-A", "703", "703-A", None),
        ("603-2", "603", "603-2", None),
        ("603-7", "603", None, "D30"),
        ("606-4", "606", None, "D30"),
        ("509 new CSE", "509", None, "D27"),
        ("505", None, None, "D28"),
        ("403 B", None, None, "D29"),
        ("508", None, None, "D10"),
        ("601", "601", None, None),
    ],
)
def test_normalise_room(inventory: Inventory, raw: str, room, sub_room, resolution) -> None:
    ref = normalise_room(raw, inventory)
    assert (ref.room, ref.sub_room) == (room, sub_room)
    assert (ref.note[2] if ref.note else None) == resolution


def test_label_key() -> None:
    assert label_key("607-B") == label_key("607B")
    assert label_key("509 new CSE") == "509"
    assert label_key("606-4") != label_key("606-5")


def test_division_key() -> None:
    assert division_key("TE Comp - C") == "TE-C"
    assert division_key("SECOMP C") == "SE-C"
    assert division_key("SE COMP NR") is None


# --------------------------------------------------------------------------- #
# Tables and cells
# --------------------------------------------------------------------------- #


def test_one_table_per_room(lab: LabTimetable) -> None:
    assert [t.room_label for t in lab.tables] == [
        "607-B", "604", "606-4", "606-5", "608", "603-2", "603-3", "603-7",
        "702-A", "702-B", "702-C", "703-A", "703-B", "509", "505",
    ]


def test_utilisation_reproduced(lab: LabTimetable) -> None:
    matched = {t.room_label for t in lab.tables if t.matches_printed}
    assert matched == {"607-B", "604", "606-4", "606-5", "608", "702-B", "702-C", "703-A",
                       "703-B", "509", "505"}
    t = lab.tables[0]
    assert t.printed == (24, 30, 80.0)
    assert t.occupied == 24
    mismatch = {f.location for f in lab.findings if f.category == "utilisation_mismatch"}
    assert mismatch == {"t5 603-2", "t6 603-3", "t7 603-7", "t8 702-A"}


def test_every_non_empty_cell_is_an_entry(lab: LabTimetable) -> None:
    tables = [el for kind, el in walk_body(open_document(LAB_FILE)) if kind == "table"]
    expected = 0
    for table in tables:
        cells, _, _ = logical_cells(table)
        for c in cells:
            if c.row and c.col and c.text.strip() and \
                    not re.fullmatch(r"(SHORT-?)?BREAK", "".join(c.text.split()).upper()):
                expected += 1
    assert len(lab.entries) == expected


def test_practical_cell(lab: LabTimetable) -> None:
    e = _cell(lab, "607-B", "Wednesday", 0)
    assert (e.kind, e.subject_raw, e.scheme_code, e.batch, e.faculty_initials_raw, e.audience) \
        == ("practical", "OS", "CE206", "B", "AGN", "SE-D")
    assert e.periods == [0, 1]
    assert (e.faculty_status, e.faculty_candidates) == ("resolved", ["Amey Ganesh Nile"])
    assert (e.room, e.sub_room) == ("607B", None)


def test_elective_takes_class_resolution_and_d25(lab: LabTimetable, faculty: FacultyIndex) -> None:
    e = _cell(lab, "607-B", "Tuesday", 0)
    assert (e.kind, e.elective_group, e.faculty_initials_raw) == ("elective", "PE-I-D", "SRD")
    assert e.matched
    assert (e.faculty_status, e.faculty_candidates) == ("resolved_d25", [d25_member(faculty)])
    assert d25_member(faculty) == "Surekha Dholay"


def test_bracketed_room_is_recorded_not_used(lab: LabTimetable) -> None:
    e = _cell(lab, "607-B", "Friday", 0)
    assert e.room_override_raw == "608"
    assert e.room == "607B"
    assert any(f.category == "room_override" and f.location == e.where for f in lab.findings)


def test_other_kinds(lab: LabTimetable) -> None:
    assert _cell(lab, "603-2", "Wednesday", 3).kind == "exam"
    assert _cell(lab, "604", "Tuesday", 5).kind == "out_of_scope"
    mdm = _cell(lab, "603-7", "Monday", 7)
    assert (mdm.kind, mdm.faculty_initials_raw, mdm.room) == ("mdm", "RS", "603")
    assert not [e for e in lab.entries if e.kind == "unparsed"]


def test_beyond_split_and_d28_d29_reported(lab: LabTimetable) -> None:
    by_category = {}
    for f in lab.findings:
        by_category.setdefault(f.category, set()).add(f.resolution)
    assert by_category["subroom_beyond_split"] == {"D30"}
    assert by_category["room_not_generation"] == {"D28", "D29"}
    assert by_category["lab_in_classroom"] == {"D29"}


# --------------------------------------------------------------------------- #
# Cross-check (task 3)
# --------------------------------------------------------------------------- #


def test_cross_check(class_tt: ClassTimetable, lab: LabTimetable) -> None:
    findings = cross_check(class_tt, lab)
    by_category: dict[str, list[str]] = {}
    for f in findings:
        by_category.setdefault(f.category, []).append(f.message)
        assert f.resolution == "needs human"
    assert len(by_category["practical_missing_in_lab_tt"]) == 5
    assert "practical_missing_in_class_tt" not in by_category
    [mismatch] = by_category["practical_mismatch"]
    assert mismatch.startswith("TE-C batch B CE307: day: class 'Thursday' vs lab 'Friday'")
    practicals = [e for e in lab.entries if e.kind == "practical"]
    assert sum(e.matched for e in practicals) == len(practicals)
