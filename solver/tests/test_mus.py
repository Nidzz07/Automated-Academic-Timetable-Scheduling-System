"""solver.mus (S14b): minimal conflicting sets and verified relaxations.

Synthetic infeasible instances only (the real EVEN scenarios are in
test_repair.py). Minimality is checked against the validator, not against
explain(): the set alone is infeasible for a search with no budget, and for
each member the witness explain() reports is a timetable the validator accepts
once that member is dropped.
"""

from __future__ import annotations

import copy
import json

import pytest

from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.mus import _Problem, apply_action, explain
from solver.tests.test_solution_v2 import RELAXATION_MAP, SOLUTION_V2
from solver.validate import validate_solution


def _infeasible(payload: dict) -> dict:
    result = backtrack_solve(build_conflict_graph(payload), payload)
    assert result.outcome == "infeasible"
    return result.to_solution_v2_dict(total_sessions=len(payload["sessions"]))


def _solved(payload: dict) -> bool:
    """Search with no budget; a timetable found must pass the validator."""
    result = backtrack_solve(build_conflict_graph(payload), payload)
    if result.solved:
        found = {"status": "solved",
                 "assignment": result._placements(result.assignment, result.room_assignment)}
        assert validate_solution(payload, found) == []
    return result.solved


def _small() -> dict:
    return generate(PRESETS["small"], seed=0)


def squeezed_faculty() -> dict:
    """The small preset with its busiest teacher free in one period only."""
    payload = _small()
    load: dict[str, int] = {}
    for s in payload["sessions"]:
        load[s["faculty_id"]] = load.get(s["faculty_id"], 0) + s["duration_periods"]
    fid = max(sorted(load), key=load.get)
    grid = payload["slot_grid"]
    entry = next(a for a in payload["faculty_availability"] if a["faculty_id"] == fid)
    entry["unavailable_slots"] = [{"day": d, "period": p} for d in range(grid["days"])
                                  for p in grid["teaching_periods"] if (d, p) != (0, 0)]
    return payload


def fixed_collision() -> dict:
    """The small preset with two one-period sessions of one cohort fixed to one slot."""
    payload = _small()
    by_cohort: dict[str, list[dict]] = {}
    for s in payload["sessions"]:
        if s["duration_periods"] == 1:
            by_cohort.setdefault(s["cohort_id"], []).append(s)
    pair = next(group[:2] for _, group in sorted(by_cohort.items()) if len(group) >= 2)
    open_cell = next(
        (d, p) for d in range(payload["slot_grid"]["days"])
        for p in payload["slot_grid"]["teaching_periods"]
        if not any((x["day"], x["period"]) == (d, p) for x in payload["pinned_occupancy"])
        and not any((x["day"], x["period"]) == (d, p) for a in payload["faculty_availability"]
                    for x in a["unavailable_slots"]))
    for s in pair:
        s["fixed_slot"] = {"day": open_cell[0], "period": open_cell[1]}
    return payload


def triangle() -> dict:
    """Three sessions joined pairwise by a FACULTY, a COHORT and a ROOM edge, two
    periods, three rooms: pre-solve sees no group to count, the search refutes it."""
    sessions = [{"id": f"s{i}", "subject_id": "subj", "faculty_id": f"f{i}", "cohort_id": f"c{i}",
                 "session_type": "theory", "duration_periods": 1, "cohort_size": 30,
                 "requires_lab": False, "fixed_slot": None} for i in range(3)]
    return {
        "schema_version": "edge_list.v1",
        "slot_grid": {"days": 1, "periods_per_day": 2, "teaching_periods": [0, 1],
                      "adjacency": [[0, 1]]},
        "sessions": sessions,
        "edges": [{"u": "s0", "v": "s1", "reason": "FACULTY"},
                  {"u": "s1", "v": "s2", "reason": "COHORT"},
                  {"u": "s0", "v": "s2", "reason": "ROOM"}],
        "rooms": [{"id": f"r{i}", "code": f"R{i}", "capacity": 30, "is_lab": False,
                   "parent_room_id": None} for i in range(3)],
        "faculty_availability": [{"faculty_id": f"f{i}", "unavailable_slots": []}
                                 for i in range(3)],
        "lab_blocks": [],
        "pinned_occupancy": [],
    }


CASES = {
    "squeezed_faculty": squeezed_faculty,
    "fixed_collision": fixed_collision,
    "infeasible_preset": lambda: generate(PRESETS["infeasible"], seed=0),
    "triangle": triangle,
}


@pytest.fixture(scope="module", params=sorted(CASES))
def explained(request: pytest.FixtureRequest) -> tuple[dict, dict, dict, dict]:
    payload = CASES[request.param]()
    infeasible = _infeasible(payload)
    stats: dict = {}
    result = explain(copy.deepcopy(payload), copy.deepcopy(infeasible), stats=stats)
    return payload, infeasible, result, stats


def test_proven_minimal(explained: tuple[dict, dict, dict, dict]) -> None:
    payload, _, result, stats = explained
    SOLUTION_V2.validate(result)
    diagnosis = result["diagnosis"]
    assert diagnosis["method"] == "mus" and stats["proven_minimal"] and not stats["unknown"]
    members = [m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]]
    assert members == stats["set"] and members
    problem = _Problem(payload, None)
    everything = set(problem.groups)
    alone, _ = problem.instance(everything - set(members))
    assert not _solved(alone)
    assert set(stats["witnesses"]) == set(members)
    for member in members:
        without, _ = problem.instance(everything - set(members) | {member})
        witness = {"status": "solved", "assignment": stats["witnesses"][member]}
        assert validate_solution(without, witness) == [], f"{member} is not needed"
        assert validate_solution(alone, witness), f"the witness for {member} breaks nothing"


def test_relaxation_is_verified(explained: tuple[dict, dict, dict, dict]) -> None:
    payload, _, result, stats = explained
    diagnosis = result["diagnosis"]
    relaxation = diagnosis["suggested_relaxation"]
    kinds = {m["constraint_id"]: m["kind"] for m in diagnosis["minimal_conflicting_set"]}
    assert relaxation["constraint_id"] in kinds
    action = relaxation["action"]
    assert action["action_type"] in RELAXATION_MAP[kinds[relaxation["constraint_id"]]]
    tried = [a["verification"]["status"] for a in stats["relaxations"]]
    if action["action_type"] == "MANUAL":
        assert relaxation["verification"] == {"status": "not_attempted", "runtime_ms": None}
        assert "restored" not in tried
    else:
        assert relaxation["verification"]["status"] == "restored" == tried[-1]
        assert tried.count("restored") == 1  # the first restored one, smallest first
        assert _solved(apply_action(payload, action))


def test_cases_cover_both_proofs_and_typed_relaxations(
        explained: tuple[dict, dict, dict, dict]) -> None:
    payload, infeasible, result, _ = explained
    method = infeasible["diagnosis"]["method"]
    if payload["sessions"][0]["id"] == "s0":  # the triangle
        assert method == "search_exhaustion"
        assert result["diagnosis"]["partial_placement"] == infeasible["diagnosis"][
            "partial_placement"]
        assert {m["kind"] for m in result["diagnosis"]["minimal_conflicting_set"]} == {
            "FACULTY_CLASH", "COHORT_CLASH", "ROOM_CLASH"}
    else:
        assert method == "presolve"


@pytest.mark.parametrize("case", ["squeezed_faculty", "fixed_collision"])
def test_typed_relaxation_restores(case: str) -> None:
    result = explain(CASES[case](), _infeasible(CASES[case]()))
    assert result is not None
    assert result["diagnosis"]["suggested_relaxation"]["verification"]["status"] == "restored"


def test_unknown_is_never_minimal() -> None:
    """With no search nodes no removal can be shown feasible: a pre-solve proof
    stays method presolve, a search proof comes back unchanged (D33)."""
    payload = squeezed_faculty()
    stats: dict = {}
    result = explain(payload, _infeasible(payload), node_limit=0, stats=stats)
    assert result is not None
    SOLUTION_V2.validate(result)
    assert result["diagnosis"]["method"] == "presolve" and not stats["proven_minimal"]
    assert stats["unknown"] and result["diagnosis"]["partial_placement"] == []
    assert "not proven minimal" in result["metadata"]["algorithm"]

    payload = triangle()
    infeasible = _infeasible(payload)
    assert explain(payload, infeasible, node_limit=0) == infeasible


def test_no_proof_no_diagnosis() -> None:
    """An initial set that is not infeasible proves nothing: no result at all."""
    payload = _small()
    assert explain(payload, None, initial=["pin.0"]) is None
    with pytest.raises(ValueError):
        explain(payload, None)


def test_deterministic() -> None:
    def run(build) -> str:
        payload = build()
        out = explain(payload, _infeasible(payload))
        assert out is not None
        out["metadata"].pop("runtime_ms")
        out["diagnosis"]["suggested_relaxation"]["verification"].pop("runtime_ms")
        return json.dumps(out, sort_keys=True)

    for build in CASES.values():
        assert run(build) == run(build)


def test_apply_action_leaves_its_input_alone() -> None:
    payload = squeezed_faculty()
    before = copy.deepcopy(payload)
    fid = payload["faculty_availability"][0]["faculty_id"]
    pin = payload["pinned_occupancy"][0]
    kind, entity = next((k, x[0]) for k in ("faculty", "room", "cohort")
                        if (x := pin[f"{k}_ids"]))
    for action in (
        {"action_type": "RELAX_FACULTY_AVAILABILITY",
         "params": {"faculty_id": fid, "slots": [{"day": 1, "period": 0}]}},
        {"action_type": "RELAX_PINNED_BLOCK",
         "params": {"slot": {"day": pin["day"], "period": pin["period"]},
                    "entity_kind": kind, "entity_id": entity}},
        {"action_type": "UNFIX_SLOT", "params": {"session_id": payload["sessions"][0]["id"]}},
        {"action_type": "RECLASSIFY_ROOM", "params": {"room_id": payload["rooms"][0]["id"],
                                                      "is_lab": True}},
    ):
        apply_action(payload, action)
    assert payload == before
    relaxed = apply_action(payload, {"action_type": "RELAX_PINNED_BLOCK", "params": {
        "slot": {"day": pin["day"], "period": pin["period"]}, "entity_kind": kind,
        "entity_id": entity}})
    assert entity not in relaxed["pinned_occupancy"][0][f"{kind}_ids"]
    with pytest.raises(ValueError):
        apply_action(payload, {"action_type": "MANUAL", "params": {}})
