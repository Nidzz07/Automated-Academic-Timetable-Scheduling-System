"""``solution.v2`` output (S8): :meth:`BacktrackResult.to_solution_v2_dict`.

Every payload it produces here is validated against the frozen
``contracts/solution_v2.schema.json`` (jsonschema in tests only):

* solved - the assignment, and a quality block listing every ROADMAP D34 rule
  as ``not_evaluated`` until scoring exists (S10);
* infeasible after a search - ``method = "search_exhaustion"``, the deepest
  consistent partial placement (proposal row 2) and the unplaced sessions;
* a pre-solve certificate and a timeout are refused (proposed contract row 9;
  ROADMAP D33).

The proposal's cross-field rules are checked as plain tests: the partial and the
unplaced ids partition the sessions, ``sessions_assigned`` counts the partial,
and the partial is conflict-free under the independent validator.
"""

from __future__ import annotations

import json
import random
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from solver.backtracking import QUALITY_RULE_IDS, BacktrackResult, backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.slots import SlotId
from solver.tests.test_property_solved_is_valid import N_INSTANCES, SEED, generate_instance
from solver.tests.test_search_equivalence import _odd_cycle
from solver.validate import validate_solution

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "contracts" / "solution_v2.schema.json").read_text(encoding="utf-8"))
SOLUTION_V2 = Draft202012Validator(SCHEMA)
RELAXATION_MAP: dict[str, list[str]] = json.loads(
    (REPO / "contracts" / "relaxation_actions_v2.json").read_text(encoding="utf-8")
)


@cache
def v2_part(*path: str) -> Draft202012Validator:
    """A validator for one sub-schema of solution_v2, with its ``$defs`` still resolvable."""
    node: Any = SCHEMA
    for key in path:
        node = node[key]
    return Draft202012Validator({**node, "$defs": SCHEMA["$defs"]})


def assert_v2_certificate_fields(fields: dict[str, Any]) -> None:
    """What a pre-solve certificate would carry under v2, checked part by part.

    The whole diagnosis cannot be validated: ``method`` has no value for a
    certificate yet (proposed contract row 9).
    """
    diagnosis = ("properties", "diagnosis", "properties")
    (entry,) = fields["minimal_conflicting_set"]
    v2_part(*diagnosis, "minimal_conflicting_set", "items").validate(entry)
    relaxation = fields["suggested_relaxation"]
    v2_part(*diagnosis, "suggested_relaxation").validate(relaxation)
    assert relaxation["constraint_id"] == entry["constraint_id"]
    assert relaxation["action"]["action_type"] in RELAXATION_MAP[entry["kind"]]
    assert relaxation["action"] == {"action_type": "MANUAL", "params": {}}
    assert relaxation["verification"] == {"status": "not_attempted", "runtime_ms": None}


def _solve(edge_list: dict[str, Any]) -> BacktrackResult:
    return backtrack_solve(build_conflict_graph(edge_list), edge_list)


def _check_v2(edge_list: dict[str, Any], result: BacktrackResult) -> dict[str, Any]:
    """Serialise, validate against the schema, and check what the schema cannot."""
    solution = result.to_solution_v2_dict()
    SOLUTION_V2.validate(solution)
    ids = [s["id"] for s in edge_list["sessions"]]
    metadata = solution["metadata"]
    assert metadata["sessions_total"] == len(ids)
    if solution["status"] == "solved":
        assert validate_solution(edge_list, solution) == []
        assert solution["assignment"] == result.to_solution_dict()["assignment"]
        return solution

    diagnosis = solution["diagnosis"]
    placed = [p["session_id"] for p in diagnosis["partial_placement"]]
    unplaced = diagnosis["unplaced_session_ids"]
    assert sorted(placed + unplaced) == sorted(ids)
    assert metadata["sessions_assigned"] == len(placed)
    assert metadata["slots_used"] is None
    # The partial is conflict-free: lab blocks are placed whole or not at all,
    # and the validator passes it on the instance cut down to what it places.
    blocks = [set(b["session_ids"]) for b in edge_list["lab_blocks"]]
    assert all(members <= set(placed) or not members & set(placed) for members in blocks)
    cut = {
        **edge_list,
        "sessions": [s for s in edge_list["sessions"] if s["id"] in placed],
        "edges": [e for e in edge_list["edges"] if e["u"] in placed and e["v"] in placed],
        "lab_blocks": [b for b in edge_list["lab_blocks"] if set(b["session_ids"]) <= set(placed)],
    }
    partial = {"status": "solved", "assignment": diagnosis["partial_placement"]}
    assert validate_solution(cut, partial) == []
    return solution


# ----------------------------------------------------------------------
# Synthetic presets and the property generator
# ----------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("preset", ["small", "medium", "large"])
def test_feasible_presets_through_v2(preset: str, seed: int) -> None:
    edge_list = generate(PRESETS[preset], seed)
    result = _solve(edge_list)
    assert result.outcome == "solved"
    solution = _check_v2(edge_list, result)
    assert solution["metadata"] == result.to_solution_dict()["metadata"]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_infeasible_preset_is_refused_until_contract_row_9(seed: int) -> None:
    """Pre-solve proves it (cohort pigeonhole on d00): no honest v2 method exists."""
    edge_list = generate(PRESETS["infeasible"], seed)
    result = _solve(edge_list)
    assert result.certificate is not None and result.certificate.check == "cohort_load"
    with pytest.raises(ValueError, match="row 9"):
        result.to_solution_v2_dict()
    assert_v2_certificate_fields(result.certificate.to_v2_fields())


def test_property_instances_through_v2() -> None:
    seen = {"solved": 0, "search_exhaustion": 0, "certificate": 0}
    non_empty_partials = 0
    for i in range(N_INSTANCES):
        edge_list = generate_instance(random.Random(SEED + i))
        result = _solve(edge_list)
        if result.certificate is not None:
            seen["certificate"] += 1
            with pytest.raises(ValueError, match="row 9"):
                result.to_solution_v2_dict()
            assert_v2_certificate_fields(result.certificate.to_v2_fields())
            continue
        solution = _check_v2(edge_list, result)
        seen["solved" if solution["status"] == "solved" else "search_exhaustion"] += 1
        non_empty_partials += bool(solution.get("diagnosis", {}).get("partial_placement"))
    # The property is only as strong as what it exercised.  Most exhausted
    # searches here fail on their first lab block (a teacher shared inside the
    # block), so their deepest partial is empty; a few get further.
    assert min(seen.values()) >= 5, seen
    assert non_empty_partials >= 2, non_empty_partials


# ----------------------------------------------------------------------
# The quality block (row 6) and the search-exhaustion diagnosis (rows 2, 5)
# ----------------------------------------------------------------------


def test_quality_lists_every_d34_rule_as_not_evaluated() -> None:
    quality = _solve(generate(PRESETS["small"], 1)).to_solution_v2_dict()["quality"]
    assert QUALITY_RULE_IDS == ("S-GAP", "S-B2B", "S-LOAD16", "FAC_LOAD_IMBALANCE")
    assert [e["rule_id"] for e in quality["breakdown"]] == list(QUALITY_RULE_IDS)
    assert {e["status"] for e in quality["breakdown"]} == {"not_evaluated"}
    assert all("raw" not in e and "penalty" not in e and e["reason"] for e in quality["breakdown"])
    assert quality["not_evaluated_rule_ids"] == list(QUALITY_RULE_IDS)


def test_search_exhaustion_keeps_the_first_deepest_partial() -> None:
    """C5 in two slots and one room: no partial gets past two sessions.

    The search first places s0 at Monday 09.00 and s1 at Monday 10.00, then
    fails, and later reaches the mirror image (s0 at 10.00, s1 at 09.00) at the
    same depth: the first one is kept.
    """
    edge_list = _odd_cycle()
    result = _solve(edge_list)
    assert result.outcome == "infeasible" and result.certificate is None
    diagnosis = _check_v2(edge_list, result)["diagnosis"]
    assert diagnosis["method"] == "search_exhaustion"
    assert diagnosis["minimal_conflicting_set"] == []
    assert "suggested_relaxation" not in diagnosis
    assert result.partial_assignment == {"s0": SlotId(0, 0), "s1": SlotId(0, 1)}
    assert diagnosis["partial_placement"] == [
        {"session_id": "s0", "day": 0, "period": 0, "room_id": "room-default",
         "sub_room_id": None},
        {"session_id": "s1", "day": 0, "period": 1, "room_id": "room-default",
         "sub_room_id": None},
    ]
    assert diagnosis["unplaced_session_ids"] == ["s2", "s3", "s4"]


def test_a_timeout_is_never_serialised() -> None:
    """ROADMAP D33: a timeout is a job status, in neither contract."""
    edge_list = _odd_cycle()
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, time_limit_s=0)
    assert result.outcome == "timeout"
    with pytest.raises(ValueError, match="D33"):
        result.to_solution_v2_dict()


def test_v1_output_is_unchanged_by_v2() -> None:
    """v1 keeps its placeholder diagnosis and stand-in score; only v2 is honest."""
    result = _solve(_odd_cycle())
    v1 = result.to_solution_dict()
    assert v1["schema_version"] == "solution.v1"
    assert v1["metadata"]["sessions_assigned"] == 0
    assert v1["diagnosis"]["minimal_conflicting_set"][0]["kind"] == "UNSATISFIABLE_DOMAIN"
    solved = _solve(generate(PRESETS["small"], 1)).to_solution_dict()
    assert solved["quality"] == {"score": 100.0, "breakdown": []}
