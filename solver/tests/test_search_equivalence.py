"""The 2026-10 search speed-ups change speed, never answers.

* Lazy lab-room candidates: the first solution is identical to the one the
  old eager enumeration found.  The eager code is kept verbatim below as the
  reference and swapped in with ``monkeypatch``.
* Room symmetry breaking: identical solutions (and so identical
  satisfiability) with and without it.
* Time budget: running out is ``"timeout"``, never ``"infeasible"``.
* S8, the grid read from the payload: on the canonical grid, search, pre-solve
  and Welsh-Powell give exactly the answers the hard-coded grid gave, checked
  against digests recorded from the pre-S8 code.

Instances: the 400 seeded property instances and the synthetic presets
(``large`` only in the symmetry test - the eager reference takes ~40 s on it;
it was compared once against a pre-change snapshot, see the 2026-10-12 section
of docs/solver-baseline-2026-10-06.md).
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

import pytest

import solver.backtracking as bt
from solver.backtracking import LabBlock, _placement_ok, _SolverState, backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.colouring import welsh_powell
from solver.graph import build_conflict_graph
from solver.slots import SlotId
from solver.tests.test_backtracking import _edge, _faculty_avail, _payload, _session
from solver.tests.test_property_solved_is_valid import N_INSTANCES, SEED, generate_instance

# ----------------------------------------------------------------------
# Reference: the eager enumeration as it was before the change
# ----------------------------------------------------------------------


def _eager_gen_room_tuples(
    room_lists: list[list[str]],
    state: _SolverState,
    idx: int = 0,
    chosen: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    if idx == len(room_lists):
        return [chosen]
    results: list[tuple[str, ...]] = []
    for r in room_lists[idx]:
        if any(
            r == c or state.parent_of.get(r) == c or state.parent_of.get(c) == r
            for c in chosen
        ):
            continue
        results.extend(_eager_gen_room_tuples(room_lists, state, idx + 1, (*chosen, r)))
    return results


def _eager_lab_block_candidates(
    state: _SolverState,
    block: LabBlock,
) -> list[tuple[SlotId, tuple[str, ...]]]:
    members = block.session_ids
    if not members:
        return []
    for i, a in enumerate(members):
        if any(b in state.graph.adjacency[a] for b in members[i + 1:]):
            return []

    common_starts = set.intersection(
        *({start for start, _ in state.domains[sid]} for sid in members)
    )

    candidates: list[tuple[SlotId, tuple[str, ...]]] = []
    for start in sorted(common_starts):
        room_lists: list[list[str]] = []
        for sid in members:
            rooms = sorted(
                r for s, r in state.domains[sid]
                if s == start and _placement_ok(state, sid, start, r) is not None
            )
            if not rooms:
                break
            room_lists.append(rooms)
        else:
            for rt in _eager_gen_room_tuples(room_lists, state):
                candidates.append((start, rt))

    candidates.sort()
    return candidates


# ----------------------------------------------------------------------


def _outcome(edge_list: dict[str, Any], **kwargs: Any) -> tuple[Any, ...]:
    r = backtrack_solve(build_conflict_graph(edge_list), edge_list, **kwargs)
    return r.outcome, r.assignment, r.room_assignment


def _property_instances() -> list[dict[str, Any]]:
    return [generate_instance(random.Random(SEED + i)) for i in range(N_INSTANCES)]


def _presets(*names: str) -> list[dict[str, Any]]:
    return [generate(PRESETS[n], seed) for n in names for seed in (1, 2, 3)]


def test_lazy_candidates_find_the_same_solutions_as_eager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = _property_instances() + _presets("small", "medium")
    lazy = [_outcome(e, break_symmetry=False) for e in instances]
    monkeypatch.setattr(bt, "_lab_block_candidates", _eager_lab_block_candidates)
    eager = [_outcome(e, break_symmetry=False) for e in instances]
    assert [i for i, (a, b) in enumerate(zip(lazy, eager, strict=True)) if a != b] == []
    assert sum(o[0] == "solved" for o in lazy) >= N_INSTANCES // 5


def test_symmetry_breaking_keeps_satisfiability_and_solutions() -> None:
    instances = _property_instances() + _presets("small", "medium", "large")
    with_sym = [_outcome(e) for e in instances]
    without = [_outcome(e, break_symmetry=False) for e in instances]
    assert [o[0] for o in with_sym] == [o[0] for o in without]
    assert with_sym == without


def test_symmetry_breaking_prunes_an_infeasible_search() -> None:
    """Three sessions forced into one slot with two interchangeable rooms: with
    symmetry breaking the first session is never retried in the second room."""
    from solver.slots import all_slots

    only = [{"day": s.day, "period": s.period} for s in all_slots() if s != SlotId(0, 0)]
    payload = _payload(
        [_session(f"s{i}", f"f{i}", f"c{i}") for i in range(3)],
        rooms=[{"id": r, "code": r, "capacity": 30, "is_lab": False, "parent_room_id": None}
               for r in ("r1", "r2")],
        faculty_availability=[_faculty_avail(f"f{i}", only) for i in range(3)],
    )
    graph = build_conflict_graph(payload)
    on = backtrack_solve(graph, payload)
    off = backtrack_solve(graph, payload, break_symmetry=False)
    assert on.outcome == off.outcome == "infeasible"
    assert on.nodes_explored < off.nodes_explored


# ----------------------------------------------------------------------
# Time budget
# ----------------------------------------------------------------------


def _odd_cycle() -> dict[str, Any]:
    """Passes pre-solve, so only the search can answer (see test_backtracking)."""
    from solver.slots import all_slots

    ids = [f"s{i}" for i in range(5)]
    unavail = [{"day": s.day, "period": s.period} for s in all_slots()
               if s not in {SlotId(0, 0), SlotId(0, 1)}]
    return _payload(
        [_session(s, faculty=f"f{s}", cohort=f"c{s}") for s in ids],
        edges=[_edge(ids[i], ids[(i + 1) % 5], "COHORT") for i in range(5)],
        faculty_availability=[_faculty_avail(f"f{s}", unavail) for s in ids],
    )


def test_exhausted_budget_is_timeout_not_infeasible() -> None:
    payload = _odd_cycle()
    result = backtrack_solve(build_conflict_graph(payload), payload, time_limit_s=0)
    assert result.outcome == "timeout" and not result.solved and result.timed_out
    with pytest.raises(ValueError, match="no status for a search timeout"):
        result.to_solution_dict()


def test_generous_budget_changes_nothing() -> None:
    for edge_list in [_odd_cycle(), *_presets("small")]:
        assert _outcome(edge_list, time_limit_s=60) == _outcome(edge_list)


# ----------------------------------------------------------------------
# S8: the grid comes from the payload - same answers on the canonical grid
# ----------------------------------------------------------------------

#: SHA-256 of the fingerprints below, recorded on 2026-10-17 by running
#: ``_fingerprint`` as defined here on the pre-S8 code (main @ 744c712, where
#: solver.slots hard-coded the canonical grid). The same under any PYTHONHASHSEED.
_PRE_S8_DIGESTS = {
    "property": "494ec6e8540818ad9b292ec2e2613b2d76823d00a51c9f62888b5d962479ab7b",
    "property_subclass": "b478200793c01651a1a2fc0b85f24400b4e02a9de25d3815928d5aeee2c5eabc",
    "small": "60b4022c7c835af5f83cab7f9b531f72dae963ebedb41c8e87b0f168c30acdb0",
    "medium": "03f9a34d3e6db67a0d3d1f335387a634f37e4f083815cad999f1b70a2eee0a8d",
    "large": "868e16c8e0cd665d50c761462a395b4d8511f5d841b6a78d07fb3e1f57500eb8",
    "infeasible": "5f5a5fa6541f0dc4cd5e63fd644c73b70e82cc3d99f0865dfe1568bb3f0c2b6a",
}


def _fingerprint(edge_list: dict[str, Any]) -> list[Any]:
    """Every answer for one instance: search, pre-solve certificate, Welsh-Powell."""
    graph = build_conflict_graph(edge_list)
    r = backtrack_solve(graph, edge_list)
    cert = r.certificate
    colours, uncoloured = welsh_powell(graph)
    return [
        r.outcome,
        sorted([sid, s.day, s.period] for sid, s in r.assignment.items()),
        sorted([sid, rid] for sid, rid in r.room_assignment.items()),
        r.nodes_explored,
        list(r.unplaced_sessions),
        None if cert is None else [cert.check, cert.kind, list(cert.session_ids),
                                   cert.resource, cert.reason],
        sorted([sid, s.day, s.period] for sid, s in colours.items()),
        list(uncoloured),
    ]


def test_payload_grid_gives_the_pre_s8_answers_on_the_canonical_grid() -> None:
    groups = {
        "property": _property_instances(),
        "property_subclass": [
            generate_instance(random.Random(SEED + i), multi_period=False, blocks=False,
                              fixed=False)
            for i in range(N_INSTANCES)
        ],
        **{name: _presets(name) for name in ("small", "medium", "large", "infeasible")},
    }
    digests = {
        name: hashlib.sha256(
            json.dumps([_fingerprint(e) for e in group], sort_keys=True).encode()
        ).hexdigest()
        for name, group in groups.items()
    }
    assert digests == _PRE_S8_DIGESTS
