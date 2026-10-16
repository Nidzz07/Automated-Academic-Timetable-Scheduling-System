"""Validation tests for the v2 contracts (docs/contract-change-proposal-v2.md, rows 1-6 and 8).

Mirrors ``test_schemas.py``: each v2 schema is a legal, closed JSON Schema; each v2
example validates; a malformed variant of each example is rejected. On top of that
it pins the rules the proposal adds - the closed ``kind`` enum, the retired
placeholder kinds, the infeasible branch that forbids anything timetable-shaped,
``diagnosis.method``, the typed relaxation and its verification, the quality
block's per-rule status, the faculty-resolution states - and runs the cross-field
rules JSON Schema cannot state (proposal sections 1, 2, 6, 8.3) as plain tests.
Row 8 adds the wall-clock period axis of ROADMAP section 5 and the D6 grid
example, which validates against the frozen ``edge_list_v1``.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

SCHEMA_FILES = {
    "ingestion": "ingestion_v2.schema.json",
    "solution": "solution_v2.schema.json",
    "edge_list": "edge_list_v1.schema.json",
}
RELAXATION_MAP = "relaxation_actions_v2.json"

INGESTION = "ingestion_v2.example.json"
SOLVED = "solution_v2.solved.example.json"
INFEASIBLE = "solution_v2.infeasible.example.json"
D6_GRID = "edge_list_v1.d6_grid.example.json"

EXAMPLE_FILES = {
    INGESTION: "ingestion",
    SOLVED: "solution",
    INFEASIBLE: "solution",
    D6_GRID: "edge_list",
}

RETIRED_KINDS = ["UNSATISFIABLE_DOMAIN", "INFEASIBLE_INSTANCE"]

Mutator = Callable[[Any], Any]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def schema(name: str) -> dict[str, Any]:
    return load_json(CONTRACTS_DIR / SCHEMA_FILES[name])


def example(filename: str) -> Any:
    return copy.deepcopy(load_json(EXAMPLES_DIR / filename))


def relaxation_map() -> dict[str, list[str]]:
    return load_json(CONTRACTS_DIR / RELAXATION_MAP)


def is_valid(schema_name: str, payload: Any) -> bool:
    return Draft202012Validator(schema(schema_name)).is_valid(payload)


def assert_valid(schema_name: str, payload: Any) -> None:
    Draft202012Validator(schema(schema_name)).validate(payload)


def assert_rejected(schema_name: str, payload: Any) -> None:
    assert not is_valid(schema_name, payload), "payload was expected to be rejected"


def kind_enum() -> list[str]:
    return schema("solution")["$defs"]["kind"]["enum"]


def action_type_enum() -> list[str]:
    action = schema("solution")["properties"]["diagnosis"]["properties"]["suggested_relaxation"][
        "properties"
    ]["action"]
    return action["properties"]["action_type"]["enum"]


# --------------------------------------------------------------------------
# 1. the schemas are legal, identified and closed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_schema_is_a_valid_json_schema(schema_name: str) -> None:
    Draft202012Validator.check_schema(schema(schema_name))


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_schema_declares_its_identity(schema_name: str) -> None:
    doc = schema(schema_name)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert doc["$id"].endswith(SCHEMA_FILES[schema_name])
    for key in ("$id", "title", "description"):
        assert doc.get(key), f"{schema_name} schema is missing {key}"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_every_object_is_closed(schema_name: str) -> None:
    open_objects: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                open_objects.append(path or "<root>")
            for key, value in node.items():
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(schema(schema_name), "")
    assert not open_objects, f"objects missing additionalProperties=false: {open_objects}"


def test_every_action_type_fixes_its_params() -> None:
    """`params` is closed only through the per-action_type branches, so each needs one."""
    action = schema("solution")["properties"]["diagnosis"]["properties"]["suggested_relaxation"][
        "properties"
    ]["action"]
    branches = Counter(
        branch["if"]["properties"]["action_type"]["const"] for branch in action["allOf"]
    )
    assert branches == Counter(action_type_enum())
    defs = schema("solution")["$defs"]
    for action_type in action_type_enum():
        params = defs[f"params_{action_type.lower()}"]
        assert params["type"] == "object" and params["additionalProperties"] is False


# --------------------------------------------------------------------------
# 2. the committed examples validate
# --------------------------------------------------------------------------


@pytest.mark.parametrize("filename,schema_name", sorted(EXAMPLE_FILES.items()))
def test_example_validates(filename: str, schema_name: str) -> None:
    assert_valid(schema_name, example(filename))


@pytest.mark.parametrize("filename,schema_name", sorted(EXAMPLE_FILES.items()))
def test_example_declares_matching_schema_version(filename: str, schema_name: str) -> None:
    expected = schema(schema_name)["properties"]["schema_version"]["const"]
    assert example(filename)["schema_version"] == expected


def test_examples_show_what_the_task_asked_for() -> None:
    """One not-evaluated rule; a MUS with slots, a typed verified action; an ambiguous initial."""
    quality = example(SOLVED)["quality"]
    assert [e["status"] for e in quality["breakdown"]].count("not_evaluated") == 1

    diagnosis = example(INFEASIBLE)["diagnosis"]
    assert diagnosis["method"] == "mus"
    assert diagnosis["partial_placement"] and diagnosis["unplaced_session_ids"]
    assert any(entry["slots"] for entry in diagnosis["minimal_conflicting_set"])
    assert diagnosis["suggested_relaxation"]["action"]["action_type"] != "MANUAL"
    assert diagnosis["suggested_relaxation"]["verification"]["status"] != "not_attempted"

    assert any(row["is_ambiguous"] for row in example(INGESTION)["faculty_initials"])


# --------------------------------------------------------------------------
# 3. malformed variants are rejected
# --------------------------------------------------------------------------


def _faculty_regains_initials(payload: Any) -> Any:
    payload["faculty"][0]["initials"] = "SK"
    return payload


def _unknown_anomaly_code(payload: Any) -> Any:
    payload["anomalies"][0]["code"] = "INITIALS_LOOKED_ODD"
    return payload


def _legend_row_without_division(payload: Any) -> Any:
    payload["faculty_initials"][0]["division_id"] = None
    return payload


def _legend_row_without_legend_ref(payload: Any) -> Any:
    payload["faculty_initials"][0]["legend_ref"] = None
    return payload


def _manual_row_with_legend_ref(payload: Any) -> Any:
    payload["faculty_initials"][0]["source"] = "manual"
    return payload


def _rules_version_missing(payload: Any) -> Any:
    del payload["quality"]["rules_version"]
    return payload


def _not_evaluated_ids_missing(payload: Any) -> Any:
    del payload["quality"]["not_evaluated_rule_ids"]
    return payload


def _not_evaluated_scored_as_zero(payload: Any) -> Any:
    entry = next(e for e in payload["quality"]["breakdown"] if e["status"] == "not_evaluated")
    entry["penalty"] = 0
    return payload


def _not_evaluated_without_reason(payload: Any) -> Any:
    entry = next(e for e in payload["quality"]["breakdown"] if e["status"] == "not_evaluated")
    del entry["reason"]
    return payload


def _evaluated_with_reason(payload: Any) -> Any:
    entry = next(e for e in payload["quality"]["breakdown"] if e["status"] == "evaluated")
    entry["reason"] = "should not be here"
    return payload


def _evaluated_without_penalty(payload: Any) -> Any:
    entry = next(e for e in payload["quality"]["breakdown"] if e["status"] == "evaluated")
    del entry["penalty"]
    return payload


def _breakdown_without_weight(payload: Any) -> Any:
    del payload["quality"]["breakdown"][-1]["weight"]
    return payload


def _unknown_rule_status(payload: Any) -> Any:
    payload["quality"]["breakdown"][0]["status"] = "skipped"
    return payload


def _conflict_entry_without_slots(payload: Any) -> Any:
    del payload["diagnosis"]["minimal_conflicting_set"][0]["slots"]
    return payload


def _method_missing(payload: Any) -> Any:
    del payload["diagnosis"]["method"]
    return payload


def _unknown_method(payload: Any) -> Any:
    payload["diagnosis"]["method"] = "heuristic"
    return payload


def _partial_placement_missing(payload: Any) -> Any:
    del payload["diagnosis"]["partial_placement"]
    return payload


def _nothing_unplaced(payload: Any) -> Any:
    payload["diagnosis"]["unplaced_session_ids"] = []
    return payload


def _mus_without_relaxation(payload: Any) -> Any:
    del payload["diagnosis"]["suggested_relaxation"]
    return payload


def _mus_with_empty_set(payload: Any) -> Any:
    payload["diagnosis"]["minimal_conflicting_set"] = []
    return payload


def _exhaustion_keeping_the_set(payload: Any) -> Any:
    payload["diagnosis"]["method"] = "search_exhaustion"
    del payload["diagnosis"]["suggested_relaxation"]
    return payload


def _exhaustion_keeping_the_relaxation(payload: Any) -> Any:
    payload["diagnosis"]["method"] = "search_exhaustion"
    payload["diagnosis"]["minimal_conflicting_set"] = []
    return payload


def _relaxation_without_action(payload: Any) -> Any:
    del payload["diagnosis"]["suggested_relaxation"]["action"]
    return payload


def _relaxation_without_verification(payload: Any) -> Any:
    del payload["diagnosis"]["suggested_relaxation"]["verification"]
    return payload


def _verification_as_boolean(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["verification"] = True
    return payload


def _unknown_action_type(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["action"]["action_type"] = "REASSIGN_ROOM"
    return payload


def _reclassify_without_is_lab(payload: Any) -> Any:
    del payload["diagnosis"]["suggested_relaxation"]["action"]["params"]["is_lab"]
    return payload


def _params_of_another_action(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["action"]["params"] = {"session_id": "sess-0001"}
    return payload


def _automatic_action_not_attempted(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["verification"] = {
        "status": "not_attempted",
        "runtime_ms": None,
    }
    return payload


def _manual_action_claimed_verified(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["action"] = {"action_type": "MANUAL", "params": {}}
    return payload


def _verified_without_runtime(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["verification"]["runtime_ms"] = None
    return payload


def _lunch_pin_without_cohorts(payload: Any) -> Any:
    del payload["pinned_occupancy"][0]["cohort_ids"]
    return payload


def _slot_ref_with_extra_field(payload: Any) -> Any:
    payload["diagnosis"]["minimal_conflicting_set"][1]["slots"][0]["label"] = "Mon 10.00"
    return payload


MALFORMED: list[tuple[str, str, Mutator]] = [
    ("ingestion:faculty-regains-initials", INGESTION, _faculty_regains_initials),
    ("ingestion:unknown-anomaly-code", INGESTION, _unknown_anomaly_code),
    ("ingestion:legend-row-without-division", INGESTION, _legend_row_without_division),
    ("ingestion:legend-row-without-legend-ref", INGESTION, _legend_row_without_legend_ref),
    ("ingestion:manual-row-with-legend-ref", INGESTION, _manual_row_with_legend_ref),
    ("solved:rules-version-missing", SOLVED, _rules_version_missing),
    ("solved:not-evaluated-ids-missing", SOLVED, _not_evaluated_ids_missing),
    ("solved:not-evaluated-scored-as-zero", SOLVED, _not_evaluated_scored_as_zero),
    ("solved:not-evaluated-without-reason", SOLVED, _not_evaluated_without_reason),
    ("solved:evaluated-with-reason", SOLVED, _evaluated_with_reason),
    ("solved:evaluated-without-penalty", SOLVED, _evaluated_without_penalty),
    ("solved:breakdown-without-weight", SOLVED, _breakdown_without_weight),
    ("solved:unknown-rule-status", SOLVED, _unknown_rule_status),
    ("infeasible:conflict-entry-without-slots", INFEASIBLE, _conflict_entry_without_slots),
    ("infeasible:method-missing", INFEASIBLE, _method_missing),
    ("infeasible:unknown-method", INFEASIBLE, _unknown_method),
    ("infeasible:partial-placement-missing", INFEASIBLE, _partial_placement_missing),
    ("infeasible:nothing-unplaced", INFEASIBLE, _nothing_unplaced),
    ("infeasible:mus-without-relaxation", INFEASIBLE, _mus_without_relaxation),
    ("infeasible:mus-with-empty-set", INFEASIBLE, _mus_with_empty_set),
    ("infeasible:exhaustion-keeping-the-set", INFEASIBLE, _exhaustion_keeping_the_set),
    (
        "infeasible:exhaustion-keeping-the-relaxation",
        INFEASIBLE,
        _exhaustion_keeping_the_relaxation,
    ),
    ("infeasible:relaxation-without-action", INFEASIBLE, _relaxation_without_action),
    ("infeasible:relaxation-without-verification", INFEASIBLE, _relaxation_without_verification),
    ("infeasible:verification-as-boolean", INFEASIBLE, _verification_as_boolean),
    ("infeasible:unknown-action-type", INFEASIBLE, _unknown_action_type),
    ("infeasible:reclassify-without-is-lab", INFEASIBLE, _reclassify_without_is_lab),
    ("infeasible:params-of-another-action", INFEASIBLE, _params_of_another_action),
    ("infeasible:automatic-action-not-attempted", INFEASIBLE, _automatic_action_not_attempted),
    ("infeasible:manual-action-claimed-verified", INFEASIBLE, _manual_action_claimed_verified),
    ("infeasible:verified-without-runtime", INFEASIBLE, _verified_without_runtime),
    ("infeasible:slot-ref-with-extra-field", INFEASIBLE, _slot_ref_with_extra_field),
    ("d6-grid:lunch-pin-without-cohorts", D6_GRID, _lunch_pin_without_cohorts),
]


@pytest.mark.parametrize("case_id,filename,mutate", MALFORMED, ids=[c[0] for c in MALFORMED])
def test_malformed_variant_is_rejected(case_id: str, filename: str, mutate: Mutator) -> None:
    assert_rejected(EXAMPLE_FILES[filename], mutate(example(filename)))


def test_every_example_has_a_malformed_variant() -> None:
    assert {case[1] for case in MALFORMED} == set(EXAMPLE_FILES)


# --------------------------------------------------------------------------
# 4. closed enums, retired kinds, the infeasible branch, the method branches
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["NOT_A_KIND", "room_capacity", "DURATION"])
def test_unknown_kind_is_rejected(kind: str) -> None:
    payload = example(INFEASIBLE)
    payload["diagnosis"]["minimal_conflicting_set"][0]["kind"] = kind
    assert_rejected("solution", payload)


@pytest.mark.parametrize("kind", RETIRED_KINDS)
def test_retired_placeholder_kind_is_rejected(kind: str) -> None:
    payload = example(INFEASIBLE)
    payload["diagnosis"]["minimal_conflicting_set"][0]["kind"] = kind
    assert_rejected("solution", payload)
    assert kind not in kind_enum()


@pytest.mark.parametrize("kind", kind_enum())
def test_every_kind_is_accepted(kind: str) -> None:
    payload = example(INFEASIBLE)
    entry = payload["diagnosis"]["minimal_conflicting_set"][0]
    entry["kind"] = kind
    assert_valid("solution", payload)


@pytest.mark.parametrize("field", ["quality", "displaced", "assignment"])
def test_infeasible_carrying_a_timetable_field_is_rejected(field: str) -> None:
    """Change 2: nothing timetable-shaped may ride on an infeasible result."""
    payload = example(INFEASIBLE)
    payload[field] = example(SOLVED)[field]
    assert_rejected("solution", payload)


def test_solved_carrying_a_diagnosis_is_rejected() -> None:
    payload = example(SOLVED)
    payload["diagnosis"] = example(INFEASIBLE)["diagnosis"]
    assert_rejected("solution", payload)


@pytest.mark.parametrize("field", ["assignment", "quality", "displaced"])
def test_solved_missing_a_required_field_is_rejected(field: str) -> None:
    payload = example(SOLVED)
    del payload[field]
    assert_rejected("solution", payload)


def test_honest_search_exhaustion_result_validates() -> None:
    """What today's backtracking fallback must migrate to (proposal 5.3)."""
    payload = example(INFEASIBLE)
    diagnosis = payload["diagnosis"]
    diagnosis["method"] = "search_exhaustion"
    diagnosis["minimal_conflicting_set"] = []
    del diagnosis["suggested_relaxation"]
    assert_valid("solution", payload)


def test_manual_action_not_attempted_validates() -> None:
    payload = example(INFEASIBLE)
    relaxation = payload["diagnosis"]["suggested_relaxation"]
    relaxation["action"] = {"action_type": "MANUAL", "params": {}}
    relaxation["verification"] = {"status": "not_attempted", "runtime_ms": None}
    assert_valid("solution", payload)


def test_manual_action_with_params_is_rejected() -> None:
    payload = example(INFEASIBLE)
    relaxation = payload["diagnosis"]["suggested_relaxation"]
    relaxation["action"] = {"action_type": "MANUAL", "params": {"room_id": "room-605"}}
    relaxation["verification"] = {"status": "not_attempted", "runtime_ms": None}
    assert_rejected("solution", payload)


@pytest.mark.parametrize(
    "action",
    [
        {"action_type": "UNFIX_SLOT", "params": {"session_id": "sess-0008"}},
        {
            "action_type": "RELAX_FACULTY_AVAILABILITY",
            "params": {"faculty_id": "fac-agn", "slots": [{"day": 4, "period": 8}]},
        },
        {
            "action_type": "RELAX_PINNED_BLOCK",
            "params": {
                "slot": {"day": 4, "period": 6},
                "entity_kind": "cohort",
                "entity_id": "coh-div-se-b",
            },
        },
    ],
    ids=lambda action: action["action_type"],
)
def test_each_automatic_action_shape_validates(action: dict[str, Any]) -> None:
    payload = example(INFEASIBLE)
    payload["diagnosis"]["suggested_relaxation"]["action"] = action
    assert_valid("solution", payload)


@pytest.mark.parametrize(
    "action",
    [
        {"action_type": "UNFIX_SLOT", "params": {}},
        {
            "action_type": "RELAX_FACULTY_AVAILABILITY",
            "params": {"faculty_id": "fac-agn", "slots": []},
        },
        {
            "action_type": "RELAX_PINNED_BLOCK",
            "params": {"slot": {"day": 4, "period": 6}, "entity_kind": "subject", "entity_id": "x"},
        },
    ],
    ids=lambda action: action["action_type"],
)
def test_each_automatic_action_rejects_bad_params(action: dict[str, Any]) -> None:
    payload = example(INFEASIBLE)
    payload["diagnosis"]["suggested_relaxation"]["action"] = action
    assert_rejected("solution", payload)


# --------------------------------------------------------------------------
# 5. ingestion.v2: exactly one faculty-resolution state per observed session
# --------------------------------------------------------------------------


def _session(**overrides: Any) -> dict[str, Any]:
    """A minimal observed session, test-only ids; overrides set the resolution state."""
    session = {
        "id": "obs-t1",
        "subject_id": "subj-t1",
        "faculty_initials_raw": "SK",
        "faculty_id": "fac-swapnali-kurhade",
        "cohort_id": "coh-t1",
        "room_id": None,
        "sub_room_id": None,
        "day": 0,
        "period": 0,
        "duration_periods": 1,
        "session_type": "theory",
        "source_cell": "TEST / SK",
    }
    session.update(overrides)
    return {k: v for k, v in session.items() if v is not ...}


def _with_session(session: dict[str, Any]) -> dict[str, Any]:
    payload = example(INGESTION)
    payload["observed_sessions"] = [session]
    return payload


CANDIDATES = ["fac-swapnali-kurhade", "fac-suhas-kakade"]

SESSION_STATES = [
    ("resolved", _session(), True),
    ("resolved-faculty-page", _session(faculty_initials_raw=None), True),
    ("ambiguous", _session(faculty_id=None, faculty_candidates=CANDIDATES), True),
    ("unresolved", _session(faculty_id=None), True),
    ("resolved-and-candidates", _session(faculty_candidates=CANDIDATES), False),
    ("one-candidate", _session(faculty_id=None, faculty_candidates=CANDIDATES[:1]), False),
    (
        "duplicate-candidates",
        _session(faculty_id=None, faculty_candidates=[CANDIDATES[0]] * 2),
        False,
    ),
    (
        "ambiguous-without-initials",
        _session(faculty_id=None, faculty_initials_raw=None, faculty_candidates=CANDIDATES),
        False,
    ),
    ("unresolved-without-initials", _session(faculty_id=None, faculty_initials_raw=None), False),
    ("initials-raw-missing", _session(faculty_initials_raw=...), False),
    ("faculty-id-missing", _session(faculty_id=...), False),
]


@pytest.mark.parametrize(
    "case_id,session,valid", SESSION_STATES, ids=[s[0] for s in SESSION_STATES]
)
def test_observed_session_resolution_state(
    case_id: str, session: dict[str, Any], valid: bool
) -> None:
    assert is_valid("ingestion", _with_session(session)) is valid


# --------------------------------------------------------------------------
# 6. cross-field rules JSON Schema cannot state
# --------------------------------------------------------------------------


def ingestion_cross_field_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = payload["faculty_initials"]
    keys = Counter((row["initials"], row["division_id"]) for row in rows)
    for row in rows:
        duplicated = keys[(row["initials"], row["division_id"])] > 1
        if row["is_ambiguous"] != duplicated:
            errors.append(f"is_ambiguous wrong for {row['faculty_id']} / {row['initials']}")
    faculty_ids = {f["id"] for f in payload["faculty"]}
    division_ids = {d["id"] for d in payload["divisions"]}
    for row in rows:
        if row["faculty_id"] not in faculty_ids:
            errors.append(f"unknown faculty {row['faculty_id']}")
        if row["division_id"] is not None and row["division_id"] not in division_ids:
            errors.append(f"unknown division {row['division_id']}")
    flagged = {(a["code"], a["source_cell"]) for a in payload["anomalies"]}
    for session in payload["observed_sessions"]:
        if "faculty_candidates" in session:
            code = "AMBIGUOUS_FACULTY_INITIALS"
        elif session["faculty_id"] is None:
            code = "UNRESOLVED_FACULTY_INITIALS"
        else:
            continue
        if (code, session["source_cell"]) not in flagged:
            errors.append(f"{session['id']} has no {code} anomaly")
    return errors


def test_ingestion_example_cross_field_rules() -> None:
    assert ingestion_cross_field_errors(example(INGESTION)) == []


def test_ingestion_cross_field_rules_catch_a_wrong_flag_and_a_missing_anomaly() -> None:
    payload = example(INGESTION)
    payload["faculty_initials"][0]["is_ambiguous"] = False
    payload["observed_sessions"] = [_session(faculty_id=None, faculty_candidates=CANDIDATES)]
    errors = ingestion_cross_field_errors(payload)
    assert any("is_ambiguous" in e for e in errors)
    assert any("AMBIGUOUS_FACULTY_INITIALS" in e for e in errors)


def test_partial_placement_agrees_with_metadata() -> None:
    """Proposal 2.4: partial and unplaced partition the sessions; counts match metadata."""
    payload = example(INFEASIBLE)
    placed = [p["session_id"] for p in payload["diagnosis"]["partial_placement"]]
    unplaced = payload["diagnosis"]["unplaced_session_ids"]
    assert len(placed) == len(set(placed))
    assert not set(placed) & set(unplaced)
    assert len(placed) == payload["metadata"]["sessions_assigned"]
    assert len(placed) + len(unplaced) == payload["metadata"]["sessions_total"]


def test_relaxation_names_a_constraint_in_the_set() -> None:
    diagnosis = example(INFEASIBLE)["diagnosis"]
    ids = {entry["constraint_id"] for entry in diagnosis["minimal_conflicting_set"]}
    assert diagnosis["suggested_relaxation"]["constraint_id"] in ids


def test_quality_breakdown_agrees_with_not_evaluated_ids() -> None:
    """Proposal 6: unique rule ids; not_evaluated_rule_ids mirrors the breakdown."""
    quality = example(SOLVED)["quality"]
    rule_ids = [entry["rule_id"] for entry in quality["breakdown"]]
    assert len(rule_ids) == len(set(rule_ids))
    not_evaluated = {e["rule_id"] for e in quality["breakdown"] if e["status"] == "not_evaluated"}
    assert set(quality["not_evaluated_rule_ids"]) == not_evaluated


# --------------------------------------------------------------------------
# 7. the kind -> action map (proposal 8.3)
# --------------------------------------------------------------------------


def test_relaxation_map_keys_equal_the_kind_enum() -> None:
    assert sorted(relaxation_map()) == sorted(kind_enum())


def test_relaxation_map_values_are_legal_and_include_manual() -> None:
    actions = set(action_type_enum())
    for kind, permitted in relaxation_map().items():
        assert set(permitted) <= actions, kind
        assert "MANUAL" in permitted, kind
        assert len(permitted) == len(set(permitted)), kind


def test_every_automatic_action_relaxes_some_kind() -> None:
    used = {a for permitted in relaxation_map().values() for a in permitted}
    assert set(action_type_enum()) - {"MANUAL"} <= used


def test_example_relaxation_is_permitted_for_its_kind() -> None:
    diagnosis = example(INFEASIBLE)["diagnosis"]
    relaxation = diagnosis["suggested_relaxation"]
    kind = next(
        entry["kind"]
        for entry in diagnosis["minimal_conflicting_set"]
        if entry["constraint_id"] == relaxation["constraint_id"]
    )
    assert relaxation["action"]["action_type"] in relaxation_map()[kind]


# --------------------------------------------------------------------------
# 7. proposal row 8: wall-clock period axis 0..9 and per-year lunch (ROADMAP D6)
# --------------------------------------------------------------------------

# ROADMAP section 5 / row 8 assessment: only P2 is closed for everyone; [4, 6] would span SE lunch.
D6_TEACHING_PERIODS = [0, 1, 3, 4, 5, 6, 7, 8, 9]
D6_ADJACENCY = [[0, 1], [1, 3], [3, 4], [4, 5], [5, 6], [6, 7], [7, 8], [8, 9]]
SE_LUNCH, TE_LUNCH, COFFEE = 5, 4, 2


def test_every_ingestion_period_field_is_on_the_wall_clock_axis() -> None:
    doc = schema("ingestion")
    props = doc["properties"]
    refs = [
        props["observed_sessions"]["items"]["properties"]["period"]["$ref"],
        props["lab_blocks"]["items"]["properties"]["start_period"]["$ref"],
        props["pinned_blocks"]["items"]["properties"]["period"]["$ref"],
    ]
    assert refs == ["#/$defs/period"] * 3
    assert "teaching_period" not in doc["$defs"]
    period = doc["$defs"]["period"]
    assert (period["minimum"], period["maximum"]) == (0, 9)


@pytest.mark.parametrize(("period", "valid"), [(0, True), (5, True), (9, True), (10, False)])
def test_observed_session_period_range(period: int, valid: bool) -> None:
    """P5 (13:15-14:15) is a TE teaching hour; it had no index on the old 0..7 axis."""
    session = _session(cohort_id="coh-te-t1", period=period, source_cell="TEST / SK / 13.15")
    assert is_valid("ingestion", _with_session(session)) is valid


@pytest.mark.parametrize(("start", "valid"), [(1, True), (8, True), (10, False)])
def test_lab_block_start_period_range(start: int, valid: bool) -> None:
    payload = example(INGESTION)
    payload["lab_blocks"] = [
        {
            "id": "lab-t1",
            "division_id": "div-be-comp-ab",
            "day": 0,
            "start_period": start,
            "duration_periods": 2,
            "parallel_session_ids": [],
        }
    ]
    assert is_valid("ingestion", payload) is valid


def _break(cohort_id: str | None, period: int) -> dict[str, Any]:
    return {
        "id": f"brk-{cohort_id}-{period}",
        "label": "BREAK",
        "cohort_id": cohort_id,
        "day": 0,
        "period": period,
        "duration_periods": 1,
        "kind": "break",
    }


def test_coffee_and_per_year_lunch_are_pinned_breaks() -> None:
    payload = example(INGESTION)
    payload["pinned_blocks"] = [
        _break(None, COFFEE),
        _break("coh-se-t1", SE_LUNCH),
        _break("coh-te-t1", TE_LUNCH),
    ]
    assert_valid("ingestion", payload)


def test_se_session_in_its_lunch_is_not_a_schema_error() -> None:
    """Pins a known limit: a session's year is reached only through cohort -> division ->
    semester_number, a cross-field join JSON Schema cannot express. Rejecting an SE session
    at P5 is a validator rule (S7), not a schema rule."""
    payload = _with_session(_session(cohort_id="coh-se-t1", period=SE_LUNCH))
    payload["pinned_blocks"] = [_break("coh-se-t1", SE_LUNCH)]
    assert is_valid("ingestion", payload)


def test_d6_grid_example_matches_the_row_8_assessment() -> None:
    payload = example(D6_GRID)
    grid = payload["slot_grid"]
    assert (grid["days"], grid["periods_per_day"]) == (5, 10)
    assert grid["teaching_periods"] == D6_TEACHING_PERIODS
    assert grid["adjacency"] == D6_ADJACENCY

    se_cohorts = {"coh-div-se-a", "coh-batch-se-a-a", "coh-batch-se-a-b"}
    lunches = {
        (pin["day"], pin["period"]): set(pin["cohort_ids"]) for pin in payload["pinned_occupancy"]
    }
    for day in range(5):
        assert lunches[(day, SE_LUNCH)] == se_cohorts
        assert lunches[(day, TE_LUNCH)] == {"coh-div-te-a"}
    assert len(lunches) == 10

    sessions = {s["id"]: s for s in payload["sessions"]}
    (block,) = payload["lab_blocks"]
    assert len(block["session_ids"]) == 2
    assert {sessions[i]["cohort_id"] for i in block["session_ids"]} < se_cohorts
    # a TE lecture fixed at P5 is legal: P5 is a teaching period, the TE lunch is P4
    assert sessions["sess-te-a-ce307-l"]["fixed_slot"] == {"day": 0, "period": 5}
