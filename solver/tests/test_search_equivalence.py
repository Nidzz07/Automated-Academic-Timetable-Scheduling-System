"""The 2026-10 search speed-ups change speed, never answers.

* Lazy lab-room candidates: the first solution is identical to the one the
  old eager enumeration found.  The eager code is kept below as the reference
  (verbatim but for S12d's start order) and swapped in with ``monkeypatch``.
* Room symmetry breaking: identical solutions (and so identical
  satisfiability) with and without it.
* Time budget: running out is ``"timeout"``, never ``"infeasible"``.
* S8, the grid read from the payload: on the canonical grid, search, pre-solve
  and Welsh-Powell give exactly the answers the hard-coded grid gave, checked
  against digests recorded from the pre-S8 code.
* S12d, the new search order: every instance keeps its verdict (solved /
  infeasible) from before S12d; the full answers are pinned by new digests.

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
from solver.backtracking import (
    LabBlock,
    _placement_ok,
    _SolverState,
    _start_order,
    backtrack_solve,
)
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

    # S12d: starts in least-constraining order (was ascending); tuples as before
    candidates: list[tuple[SlotId, tuple[str, ...]]] = []
    for start in _start_order(state, members, common_starts):
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

#: SHA-256 of the fingerprints below.  First recorded on 2026-10-17 from the
#: pre-S8 code (main @ 744c712, where solver.slots hard-coded the canonical
#: grid); the S8 code matched them.  Re-recorded on 2026-10-19 for S12d's search
#: order (MRV + degree over blocks and sessions, least-constraining starts),
#: which changes assignments and node counts on purpose: every group but
#: "infeasible" changed; its pre-solve certificates, like every group's
#: Welsh-Powell colouring, did not.  The same under any PYTHONHASHSEED.
_DIGESTS = {
    "property": "1d65215188448a1e26f878c3c59c4c06ff0c5401c81e122759c9afd618a66343",
    "property_subclass": "51be4eded54c7ab0a64faacd626557a5d2dde9b16656f9cc21b9161ebe202343",
    "small": "abacc3ca6cfe7d7b28070fe546dc4cf7d79cd4190ec4e072ec350aaf30a2f7d4",
    "medium": "1056012f0f46f1add181c504f72dd35d3ce6fe098cb0a3a56695c9120be86829",
    "large": "2516537caf2da2d123a021cf8fc9549266449195ed7a1dd22d76bb11357bcc97",
    "infeasible": "5f5a5fa6541f0dc4cd5e63fd644c73b70e82cc3d99f0865dfe1568bb3f0c2b6a",
}

#: SHA-256 of each group's list of outcomes alone, recorded on 2026-10-19 from
#: the pre-S12d code (main @ 75a3f31): a search change may change assignments,
#: never which instances are solved and which are infeasible.
_PRE_S12D_VERDICTS = {
    "property": "cd80f46927daba9f7994331a2e35267271b7c677f99b5c48b5d88a2cc83072c2",
    "property_subclass": "cc39c253998b3a0b1abfc2c4c02e3a5c073932397dd4703103374144243620c2",
    "small": "30ea0f1eb35099373db254880d18bfd83ad9a7f288dd4db6f97dc03413f145d5",
    "medium": "30ea0f1eb35099373db254880d18bfd83ad9a7f288dd4db6f97dc03413f145d5",
    "large": "30ea0f1eb35099373db254880d18bfd83ad9a7f288dd4db6f97dc03413f145d5",
    "infeasible": "cf865e4e3b4095a3a80824e47973f5e5d2a5413fd8bd1211ea57890f5998d7c7",
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


def test_answers_match_the_recorded_digests_and_pre_s12d_verdicts() -> None:
    groups = {
        "property": _property_instances(),
        "property_subclass": [
            generate_instance(random.Random(SEED + i), multi_period=False, blocks=False,
                              fixed=False)
            for i in range(N_INSTANCES)
        ],
        **{name: _presets(name) for name in ("small", "medium", "large", "infeasible")},
    }
    fingerprints = {name: [_fingerprint(e) for e in group] for name, group in groups.items()}

    def digest(x: Any) -> str:
        return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()

    verdicts = {name: digest([f[0] for f in fps]) for name, fps in fingerprints.items()}
    assert verdicts == _PRE_S12D_VERDICTS
    assert {name: digest(fps) for name, fps in fingerprints.items()} == _DIGESTS
