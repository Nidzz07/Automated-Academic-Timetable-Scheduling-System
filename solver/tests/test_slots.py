"""Tests for :mod:`solver.slots`.

The point of interest is the drift guard: :data:`solver.slots.TEACHING_PERIODS`
is checked against the value frozen in ``contracts/edge_list_v1.schema.json`` by
reading the schema, never by restating the list here. A duplicated literal would
agree with itself forever and catch nothing.

Since S8 the canonical constants are a test helper and the solver reads each
payload's grid through :class:`~solver.slots.SlotGrid`; the last section checks
both halves of that.
"""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from solver.slots import (
    BREAK_LABELS,
    DAYS,
    LUNCH_PERIOD,
    PERIOD_TIMES,
    PERIODS_PER_DAY,
    SHORT_BREAK_PERIOD,
    SLOT_COUNT,
    TEACHING_PERIODS,
    SlotGrid,
    SlotId,
    all_slots,
    from_index,
    is_adjacent,
    slot_index,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_LIST_SCHEMA = REPO_ROOT / "contracts" / "edge_list_v1.schema.json"
D6_EXAMPLE = REPO_ROOT / "contracts" / "examples" / "edge_list_v1.d6_grid.example.json"


def schema_slot_grid() -> dict:
    """The frozen ``slot_grid`` sub-schema, read from the contract on disk."""
    with EDGE_LIST_SCHEMA.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    return schema["properties"]["slot_grid"]["properties"]


# --------------------------------------------------------------------------
# drift guards against the frozen contract
# --------------------------------------------------------------------------


def test_teaching_periods_matches_the_edge_list_contract() -> None:
    """TEACHING_PERIODS is read from the schema on disk, never restated here.

    The schema records the canonical grid as an annotation-only ``default`` on
    ``slot_grid.teaching_periods``. If someone edits that value, or edits the
    constant in :mod:`solver.slots`, this test fails rather than letting the
    solver and the contract disagree in silence.
    """
    contract_value = schema_slot_grid()["teaching_periods"]["default"]
    solver_value = TEACHING_PERIODS

    assert solver_value == contract_value, (
        "solver.slots.TEACHING_PERIODS has drifted from "
        "contracts/edge_list_v1.schema.json's slot_grid.teaching_periods default"
    )


def test_periods_per_day_matches_the_edge_list_contract() -> None:
    grid = schema_slot_grid()
    assert grid["periods_per_day"]["default"] == PERIODS_PER_DAY
    assert grid["days"]["default"] == DAYS


def test_teaching_periods_lie_on_the_declared_wall_clock_axis() -> None:
    periods = TEACHING_PERIODS
    assert all(0 <= period < PERIODS_PER_DAY for period in periods)
    assert periods == sorted(periods)
    assert len(set(periods)) == len(periods)


def test_adjacency_matches_the_edge_list_contract() -> None:
    """Every adjacent pair the schema declares must satisfy is_adjacent."""
    adjacency = schema_slot_grid()["adjacency"]["default"]

    assert adjacency, "the contract declares no adjacency pairs"
    for first, second in adjacency:
        assert is_adjacent(SlotId(0, first), SlotId(0, second)), (
            f"contract declares periods {first} and {second} adjacent, "
            f"solver.slots disagrees"
        )


def test_adjacency_is_exactly_what_the_contract_declares() -> None:
    """Not just a superset: is_adjacent must invent no pairs of its own."""
    declared = {
        frozenset(pair) for pair in schema_slot_grid()["adjacency"]["default"]
    }
    computed = {
        frozenset((a.period, b.period))
        for a in all_slots()
        for b in all_slots()
        if a.day == 0 and b.day == 0 and is_adjacent(a, b)
    }
    assert computed == declared


def test_contract_example_uses_the_same_grid() -> None:
    """The committed example payload must not contradict the schema's default."""
    example_path = REPO_ROOT / "contracts" / "examples" / "edge_list_v1.example.json"
    with example_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)["slot_grid"]

    grid = schema_slot_grid()
    assert payload["teaching_periods"] == grid["teaching_periods"]["default"]
    assert payload["periods_per_day"] == grid["periods_per_day"]["default"]
    assert payload["days"] == grid["days"]["default"]
    assert payload["adjacency"] == grid["adjacency"]["default"]


def test_schema_documents_the_same_grid_shape() -> None:
    """Sanity check that the fields this module mirrors still exist in the schema."""
    grid = schema_slot_grid()
    assert set(grid) == {"days", "periods_per_day", "teaching_periods", "adjacency"}


# --------------------------------------------------------------------------
# period table
# --------------------------------------------------------------------------


def test_period_times_covers_the_whole_wall_clock_axis() -> None:
    assert sorted(PERIOD_TIMES) == list(range(PERIODS_PER_DAY))


def test_breaks_are_labelled_and_not_teaching_periods() -> None:
    assert SHORT_BREAK_PERIOD not in TEACHING_PERIODS
    assert LUNCH_PERIOD not in TEACHING_PERIODS
    assert BREAK_LABELS[SHORT_BREAK_PERIOD] == "SHORT_BREAK"
    assert BREAK_LABELS[LUNCH_PERIOD] == "LUNCH"


def test_short_break_is_fifteen_minutes_not_an_invented_hour() -> None:
    """The breaks carry their real durations from the timetable documents."""
    assert PERIOD_TIMES[SHORT_BREAK_PERIOD] == ("11.00", "11.15")
    assert PERIOD_TIMES[LUNCH_PERIOD] == ("13.15", "14.15")


def test_periods_are_contiguous_on_the_clock() -> None:
    """Each period starts exactly when the previous one ends."""
    for period in range(PERIODS_PER_DAY - 1):
        assert PERIOD_TIMES[period][1] == PERIOD_TIMES[period + 1][0]


# --------------------------------------------------------------------------
# SlotId
# --------------------------------------------------------------------------


def test_slot_id_is_frozen_and_hashable() -> None:
    slot = SlotId(1, 3)
    assert {slot, SlotId(1, 3)} == {slot}
    with pytest.raises(FrozenInstanceError):
        slot.day = 2  # type: ignore[misc]


@pytest.mark.parametrize("day", [-1, 5, 99])
def test_slot_id_rejects_a_day_outside_the_week(day: int) -> None:
    with pytest.raises(ValueError):
        SlotId(day, 0)


def test_slot_id_rejects_a_negative_period() -> None:
    with pytest.raises(ValueError):
        SlotId(0, -1)


@pytest.mark.parametrize("period", [10, 42])
def test_the_grid_bounds_the_period(period: int) -> None:
    """SlotId takes any wall-clock index; the payload's grid refuses one off its axis."""
    assert SlotId(0, period).period == period
    with pytest.raises(ValueError, match="off the slot grid"):
        _canonical_grid().slot(0, period)


def test_slot_names_its_clock_time_without_a_break_label() -> None:
    """Under D6 P5 is lunch for SE but a teaching hour for TE, so no label is printed."""
    assert str(SlotId(0, LUNCH_PERIOD)) == "Monday 13.15-14.15"
    assert str(SlotId(4, 1)) == "Friday 10.00-11.00"
    assert str(SlotId(2, 11)) == "Wednesday period 11"


def test_break_periods_are_constructible() -> None:
    """The grid contains the breaks; they are just never teaching slots."""
    assert SlotId(0, SHORT_BREAK_PERIOD).period == SHORT_BREAK_PERIOD
    assert SlotId(0, LUNCH_PERIOD).period == LUNCH_PERIOD


# --------------------------------------------------------------------------
# is_adjacent
# --------------------------------------------------------------------------


def test_adjacent_across_the_short_break() -> None:
    """Periods 1 and 3 are TEACHING_PERIODS positions 1 and 2 - a 10.00-12.00 lab."""
    assert is_adjacent(SlotId(0, 1), SlotId(0, 3))
    assert is_adjacent(SlotId(0, 3), SlotId(0, 1))


def test_adjacent_across_lunch() -> None:
    """Periods 4 and 6 are positions 3 and 4."""
    assert is_adjacent(SlotId(2, 4), SlotId(2, 6))
    assert is_adjacent(SlotId(2, 6), SlotId(2, 4))


def test_adjacent_for_plain_consecutive_periods() -> None:
    assert is_adjacent(SlotId(0, 0), SlotId(0, 1))
    assert is_adjacent(SlotId(4, 7), SlotId(4, 8))
    assert is_adjacent(SlotId(4, 8), SlotId(4, 9))


def test_not_adjacent_across_a_day_boundary() -> None:
    """Friday 17.15 does not run into Monday 09.00, and neither does anything else."""
    assert not is_adjacent(SlotId(0, 1), SlotId(1, 3))
    assert not is_adjacent(SlotId(0, 0), SlotId(1, 1))
    assert not is_adjacent(SlotId(3, 9), SlotId(4, 0))


def test_not_adjacent_when_a_teaching_period_sits_between_them() -> None:
    """Periods 0 and 3 are positions 0 and 2 - period 1 is in the way."""
    assert not is_adjacent(SlotId(0, 0), SlotId(0, 3))
    assert not is_adjacent(SlotId(0, 1), SlotId(0, 4))


def test_not_adjacent_to_itself() -> None:
    assert not is_adjacent(SlotId(0, 3), SlotId(0, 3))


@pytest.mark.parametrize("break_period", [SHORT_BREAK_PERIOD, LUNCH_PERIOD])
@pytest.mark.parametrize("neighbour", [1, 3, 4, 6])
def test_not_adjacent_when_either_side_is_a_break(break_period: int, neighbour: int) -> None:
    """A break is spanned, never occupied - it is adjacent to nothing."""
    assert not is_adjacent(SlotId(0, break_period), SlotId(0, neighbour))
    assert not is_adjacent(SlotId(0, neighbour), SlotId(0, break_period))


def test_not_adjacent_between_the_two_breaks() -> None:
    assert not is_adjacent(SlotId(0, SHORT_BREAK_PERIOD), SlotId(0, LUNCH_PERIOD))


def test_adjacency_is_symmetric_over_the_whole_grid() -> None:
    for first in all_slots():
        for second in all_slots():
            assert is_adjacent(first, second) == is_adjacent(second, first)


def test_every_slot_has_at_most_two_neighbours() -> None:
    """A linear teaching order means interior slots have 2 neighbours, ends have 1."""
    for slot in all_slots():
        neighbours = [other for other in all_slots() if is_adjacent(slot, other)]
        expected = 1 if slot.period in (TEACHING_PERIODS[0], TEACHING_PERIODS[-1]) else 2
        assert len(neighbours) == expected, f"{slot} has {len(neighbours)} neighbours"


# --------------------------------------------------------------------------
# all_slots
# --------------------------------------------------------------------------


def test_all_slots_has_forty_entries() -> None:
    slots = all_slots()
    assert len(slots) == 40
    assert len(slots) == SLOT_COUNT == DAYS * len(TEACHING_PERIODS)


def test_all_slots_are_teaching_slots_and_unique() -> None:
    slots = all_slots()
    assert all(slot.period in TEACHING_PERIODS for slot in slots)
    assert len(set(slots)) == len(slots)


def test_all_slots_is_day_major_period_minor() -> None:
    slots = all_slots()
    assert [slot.day for slot in slots[:8]] == [0] * 8
    assert [slot.period for slot in slots[:8]] == TEACHING_PERIODS
    assert [slot.period for slot in slots[8:16]] == TEACHING_PERIODS
    assert slots[0] == SlotId(0, 0)
    assert slots[-1] == SlotId(4, 9)


# --------------------------------------------------------------------------
# dense index
# --------------------------------------------------------------------------


def test_slot_index_round_trips_for_every_valid_slot() -> None:
    for slot in all_slots():
        assert from_index(slot_index(slot)) == slot


def test_index_round_trips_for_every_dense_index() -> None:
    for i in range(SLOT_COUNT):
        assert slot_index(from_index(i)) == i


def test_slot_index_is_dense_and_aligned_with_all_slots() -> None:
    assert [slot_index(slot) for slot in all_slots()] == list(range(SLOT_COUNT))


@pytest.mark.parametrize("break_period", [SHORT_BREAK_PERIOD, LUNCH_PERIOD])
def test_slot_index_raises_on_a_break_period(break_period: int) -> None:
    with pytest.raises(ValueError, match="no dense slot index"):
        slot_index(SlotId(0, break_period))


@pytest.mark.parametrize("bad_index", [-1, SLOT_COUNT, 999])
def test_from_index_rejects_an_out_of_range_index(bad_index: int) -> None:
    with pytest.raises(ValueError):
        from_index(bad_index)


def test_dense_index_is_not_the_ingestion_period_axis() -> None:
    """Guard against the axis confusion the module docstring warns about.

    Ingestion's ``period`` is a teaching-order index 0..7 *within a day*. The dense
    index runs 0..39 *across the week*. They coincide only on Monday, and that
    coincidence is what makes the mistake easy to miss.
    """
    assert slot_index(SlotId(0, 3)) == 2  # Monday, third teaching hour
    assert slot_index(SlotId(1, 3)) == 10  # Tuesday, same hour, different index
    assert slot_index(SlotId(4, 9)) == 39


# --------------------------------------------------------------------------
# SlotGrid - the payload's grid, which the solver reads (S8)
# --------------------------------------------------------------------------


def _raw_grid(**overrides: Any) -> dict[str, Any]:
    """The schema's default ``slot_grid`` payload, with *overrides*."""
    grid = schema_slot_grid()
    return {**{key: grid[key]["default"] for key in grid}, **overrides}


def _canonical_grid() -> SlotGrid:
    return SlotGrid.from_payload(_raw_grid())


def test_canonical_payload_grid_agrees_with_the_test_helpers() -> None:
    grid = _canonical_grid()
    assert (grid.days, grid.periods_per_day) == (DAYS, PERIODS_PER_DAY)
    assert grid.all_slots() == all_slots()
    for a in all_slots():
        for b in all_slots():
            assert grid.is_adjacent(a, b) == is_adjacent(a, b)


def test_d6_grid_teaches_p5_and_joins_it_both_ways() -> None:
    """ROADMAP D6: only P2 closes for everyone; each year's lunch is a pin, not a gap."""
    payload = json.loads(D6_EXAMPLE.read_text(encoding="utf-8"))
    grid = SlotGrid.from_payload(payload["slot_grid"])
    assert grid.is_teaching_period(5) and not grid.is_teaching_period(SHORT_BREAK_PERIOD)
    assert grid.is_adjacent(SlotId(0, 4), SlotId(0, 5))
    assert grid.is_adjacent(SlotId(0, 5), SlotId(0, 6))
    assert grid.is_adjacent(SlotId(0, 1), SlotId(0, 3))  # across the coffee break
    assert not grid.is_adjacent(SlotId(0, 4), SlotId(0, 6))  # P5 teaches between them
    assert len(grid.all_slots()) == 5 * 9


@pytest.mark.parametrize(
    "overrides",
    [
        {"days": 3},
        {"periods_per_day": 12, "teaching_periods": [0, 1, 3, 10, 11],
         "adjacency": [[0, 1], [10, 11]]},
        {"adjacency": []},
        {"teaching_periods": [9, 0, 1], "adjacency": [[0, 1], [1, 9]]},
    ],
    ids=["three-days", "twelve-periods", "no-adjacency", "unsorted-teaching-periods"],
)
def test_any_well_formed_grid_is_accepted(overrides: dict[str, Any]) -> None:
    grid = SlotGrid.from_payload(_raw_grid(**overrides))
    assert list(grid.teaching_periods) == sorted(grid.teaching_periods)
    assert len(grid.all_slots()) == grid.days * len(grid.teaching_periods)
    assert {(a.period, b.period) for a in grid.all_slots() for b in grid.all_slots()
            if a.day == b.day == 0 and a.period < b.period and grid.is_adjacent(a, b)
            } == {tuple(pair) for pair in _raw_grid(**overrides)["adjacency"]}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"days": 0}, "days"),
        ({"days": 6}, "days"),
        ({"periods_per_day": 0}, "periods_per_day"),
        ({"teaching_periods": [0, 0, 1], "adjacency": [[0, 1]]}, "teaching_periods"),
        ({"teaching_periods": [0, 1, 10], "adjacency": [[0, 1]]}, "teaching_periods"),
        ({"adjacency": [[0, 3]]}, "adjacency"),
        ({"adjacency": [[3, 1]]}, "adjacency"),
        ({"adjacency": [[1, 2]]}, "adjacency"),
    ],
    ids=["no-days", "saturday", "no-periods", "duplicate-period", "period-off-the-axis",
         "pair-skips-a-teaching-period", "pair-backwards", "pair-into-a-break"],
)
def test_a_malformed_grid_is_refused(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        SlotGrid.from_payload(_raw_grid(**overrides))


def test_no_solver_module_reads_the_canonical_grid() -> None:
    """The canonical grid is a test helper: solver modules take only SlotId and SlotGrid."""
    for name in ("graph", "backtracking", "colouring", "presolve", "validate"):
        tree = ast.parse((REPO_ROOT / "solver" / f"{name}.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "solver.slots":
                imported.update(alias.name for alias in node.names)
            assert not (isinstance(node, ast.Import)
                        and any(alias.name == "solver.slots" for alias in node.names)), name
        assert imported <= {"SlotGrid", "SlotId"}, (name, imported)
