"""Pinned items and the cohort-clash rule on the real EVEN instance (S14u part 1).

:func:`solver.graph.slot_is_open` (and so backtracking, repair, improve and
``validate.py``) blocks a session at a pinned slot only when the pin lists the
session's own ``cohort_id``. Session-session clashes use the payload's COHORT
edges instead: two cohorts clash when they share a batch. These tests prove the
two rules agree on the committed edge list, so the exact-id test cannot let a
session sit with students a pin already holds.

Why they agree: ``db/export_edge_list.py`` writes each pin's ``cohort_ids`` as
``overlapping(owner)``, every cohort sharing a batch with the pin's owner, and
every batch of each division is in that universe. So the batches a pin lists are
exactly the batches it holds. A frozen PCS practical of SE-Comp A batch D lists
SE-Comp A and batch D, not batches A-C: those batches run their own practicals
beside it, as the printed timetable does (63 such placements in the S12g
``solution.json``; none shares a student with the pin).

``display.json`` ``batches`` gives the division -> batch hierarchy; the first
test checks it reproduces the COHORT edges, so the overlap used below is the
one session clashes use.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from solver.benchmarks.real_solve import INSTANCE
from solver.graph import build_conflict_graph


@pytest.fixture(scope="module")
def edge_list() -> dict[str, Any]:
    return json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def batches_of(edge_list: dict[str, Any]) -> dict[str, set[str]]:
    display = json.loads((INSTANCE / "display.json").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for division, batches in display["batches"].items():
        out[division] = set(batches)
        out.update({b: {b} for b in batches})
    return out


def test_hierarchy_reproduces_the_cohort_edges(
    edge_list: dict[str, Any], batches_of: dict[str, set[str]]
) -> None:
    cohort = {s["id"]: s["cohort_id"] for s in edge_list["sessions"]}
    edged = {
        frozenset((cohort[e["u"]], cohort[e["v"]]))
        for e in edge_list["edges"]
        if e["reason"] == "COHORT"
    }
    used = sorted(set(cohort.values()))
    assert set(used) <= set(batches_of)
    for i, a in enumerate(used):
        for b in used[i + 1 :]:
            assert bool(batches_of[a] & batches_of[b]) == (frozenset((a, b)) in edged), (a, b)


def test_a_pin_blocks_exactly_the_cohorts_sharing_its_batches(
    edge_list: dict[str, Any], batches_of: dict[str, set[str]]
) -> None:
    graph = build_conflict_graph(edge_list)
    all_batches = {b for c, bs in batches_of.items() if bs == {c} for b in bs}
    cohorts = {s.cohort_id for s in graph.sessions.values()}
    checked = 0
    for slot, pin in graph.pinned_slots.items():
        held = pin["cohort_ids"] & all_batches
        for c in cohorts:
            # slot_is_open's test == the overlap rule session clashes use
            assert (c in pin["cohort_ids"]) == bool(batches_of[c] & held), (slot, c)
            checked += 1
    assert checked == len(graph.pinned_slots) * len(cohorts) > 0


def test_no_committed_placement_shares_a_batch_a_pin_holds(
    edge_list: dict[str, Any], batches_of: dict[str, set[str]]
) -> None:
    graph = build_conflict_graph(edge_list)
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    teaching = list(graph.grid.teaching_periods)
    all_batches = {b for c, bs in batches_of.items() if bs == {c} for b in bs}
    for a in solution["assignment"]:
        s = graph.sessions[a["session_id"]]
        start = teaching.index(a["period"])
        for period in teaching[start : start + s.duration_periods]:
            pin = graph.pinned_slots.get(graph.grid.slot(a["day"], period))
            if pin is not None:
                assert not batches_of[s.cohort_id] & pin["cohort_ids"] & all_batches, (
                    s.id, a["day"], period,
                )
