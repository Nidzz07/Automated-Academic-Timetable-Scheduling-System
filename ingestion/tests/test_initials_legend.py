"""Tests for the initials legend extractor.

The real-file tests pin entries that were checked by eye against the .docx
files, the ODD BE legend's three-pairs-per-row layout, and the disagreements
the report must keep surfacing. Synthetic grids cover the reading rules.
"""

from __future__ import annotations

import pytest

from ingestion.initials_legend import (
    CLASS_FILES,
    DEFAULT_REPORT,
    Legend,
    LegendEntry,
    build_report,
    classify,
    duplicates_within_legend,
    extract_legends,
    group_by_initials,
    legend_pairs,
    name_key,
    read_legend,
)
from ingestion.seed_reference import FACULTY_INITIALS
from ingestion.survey import REAL_DIR

EVEN, ODD = CLASS_FILES


@pytest.fixture(scope="module")
def even() -> list[Legend]:
    return extract_legends(REAL_DIR / EVEN)


@pytest.fixture(scope="module")
def odd() -> list[Legend]:
    return extract_legends(REAL_DIR / ODD)


def _legend(legends: list[Legend], table_index: int) -> Legend:
    return next(lg for lg in legends if lg.table_index == table_index)


# --------------------------------------------------------------------------- #
# Real files
# --------------------------------------------------------------------------- #


def test_legend_counts(even: list[Legend], odd: list[Legend]) -> None:
    # EVEN is 11, not 10: TE Comp - D has two legend tables (t15 and t16).
    assert [lg.table_index for lg in even] == [1, 3, 5, 7, 9, 11, 13, 15, 16, 18, 20]
    assert [lg.table_index for lg in odd] == [1, 3, 4, 6, 8, 10, 12, 14, 16, 18]
    assert all(not lg.problems for lg in even + odd)


def test_hand_checked_entries(even: list[Legend], odd: list[Legend]) -> None:
    # EVEN t1, SE-Comp A: the name cell has a leading space in the source.
    se_a = _legend(even, 1)
    assert se_a.division == "SE-Comp A"
    assert LegendEntry("AsT", "Asma Tambe", 8, 0) in se_a.entries
    assert LegendEntry("AVN", "Dr, Anant Nimkar", 2, 0) in se_a.entries
    # EVEN t5, SE-Comp C: SD abbreviated, and initials cell "  TP" padded.
    se_c = _legend(even, 5)
    assert LegendEntry("SD", "Prof. Sonali D.", 7, 0) in se_c.entries
    assert LegendEntry("TP", "Prof. Taqdis Pawle", 8, 0) in se_c.entries
    # ODD t12, TE Comp- B: the one legend entry with no honorific.
    assert LegendEntry("VK", "Vipul Kushwah", 9, 0) in _legend(odd, 12).entries


def test_legend_after_a_note_belongs_to_the_preceding_grid(even: list[Legend]) -> None:
    # EVEN t1's nearest paragraph is "Note 1: Law-II ...", not a division.
    assert _legend(even, 1).division == "SE-Comp A"
    assert _legend(even, 16).division == "TE Comp - D"


def test_odd_be_legend_reads_three_pairs_per_row(odd: list[Legend]) -> None:
    be = _legend(odd, 18)
    assert be.division == "BE Comp- A & B"
    assert be.pairs == 3
    assert [(e.row, e.pair, e.initials, e.name) for e in be.entries] == [
        (1, 0, "SK", "Prof. Swapnali Kurhade"),
        (1, 1, "VR", "Prof. Vaishnavi Rathod"),
        (1, 2, "SK", "Prof. Suhas Kakade"),
        (2, 0, "SG", "Prof. Shaily Goyal"),
        (2, 1, "AN", "Prof. Aishwarya Nalawade"),
        (2, 2, "DDA", "Dr. Dayanand Ambawade"),
    ]
    assert duplicates_within_legend(be) == {"SK": ["Prof. Swapnali Kurhade", "Prof. Suhas Kakade"]}


def test_conflicting_initials_keep_every_name(even: list[Legend], odd: list[Legend]) -> None:
    grouped = group_by_initials(even + odd)
    sd: dict[str, set[str]] = {}
    for o in grouped["SD"]:
        sd.setdefault(o.name, set()).add(o.division)
    # SE legends say Sonali Dudhihalli; TE legends say Surekha Dholay.
    assert sd["Prof. Sonali Dudhihalli"] == {"SE-Comp B", "SE-Comp D"}
    assert sd["Prof. Sonali D."] == {"SE-Comp C"}
    assert all(d.startswith("TE") for d in sd["Dr. Surekha Dholay"])
    conflicts = {k for k, occ in grouped.items() if classify([o.name for o in occ]) == "CONFLICT"}
    assert conflicts == {"SD", "SK", "SM"}


def test_initials_are_case_sensitive(even: list[Legend]) -> None:
    grouped = group_by_initials(even)
    assert {o.name for o in grouped["AT"]} == {"Dr. Anuj Tawari"}
    assert {o.name for o in grouped["AsT"]} == {"Asma Tambe", "Prof. Asma Tambe"}


def test_seeded_initials_never_conflict_with_legends(even: list[Legend], odd: list[Legend]) -> None:
    grouped = group_by_initials(even + odd)
    for initials, seeded in FACULTY_INITIALS.items():
        names = [o.name for o in grouped[initials]]
        assert classify([seeded, *names]) != "CONFLICT", initials


def test_committed_report_is_current() -> None:
    assert DEFAULT_REPORT.read_text(encoding="utf-8") == build_report()


# --------------------------------------------------------------------------- #
# Synthetic grids
# --------------------------------------------------------------------------- #


def test_pair_width_comes_from_the_header_row() -> None:
    assert legend_pairs([["Initials", "Name of the Faculty"]]) == 1
    assert legend_pairs([[" Initials", "Name of Faculty"] * 2]) == 2
    assert legend_pairs([["Time", "Monday", "Tuesday"]]) is None
    assert legend_pairs([["Initials", "Name of the Faculty", "Initials"]]) is None
    assert legend_pairs([["Initials", "Name", "Initials", "Name of Faculty"]]) is None
    assert legend_pairs([]) is None


def test_read_legend_skips_blank_pairs_and_reports_half_filled() -> None:
    grid = [
        ["Initials", "Name of Faculty", "Initials", "Name of Faculty"],
        ["  AB ", " Dr.  A\nB ", "", ""],
        ["CD", "", "", "Orphan Name"],
    ]
    entries, problems = read_legend(grid)
    assert entries == [LegendEntry("AB", "Dr. A B", 1, 0)]
    assert len(problems) == 2


def test_read_legend_rejects_a_non_legend() -> None:
    with pytest.raises(ValueError):
        read_legend([["Time", "Monday"]])


@pytest.mark.parametrize(
    ("names", "status"),
    [
        (["Dr. Nataasha Raul", "Nataasha Raul"], "AGREE"),
        (["Dr, Anant Nimkar", "Dr. Anant Nimkar"], "AGREE"),
        (["Prof. Jostna Bhagat", "Prof. Jotsna Bhagat"], "VARIANT"),
        (["Prof. Swapnali Kurhade", "Prof. Suhas Kakade"], "CONFLICT"),
    ],
)
def test_classify(names: list[str], status: str) -> None:
    assert classify(names) == status


def test_name_key_strips_only_real_honorifics() -> None:
    assert name_key("Mrs. Isha Sawalkar") == "isha sawalkar"
    assert name_key("Prof.Shaily Goyal") == "shaily goyal"
    assert name_key("Drishti Rao") == "drishti rao"
