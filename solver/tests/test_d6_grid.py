"""SPIT's EVEN grid (ROADMAP D6, D7, D24) read from the payload (S8).

``contracts/examples/edge_list_v1.d6_grid.example.json`` is the frozen
``edge_list_v1`` carrying the D6 grid: P0-P9 with only P2 (coffee) closed for
everyone, and each year's lunch - P5 for SE, P4 for TE - pinned for that year's
cohorts (proposal Row 8 assessment).  Solver, pre-solve and validator must all
read that grid: a lab block runs on the payload's adjacency, may span the
coffee break, and never covers a period pinned for its cohort.

The example's ids, and the sessions and pins the tests add, are test data, not
SPIT facts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from solver.backtracking import (
    BacktrackResult,
    _build_initial_domains,
    _new_state,
    backtrack_solve,
)
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.slots import SlotGrid, SlotId
from solver.tests.test_backtracking import _payload, _room, _session
from solver.tests.test_solution_v2 import SOLUTION_V2, assert_v2_certificate_fields
from solver.validate import validate_slot_placements, validate_solution

D6_EXAMPLE = (Path(__file__).resolve().parents[2] / "contracts" / "examples"
              / "edge_list_v1.d6_grid.example.json")
SE_LUNCH, TE_LUNCH = 5, 4  # ROADMAP section 5
D6_TEACHING = {0, 1, 3, 4, 5, 6, 7, 8, 9}

SE_LECTURE, TE_LECTURE = "sess-se-a-ce206-l", "sess-te-a-ce307-l"
SE_BLOCK = ("sess-se-a-a-ce206-p", "sess-se-a-b-ce207-p")
TE_BLOCK = ("sess-te-a-a-lab-p", "sess-te-a-b-lab-p")


def _d6() -> dict[str, Any]:
    return json.loads(D6_EXAMPLE.read_text(encoding="utf-8"))


def _with_te_block(edge_list: dict[str, Any]) -> dict[str, Any]:
    """Add a TE-Comp A batch lab block the way the exporter would (Row 8 caveat:
    the year's lunch pin lists every cohort of that year, batches included)."""
    e = copy.deepcopy(edge_list)
    for sid, faculty, cohort in [(TE_BLOCK[0], "fac-0005", "coh-batch-te-a-a"),
                                 (TE_BLOCK[1], "fac-0006", "coh-batch-te-a-b")]:
        e["sessions"].append({
            "id": sid, "subject_id": "subj-te-lab", "faculty_id": faculty, "cohort_id": cohort,
            "session_type": "lab", "duration_periods": 2, "cohort_size": 20,
            "requires_lab": True, "fixed_slot": None,
        })
        e["faculty_availability"].append({"faculty_id": faculty, "unavailable_slots": []})
        e["edges"].append({"u": TE_LECTURE, "v": sid, "reason": "COHORT"})
    e["lab_blocks"].append({"id": "labblk-te-a-1", "session_ids": list(TE_BLOCK),
                            "duration_periods": 2, "must_be_contiguous": True})
    for pin in e["pinned_occupancy"]:
        if pin["period"] == TE_LUNCH:
            pin["cohort_ids"] += ["coh-batch-te-a-a", "coh-batch-te-a-b"]
    return e


def _only_open(edge_list: dict[str, Any], faculty: tuple[str, ...], *slots: SlotId) -> None:
    """Leave exactly *slots* open for each of *faculty*."""
    grid = SlotGrid.from_payload(edge_list["slot_grid"])
    for entry in edge_list["faculty_availability"]:
        if entry["faculty_id"] in faculty:
            entry["unavailable_slots"] = [{"day": s.day, "period": s.period}
                                          for s in grid.all_slots() if s not in slots]


def _block(members: tuple[str, ...], day: int, period: int) -> list[tuple[Any, ...]]:
    return [(sid, day, period, "room-702", sub)
            for sid, sub in zip(members, ("room-702-a", "room-702-b"), strict=True)]


def _placed(*rows: tuple[Any, ...]) -> dict[str, Any]:
    """A hand-built solved payload from (session, day, period, room, sub_room) rows."""
    return {"status": "solved", "assignment": [
        {"session_id": s, "day": d, "period": p, "room_id": r, "sub_room_id": sub}
        for s, d, p, r, sub in rows
    ]}


LECTURES = [(SE_LECTURE, 1, 0, "room-601", None), (TE_LECTURE, 0, 5, "room-701", None)]


def _starts(edge_list: dict[str, Any], sid: str) -> set[SlotId]:
    """Every start the solver will consider for *sid* (its initial domain)."""
    state = _new_state(build_conflict_graph(edge_list), edge_list)
    _build_initial_domains(state)
    return {start for start, _ in state.domains[sid]}


def _solved(edge_list: dict[str, Any]) -> BacktrackResult:
    """Solve, and hold the result to the validator and the solution_v2 schema."""
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    assert result.solved
    solution = result.to_solution_v2_dict()
    SOLUTION_V2.validate(solution)
    assert validate_solution(edge_list, solution) == []
    return result


def _week(*periods: int) -> set[SlotId]:
    return {SlotId(day, period) for day in range(5) for period in periods}


# ----------------------------------------------------------------------
# The example as committed
# ----------------------------------------------------------------------


def test_d6_example_solves_with_each_years_lunch_free() -> None:
    result = _solved(_d6())
    assert result.assignment[TE_LECTURE] == SlotId(0, 5)  # P5 teaches for TE
    assert result.assignment[SE_BLOCK[0]] == result.assignment[SE_BLOCK[1]]
    assert all(s.period != SE_LUNCH for sid in (SE_LECTURE, *SE_BLOCK)
               for s in result.occupied[sid])


# ----------------------------------------------------------------------
# Lab blocks on the D6 grid (D7)
# ----------------------------------------------------------------------


def test_se_lab_block_over_p4_p5_is_rejected() -> None:
    """P4-P5 is a contiguous pair on the D6 grid, but P5 is SE's lunch."""
    e = _d6()
    violations = validate_solution(e, _placed(*LECTURES, *_block(SE_BLOCK, 0, 4)))
    assert [(v.kind, v.session_ids, v.slots) for v in violations] == [
        ("PINNED_BLOCK", (SE_BLOCK[0],), (SlotId(0, SE_LUNCH),)),
        ("PINNED_BLOCK", (SE_BLOCK[1],), (SlotId(0, SE_LUNCH),)),
    ]
    # The solver never offers a start whose two periods touch SE's lunch.
    for sid in SE_BLOCK:
        assert _starts(e, sid) == _week(0, 1, 3, 6, 7, 8)


def test_te_lab_block_over_p5_p6_is_accepted() -> None:
    e = _with_te_block(_d6())
    rows = [*LECTURES, *_block(SE_BLOCK, 0, 1), *_block(TE_BLOCK, 1, 5)]
    assert validate_solution(e, _placed(*rows)) == []
    for sid in TE_BLOCK:  # TE's lunch is P4, so P3-P4 and P4-P5 are out
        assert _starts(e, sid) == _week(0, 1, 5, 6, 7, 8)
    _only_open(e, ("fac-0005", "fac-0006"), SlotId(1, 5), SlotId(1, 6))
    result = _solved(e)
    assert result.occupied[TE_BLOCK[0]] == (SlotId(1, 5), SlotId(1, 6))


def test_lab_block_across_the_coffee_break_is_accepted() -> None:
    e = _d6()
    assert validate_solution(e, _placed(*LECTURES, *_block(SE_BLOCK, 0, 1))) == []
    _only_open(e, ("fac-0003", "fac-0004"), SlotId(2, 1), SlotId(2, 3))
    result = _solved(e)
    assert result.occupied[SE_BLOCK[0]] == (SlotId(2, 1), SlotId(2, 3))


def test_lab_block_never_covers_a_frozen_item() -> None:
    """D24: a frozen elective holding one batch blocks that batch's lab block."""
    e = _d6()
    e["pinned_occupancy"].append({"day": 3, "period": 7, "faculty_ids": [], "room_ids": [],
                                  "cohort_ids": ["coh-batch-se-a-a"]})
    assert not {SlotId(3, 6), SlotId(3, 7)} & _starts(e, SE_BLOCK[0])
    assert SlotId(3, 6) in _starts(e, SE_BLOCK[1])
    [v] = validate_solution(e, _placed(*LECTURES, *_block(SE_BLOCK, 3, 6)))
    assert (v.kind, v.session_ids, v.slots) == ("PINNED_BLOCK", (SE_BLOCK[0],), (SlotId(3, 7),))
    _only_open(e, ("fac-0003", "fac-0004"), SlotId(3, 6), SlotId(3, 7))
    assert backtrack_solve(build_conflict_graph(e), e).outcome == "infeasible"


# ----------------------------------------------------------------------
# Pre-solve and search count each year's own teaching periods
# ----------------------------------------------------------------------


def _one_division(cohort: str, lunch: int, sessions: int) -> dict[str, Any]:
    """D6 grid, one division's lectures, each with its own teacher, all clashing."""
    e = _d6()
    ids = [f"t{i:02d}" for i in range(sessions)]
    e["sessions"] = [
        {"id": sid, "subject_id": f"subj-{sid}", "faculty_id": f"fac-{sid}", "cohort_id": cohort,
         "session_type": "theory", "duration_periods": 1, "cohort_size": 80,
         "requires_lab": False, "fixed_slot": None}
        for sid in ids
    ]
    e["edges"] = [{"u": a, "v": b, "reason": "COHORT"} for i, a in enumerate(ids)
                  for b in ids[i + 1:]]
    e["faculty_availability"] = [{"faculty_id": f"fac-{sid}", "unavailable_slots": []}
                                 for sid in ids]
    e["lab_blocks"] = []
    e["pinned_occupancy"] = [{"day": d, "period": lunch, "faculty_ids": [], "room_ids": [],
                              "cohort_ids": [cohort]} for d in range(5)]
    return e


@pytest.mark.parametrize(("cohort", "lunch"), [("coh-div-se-a", SE_LUNCH),
                                               ("coh-div-te-a", TE_LUNCH)])
def test_each_year_has_its_own_forty_periods(cohort: str, lunch: int) -> None:
    """Nine teaching periods a day less the year's lunch: 40 a week, for search
    and pre-solve alike."""
    result = _solved(_one_division(cohort, lunch, 40))
    assert {s.period for s in result.assignment.values()} == D6_TEACHING - {lunch}

    over = _one_division(cohort, lunch, 41)
    result = backtrack_solve(build_conflict_graph(over), over)
    cert = result.certificate
    assert cert is not None
    assert (cert.check, cert.kind, cert.resource) == ("cohort_load", "COHORT_CLASH", cohort)
    assert "41 periods" in cert.reason and "only 40 periods" in cert.reason
    assert set(cert.slots) == _week(*(D6_TEACHING - {lunch}))
    # The lunch pins are what make the bound bite, yet no pin is offered for
    # relaxing: the backend refuses a lunch pin, and edge_list_v1 cannot tell
    # the solver which pins are lunch (Row 8 assessment).
    fields = cert.to_v2_fields()
    assert_v2_certificate_fields(fields)
    assert fields["suggested_relaxation"]["action"]["action_type"] == "MANUAL"


# ----------------------------------------------------------------------
# Any well-formed grid, not only SPIT's
# ----------------------------------------------------------------------


def test_a_grid_unlike_spits_is_solved_and_checked_on_its_own_terms() -> None:
    """Two days, twelve periods, one joined pair: a double can only run 10-11."""
    payload = _payload([_session("lab", faculty="f1", duration=2)],
                       rooms=[_room("r1", capacity=30)])
    payload["slot_grid"] = {"days": 2, "periods_per_day": 12,
                            "teaching_periods": [0, 1, 10, 11], "adjacency": [[10, 11]]}
    result = _solved(payload)
    assert result.occupied["lab"] == (SlotId(0, 10), SlotId(0, 11))
    colours, uncoloured = welsh_powell(build_conflict_graph(payload))
    assert uncoloured == [] and colours["lab"] == SlotId(0, 10)
    assert validate_slot_placements(payload, {"lab": (0, 10)}) == []

    payload["pinned_occupancy"] = [{"day": 2, "period": 0, "faculty_ids": [], "room_ids": [],
                                    "cohort_ids": []}]
    with pytest.raises(ValueError, match="off the slot grid"):
        build_conflict_graph(payload)
