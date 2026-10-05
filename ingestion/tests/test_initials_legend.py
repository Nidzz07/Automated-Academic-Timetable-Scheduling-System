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
    normalise_whitespace,
    read_legend,
    strip_title,
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
    assert LegendEntry("AsT", "Asma Tambe", 8, 0, " Asma Tambe") in se_a.entries
    assert LegendEntry("AVN", "Dr, Anant Nimkar", 2, 0, "Dr, Anant Nimkar") in se_a.entries
    # EVEN t5, SE-Comp C: SD abbreviated, and initials cell "  TP" padded.
    se_c = _legend(even, 5)
    assert LegendEntry("SD", "Prof. Sonali D.", 7, 0, "Prof. Sonali D.") in se_c.entries
    assert LegendEntry("TP", "Prof. Taqdis Pawle", 8, 0, "Prof. Taqdis Pawle") in se_c.entries
    # ODD t12, TE Comp- B: the one legend entry with no honorific.
    assert LegendEntry("VK", "Vipul Kushwah", 9, 0, "Vipul Kushwah") in _legend(odd, 12).entries


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
    assert entries == [LegendEntry("AB", "Dr. A B", 1, 0, " Dr.  A\nB ")]
    assert len(problems) == 2


# --------------------------------------------------------------------------- #
# Whitespace normalisation and title stripping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        # A soft line break inside a Word cell.
        ("Dr, Anant Nim\nkar", "Dr, Anant Nim kar"),
        ("Kail\nas Devadkar", "Kail as Devadkar"),
        ("Kail\r\n  as\tDevadkar", "Kail as Devadkar"),
        ("  Prof.   Asma\u00a0Tambe ", "Prof. Asma Tambe"),
        ("Dr. Deepak Nair", "Dr. Deepak Nair"),
    ],
)
def test_normalise_whitespace_collapses_internal_breaks(raw: str, normalised: str) -> None:
    assert normalise_whitespace(raw) == normalised


def test_read_legend_keeps_the_raw_name_alongside_the_normalised_one() -> None:
    grid = [
        ["Initials", "Name of the Faculty"],
        ["AVN", "Dr, Anant Nim\nkar"],
        ["KKD", "Kail\nas Devadkar"],
    ]
    entries, problems = read_legend(grid)
    assert not problems
    assert [(e.name, e.raw_name) for e in entries] == [
        ("Dr, Anant Nim kar", "Dr, Anant Nim\nkar"),
        ("Kail as Devadkar", "Kail\nas Devadkar"),
    ]
    assert all("\n" not in e.name for e in entries)


def test_real_legend_names_are_single_line(even: list[Legend], odd: list[Legend]) -> None:
    """Every stored name is normalised; the raw cell text survives beside it."""
    entries = [e for lg in even + odd for e in lg.entries]
    assert all(e.name == normalise_whitespace(e.raw_name) for e in entries)
    assert all("\n" not in e.name for e in entries)
    # EVEN t1 pads this cell with a leading space; raw keeps it, name drops it.
    asma = next(e for e in _legend(even, 1).entries if e.initials == "AsT")
    assert (asma.raw_name, asma.name) == (" Asma Tambe", "Asma Tambe")


@pytest.mark.parametrize(
    ("name", "stripped"),
    [
        ("Mr. Anas Ansari", "Anas Ansari"),
        ("Ms. Aishwarya Nalawade", "Aishwarya Nalawade"),
        ("Mrs. Isha Sawalkar", "Isha Sawalkar"),
        ("Prof. Asma Tambe", "Asma Tambe"),
        ("Prof.Shaily Goyal", "Shaily Goyal"),
        ("Dr. Anuj Tawari", "Anuj Tawari"),
        ("Dr, Anant Nimkar", "Anant Nimkar"),
        ("Prof. Dr. X Y", "X Y"),
        # Initials inside the name are not titles.
        ("Dr. D. R. Kalbande", "D. R. Kalbande"),
        ("Prof. Suman M.", "Suman M."),
        # Only a real title is stripped.
        ("Drishti Rao", "Drishti Rao"),
        ("Mrinal Sen", "Mrinal Sen"),
        ("Asma Tambe", "Asma Tambe"),
    ],
)
def test_strip_title(name: str, stripped: str) -> None:
    assert strip_title(name) == stripped


def test_strip_title_does_not_change_what_is_stored(even: list[Legend]) -> None:
    """Titles are dropped for matching only; LegendEntry.name keeps them."""
    names = {e.name for lg in even for e in lg.entries}
    assert "Prof. Asma Tambe" in names
    assert "Dr, Anant Nimkar" in names


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
