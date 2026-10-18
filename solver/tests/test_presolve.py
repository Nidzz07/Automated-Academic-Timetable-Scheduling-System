"""Tests for :mod:`solver.presolve`.

Every check gets a minimal instance it rejects and a neighbouring one it
passes.  A rejection must also reach ``backtrack_solve`` as an infeasible
``solution_v1`` result carrying the certificate, with no search, and as a
``solution.v2`` result with ``diagnosis.method = "presolve"`` (row 9, D43).
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
from jsonschema import Draft202012Validator

from solver.backtracking import _build_initial_domains, _new_state, backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.presolve import Certificate, hopcroft_karp, presolve
from solver.slots import SlotId, all_slots
from solver.tests.test_backtracking import (
    _edge,
    _faculty_avail,
    _lab_block,
    _payload,
    _room,
    _session,
)
from solver.tests.test_solution_v2 import SOLUTION_V2, assert_v2_certificate_fields

SOLUTION_V1 = Draft202012Validator(json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "solution_v1.schema.json")
    .read_text(encoding="utf-8")
))


def _check(payload: dict[str, Any]) -> Certificate | None:
    state = _new_state(build_conflict_graph(payload), payload)
    _build_initial_domains(state)
    return presolve(state)


def _only(*open_slots: SlotId) -> list[dict[str, int]]:
    """Unavailability that leaves exactly *open_slots* free."""
    return [{"day": s.day, "period": s.period} for s in all_slots() if s not in open_slots]


A, B = SlotId(0, 0), SlotId(0, 1)


def _assert_rejected(payload: dict[str, Any], check: str, kind: str) -> Certificate:
    cert = _check(payload)
    assert cert is not None and (cert.check, cert.kind) == (check, kind), cert
    result = backtrack_solve(build_conflict_graph(payload), payload)
    assert result.outcome == "infeasible" and result.nodes_explored == 0
    assert result.certificate == cert
    solution = result.to_solution_dict()
    SOLUTION_V1.validate(solution)
    assert solution["diagnosis"]["minimal_conflicting_set"][0]["description"] == cert.reason
    v2 = result.to_solution_v2_dict()
    SOLUTION_V2.validate(v2)
    assert v2["diagnosis"]["method"] == "presolve"
    assert_v2_certificate_fields(v2["diagnosis"])
    assert v2["diagnosis"]["minimal_conflicting_set"][0]["kind"] == kind
    return cert


# ----------------------------------------------------------------------
# room_suitability
# ----------------------------------------------------------------------


def test_room_type_rejected_and_passed() -> None:
    lab = [_session("s1", requires_lab=True, session_type="lab")]
    cert = _assert_rejected(_payload(lab, rooms=[_room("r1", capacity=60)]),
                            "room_suitability", "ROOM_TYPE")
    assert cert.session_ids == ("s1",)
    assert cert.slots == ()  # not about a time
    assert _check(_payload(lab, rooms=[_room("L", capacity=60, is_lab=True)])) is None


def test_room_capacity_rejected_and_passed() -> None:
    big = [_session("s1", cohort_size=100)]
    _assert_rejected(_payload(big, rooms=[_room("r1", capacity=80)]),
                     "room_suitability", "ROOM_CAPACITY")
    assert _check(_payload(big, rooms=[_room("r1", capacity=100)])) is None


# ----------------------------------------------------------------------
# faculty_load / cohort_load (pigeonhole)
# ----------------------------------------------------------------------


def _faculty_pair(*open_slots: SlotId) -> dict[str, Any]:
    return _payload(
        [_session("s1", "f1", "c1"), _session("s2", "f1", "c2")],
        edges=[_edge("s1", "s2", "FACULTY")],
        faculty_availability=[_faculty_avail("f1", _only(*open_slots))],
    )


def test_faculty_load_rejected_and_passed() -> None:
    cert = _assert_rejected(_faculty_pair(A), "faculty_load", "FACULTY_CLASH")
    assert (cert.resource, cert.session_ids) == ("f1", ("s1", "s2"))
    assert cert.slots == (A,)  # every slot the group can use
    assert _check(_faculty_pair(A, B)) is None


def _division_and_batches(*open_slots: SlotId) -> dict[str, Any]:
    """A division session conflicts with each batch session; batches don't."""
    return _payload(
        [_session("div", "f1", "D"), _session("a", "f2", "D-A"), _session("b", "f3", "D-B")],
        edges=[_edge("div", "a", "COHORT"), _edge("div", "b", "COHORT")],
        faculty_availability=[_faculty_avail(f, _only(*open_slots)) for f in ("f1", "f2", "f3")],
    )


def test_cohort_load_counts_division_sessions_against_each_batch() -> None:
    cert = _assert_rejected(_division_and_batches(A), "cohort_load", "COHORT_CLASH")
    assert cert.resource == "D" and set(cert.session_ids) == {"div", "a"}
    # Two slots: the batches share one, the division takes the other.
    assert _check(_division_and_batches(A, B)) is None


# ----------------------------------------------------------------------
# lab_capacity
# ----------------------------------------------------------------------


def _fixed_lab_block(sub_rooms: int) -> dict[str, Any]:
    members = [f"m{i}" for i in range(3)]
    return _payload(
        [_session(m, f"f{m}", f"B{m}", duration=2, requires_lab=True, session_type="lab",
                  fixed_slot={"day": 0, "period": 0}) for m in members],
        rooms=[_room("L", capacity=60, is_lab=True)]
        + [_room(f"L-{k}", capacity=20, is_lab=True, parent_room_id="L")
           for k in range(sub_rooms)],
        lab_blocks=[_lab_block("blk", members)],
    )


def test_lab_capacity_rejected_and_passed() -> None:
    cert = _assert_rejected(_fixed_lab_block(2), "lab_capacity", "ROOM_OCCUPANCY")
    assert cert.session_ids == ("m0", "m1", "m2") and cert.resource == "slot.0.0"
    assert cert.slots == (SlotId(0, 0),)
    assert _check(_fixed_lab_block(3)) is None


# ----------------------------------------------------------------------
# hall_faculty / hall_cohort (counting passes, matching does not)
# ----------------------------------------------------------------------


def _three_with_two_pinned(reason: str, fixed_to_same: bool) -> dict[str, Any]:
    """Three pairwise-conflicting sessions, two of them fixed to Mon 09.00."""
    second = A if fixed_to_same else B
    fixed = [{"day": 0, "period": 0}, {"day": second.day, "period": second.period}, None]
    by_faculty = reason == "FACULTY"
    sessions = [
        _session(f"s{i}", "f1" if by_faculty else f"f{i}", f"c{i}" if by_faculty else "c1",
                 fixed_slot=fixed[i])
        for i in range(3)
    ]
    return _payload(sessions, edges=[_edge("s0", "s1", reason), _edge("s0", "s2", reason),
                                     _edge("s1", "s2", reason)])


@pytest.mark.parametrize(("reason", "check", "kind"), [
    ("FACULTY", "hall_faculty", "FACULTY_CLASH"),
    ("COHORT", "hall_cohort", "COHORT_CLASH"),
])
def test_hall_rejected_and_passed(reason: str, check: str, kind: str) -> None:
    cert = _assert_rejected(_three_with_two_pinned(reason, True), check, kind)
    assert cert.session_ids == ("s0", "s1")  # the violator, not the whole group
    assert cert.slots == (A,)  # the only slot the violator can use
    assert _check(_three_with_two_pinned(reason, False)) is None


def test_hopcroft_karp_matches_networkx() -> None:
    rng = random.Random(7)
    for _ in range(200):
        n_left, n_right = rng.randint(0, 9), rng.randint(0, 9)
        adj = [sorted(rng.sample(range(n_right), rng.randint(0, n_right)))
               for _ in range(n_left)]
        match = hopcroft_karp(adj, n_right)
        matched = [v for v in match if v != -1]
        assert len(matched) == len(set(matched))
        assert all(v == -1 or v in adj[u] for u, v in enumerate(match))
        g = nx.Graph()
        g.add_nodes_from(("L", u) for u in range(n_left))
        g.add_edges_from((("L", u), ("R", v)) for u in range(n_left) for v in adj[u])
        best = nx.bipartite.hopcroft_karp_matching(g, top_nodes=[("L", u)
                                                                  for u in range(n_left)])
        assert len(matched) == len(best) // 2


# ----------------------------------------------------------------------
# The synthetic infeasible preset (ROADMAP Phase 5 edge case)
# ----------------------------------------------------------------------


def test_infeasible_preset_is_proved_by_presolve_in_under_5_s() -> None:
    edge_list = generate(PRESETS["infeasible"], 1)
    started = time.perf_counter()
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    assert time.perf_counter() - started < 5
    assert result.outcome == "infeasible" and result.nodes_explored == 0
    assert result.certificate is not None
    assert (result.certificate.check, result.certificate.resource) == ("cohort_load", "d00")
    SOLUTION_V1.validate(result.to_solution_dict())
