"""Slot representation for the solver.

This module is the solver's only vocabulary for "when". Everything downstream -
the conflict graph, colouring, backtracking, MUS extraction, repair - speaks in
:class:`SlotId` and in the dense index produced by :func:`slot_index`.

Three period axes exist in this project. Confusing them silently produces a
timetable that is off by a break, so they are spelled out here:

1. **Wall-clock period index, 0..9** - the axis this module uses, and the one
   frozen by ``contracts/edge_list_v1.schema.json`` as ``slot_grid.periods_per_day
   = 10``. It counts every hour of the day *including* the two breaks. Index 2 is
   the 11.00-11.15 short break and index 5 is the 13.15-14.15 lunch break; neither
   can hold a session. This is the single source of truth for the solver.

2. **Teaching-order index, 0..7** - used *only* by
   ``contracts/ingestion_v1.schema.json`` for its ``period`` field, where it
   numbers the eight schedulable hours consecutively with the breaks skipped. It
   is the data layer's job to translate that axis onto axis 1 when it builds the
   edge list. **It must never appear inside ``solver/``.** If you find yourself
   writing ``period in range(8)`` here, you have the wrong axis.

3. **Dense slot index, 0..39** - :func:`slot_index` / :func:`from_index`, a flat
   numbering of the 40 real teaching slots (5 days x 8 teaching periods) for
   compact bitset and array use. Solver-internal only: it never crosses a contract
   boundary, and it is *not* interchangeable with axis 2 even though both start at
   0 and both exclude breaks.

Adjacency is the reason axis 1 cannot simply be "hours since 09.00". A double lab
such as ``ET Lab /DDA /509 (10.00 -12.00)`` runs from period 1 to period 3, across
the short break. Those two periods are adjacent *in teaching order* while their
raw indices differ by 2, so :func:`is_adjacent` compares positions within
:data:`TEACHING_PERIODS` rather than the numbers themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DAYS",
    "DAY_NAMES",
    "PERIODS_PER_DAY",
    "TEACHING_PERIODS",
    "SHORT_BREAK_PERIOD",
    "LUNCH_PERIOD",
    "BREAK_LABELS",
    "PERIOD_TIMES",
    "SLOT_COUNT",
    "SlotId",
    "is_adjacent",
    "all_slots",
    "slot_index",
    "from_index",
    "is_teaching_period",
    "period_label",
]

#: Teaching days per week, Monday=0 .. Friday=4.
DAYS = 5

DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

#: Length of the wall-clock period axis, breaks included. Mirrors
#: ``slot_grid.periods_per_day`` in the edge-list contract.
PERIODS_PER_DAY = 10

#: Wall-clock period indices that can hold a session.
#:
#: This must stay literally equal to ``slot_grid.teaching_periods`` in
#: ``contracts/edge_list_v1.schema.json``; ``tests/test_slots.py`` reads the
#: schema and fails if the two ever drift apart.
TEACHING_PERIODS: list[int] = [0, 1, 3, 4, 6, 7, 8, 9]

#: The 11.00-11.15 break. A double lab may span it, so it is not a teaching period
#: but it does sit between two adjacent ones.
SHORT_BREAK_PERIOD = 2

#: The 13.15-14.15 lunch break.
LUNCH_PERIOD = 5

BREAK_LABELS: dict[int, str] = {
    SHORT_BREAK_PERIOD: "SHORT_BREAK",
    LUNCH_PERIOD: "LUNCH",
}

#: Wall-clock period index -> (start, end) clock time, as printed on the class
#: timetables (CONTEXT.md section 3.2, from CE_Class_Time_Table-*_sem_25-26.docx).
#: Indices 2 and 5 are the breaks and carry their real durations - 15 minutes and
#: an hour - rather than an invented lecture hour.
PERIOD_TIMES: dict[int, tuple[str, str]] = {
    0: ("09.00", "10.00"),
    1: ("10.00", "11.00"),
    2: ("11.00", "11.15"),  # SHORT_BREAK - not schedulable
    3: ("11.15", "12.15"),
    4: ("12.15", "13.15"),
    5: ("13.15", "14.15"),  # LUNCH - not schedulable
    6: ("14.15", "15.15"),
    7: ("15.15", "16.15"),
    8: ("16.15", "17.15"),
    9: ("17.15", "18.15"),
}

#: Number of real teaching slots in a week: 5 days x 8 teaching periods.
SLOT_COUNT = DAYS * len(TEACHING_PERIODS)

# Position of each teaching period within TEACHING_PERIODS, so adjacency and the
# dense index are O(1) rather than a list scan.
_TEACHING_POSITION: dict[int, int] = {
    period: position for position, period in enumerate(TEACHING_PERIODS)
}


@dataclass(frozen=True, slots=True, order=True)
class SlotId:
    """One (day, period) slot on the wall-clock grid.

    ``period`` is a wall-clock index in 0..9, matching the edge-list contract.
    Break periods (2 and 5) are constructible - the grid contains them - but they
    are never teaching slots, so they are absent from :func:`all_slots` and
    rejected by :func:`slot_index`.
    """

    day: int
    period: int

    def __post_init__(self) -> None:
        if not isinstance(self.day, int) or isinstance(self.day, bool):
            raise TypeError(f"day must be an int, got {type(self.day).__name__}")
        if not isinstance(self.period, int) or isinstance(self.period, bool):
            raise TypeError(f"period must be an int, got {type(self.period).__name__}")
        if not 0 <= self.day < DAYS:
            raise ValueError(f"day must be in 0..{DAYS - 1} (Monday..Friday), got {self.day}")
        if not 0 <= self.period < PERIODS_PER_DAY:
            raise ValueError(
                f"period must be a wall-clock index in 0..{PERIODS_PER_DAY - 1}, "
                f"got {self.period}. Note this is the wall-clock axis including "
                f"breaks, not the ingestion contract's teaching-order 0..7."
            )

    def __str__(self) -> str:
        start, end = PERIOD_TIMES[self.period]
        label = BREAK_LABELS.get(self.period)
        suffix = f" [{label}]" if label else ""
        return f"{DAY_NAMES[self.day]} {start}-{end}{suffix}"


def is_teaching_period(period: int) -> bool:
    """True when this wall-clock period can hold a session."""
    return period in _TEACHING_POSITION


def period_label(period: int) -> str:
    """``'SHORT_BREAK'``/``'LUNCH'`` for the breaks, otherwise the clock range."""
    if period in BREAK_LABELS:
        return BREAK_LABELS[period]
    start, end = PERIOD_TIMES[period]
    return f"{start}-{end}"


def is_adjacent(a: SlotId, b: SlotId) -> bool:
    """True when ``a`` and ``b`` are consecutive teaching slots on the same day.

    Adjacency is measured by position within :data:`TEACHING_PERIODS`, not by the
    raw difference of the period numbers. That is what lets a double lab span a
    break: periods 1 and 3 sit at positions 1 and 2, so they are adjacent even
    though a break separates them on the clock. The same holds for periods 4 and 6
    across lunch.

    A period that is not a teaching period is adjacent to nothing - a break cannot
    be one half of a contiguous pair, it can only be spanned by one.
    """
    if a.day != b.day:
        return False
    position_a = _TEACHING_POSITION.get(a.period)
    position_b = _TEACHING_POSITION.get(b.period)
    if position_a is None or position_b is None:
        return False
    return abs(position_a - position_b) == 1


def all_slots() -> list[SlotId]:
    """Every schedulable slot in the week, day-major and period-minor.

    Ordering is day 0's teaching periods in :data:`TEACHING_PERIODS` order, then
    day 1's, and so on, which makes the result index-aligned with
    :func:`slot_index`.
    """
    return [SlotId(day, period) for day in range(DAYS) for period in TEACHING_PERIODS]


def slot_index(slot: SlotId) -> int:
    """Map a teaching slot onto the dense 0..39 axis.

    Raises:
        ValueError: if ``slot`` falls on a break period, which has no dense index.
    """
    position = _TEACHING_POSITION.get(slot.period)
    if position is None:
        label = BREAK_LABELS.get(slot.period, "not a teaching period")
        raise ValueError(
            f"period {slot.period} has no dense slot index: {label}. "
            f"Teaching periods are {TEACHING_PERIODS}."
        )
    return slot.day * len(TEACHING_PERIODS) + position


def from_index(i: int) -> SlotId:
    """Inverse of :func:`slot_index`.

    Raises:
        ValueError: if ``i`` is outside 0..:data:`SLOT_COUNT` - 1.
    """
    if not isinstance(i, int) or isinstance(i, bool):
        raise TypeError(f"slot index must be an int, got {type(i).__name__}")
    if not 0 <= i < SLOT_COUNT:
        raise ValueError(f"slot index must be in 0..{SLOT_COUNT - 1}, got {i}")
    day, position = divmod(i, len(TEACHING_PERIODS))
    return SlotId(day, TEACHING_PERIODS[position])
