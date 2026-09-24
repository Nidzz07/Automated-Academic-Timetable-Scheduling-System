"""Validation tests for the three frozen contracts in ``contracts/``.

These are the only tests that guard the coupling points between the three tracks
(CONTEXT.md section 5). They check three things, in increasing strictness:

1. each schema is itself a legal JSON Schema draft 2020-12 document;
2. each committed example validates against its schema;
3. a deliberately malformed variant of each example is *rejected*.

Point 3 is the one that carries weight. A schema that accepts anything passes a
success-only suite, so every example is paired with a mutation that must fail.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"

SCHEMA_FILES = {
    "ingestion": "ingestion_v1.schema.json",
    "edge_list": "edge_list_v1.schema.json",
    "solution": "solution_v1.schema.json",
}

INGESTION = "ingestion_v1.example.json"
EDGE_LIST = "edge_list_v1.example.json"
SOLVED = "solution_v1.solved.example.json"
INFEASIBLE = "solution_v1.infeasible.example.json"

# example file -> the schema it must validate against
EXAMPLE_FILES = {
    INGESTION: "ingestion",
    EDGE_LIST: "edge_list",
    SOLVED: "solution",
    INFEASIBLE: "solution",
}

Mutator = Callable[[Any], Any]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def schema(name: str) -> dict[str, Any]:
    return load_json(CONTRACTS_DIR / SCHEMA_FILES[name])


def example(filename: str) -> Any:
    return load_json(EXAMPLES_DIR / filename)


def assert_rejected(schema_name: str, payload: Any) -> ValidationError:
    """Assert the payload fails validation, and hand back the error."""
    validator = Draft202012Validator(schema(schema_name))
    errors = sorted(validator.iter_errors(payload), key=str)
    assert errors, "payload was expected to be rejected but validated cleanly"
    return errors[0]


# --------------------------------------------------------------------------
# 1. the schemas are legal JSON Schema documents
# --------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_schema_is_a_valid_json_schema(schema_name: str) -> None:
    Draft202012Validator.check_schema(schema(schema_name))


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_schema_declares_its_identity(schema_name: str) -> None:
    """$id, title and description are part of the contract's documentation."""
    doc = schema(schema_name)
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    for key in ("$id", "title", "description"):
        assert doc.get(key), f"{schema_name} schema is missing {key}"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_FILES))
def test_every_object_is_closed(schema_name: str) -> None:
    """No object anywhere in a contract may accept unlisted properties.

    An open object would let a producer smuggle a field past the contract and
    the consumer would never learn of it until runtime.
    """
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


# --------------------------------------------------------------------------
# 2. the committed examples validate
# --------------------------------------------------------------------------


@pytest.mark.parametrize("filename,schema_name", sorted(EXAMPLE_FILES.items()))
def test_example_validates(filename: str, schema_name: str) -> None:
    Draft202012Validator(schema(schema_name)).validate(example(filename))


@pytest.mark.parametrize("filename,schema_name", sorted(EXAMPLE_FILES.items()))
def test_example_declares_matching_schema_version(filename: str, schema_name: str) -> None:
    expected = schema(schema_name)["properties"]["schema_version"]["const"]
    assert example(filename)["schema_version"] == expected


# --------------------------------------------------------------------------
# 3. malformed variants are rejected
# --------------------------------------------------------------------------


def _drop_semester_code(payload: Any) -> Any:
    del payload["semester"]["code"]
    return payload


def _invent_a_room_field(payload: Any) -> Any:
    payload["rooms"][0]["floor"] = 7
    return payload


def _unknown_anomaly_code(payload: Any) -> Any:
    payload["anomalies"][0]["code"] = "ROOM_LOOKED_ODD"
    return payload


def _day_out_of_range(payload: Any) -> Any:
    payload["observed_sessions"][0]["day"] = 5
    return payload


def _adjacency_triple(payload: Any) -> Any:
    payload["slot_grid"]["adjacency"].append([0, 1, 3])
    return payload


def _capacity_as_string(payload: Any) -> Any:
    payload["rooms"][0]["capacity"] = "80"
    return payload


def _lab_block_not_contiguous(payload: Any) -> Any:
    payload["lab_blocks"][0]["must_be_contiguous"] = False
    return payload


def _breakdown_without_explanation(payload: Any) -> Any:
    del payload["quality"]["breakdown"][0]["explanation"]
    return payload


def _metadata_without_backtracks(payload: Any) -> Any:
    del payload["metadata"]["backtracks"]
    return payload


def _unknown_status(payload: Any) -> Any:
    payload["status"] = "partial"
    return payload


def _diagnosis_without_relaxation(payload: Any) -> Any:
    del payload["diagnosis"]["suggested_relaxation"]
    return payload


def _relaxation_with_internal_id_only(payload: Any) -> Any:
    payload["diagnosis"]["suggested_relaxation"]["description"] = ""
    return payload


MALFORMED: list[tuple[str, str, Mutator]] = [
    # case id, source example, mutation (the schema comes from EXAMPLE_FILES)
    ("ingestion:semester-code-missing", INGESTION, _drop_semester_code),
    ("ingestion:unlisted-room-field", INGESTION, _invent_a_room_field),
    ("ingestion:unknown-anomaly-code", INGESTION, _unknown_anomaly_code),
    ("ingestion:day-out-of-range", INGESTION, _day_out_of_range),
    ("edge_list:adjacency-triple", EDGE_LIST, _adjacency_triple),
    ("edge_list:capacity-as-string", EDGE_LIST, _capacity_as_string),
    ("edge_list:lab-block-not-contiguous", EDGE_LIST, _lab_block_not_contiguous),
    ("solution:breakdown-without-explanation", SOLVED, _breakdown_without_explanation),
    ("solution:metadata-without-backtracks", SOLVED, _metadata_without_backtracks),
    ("solution:unknown-status", SOLVED, _unknown_status),
    ("solution:diagnosis-without-relaxation", INFEASIBLE, _diagnosis_without_relaxation),
    ("solution:empty-relaxation-description", INFEASIBLE, _relaxation_with_internal_id_only),
]


@pytest.mark.parametrize(
    "case_id,filename,mutate",
    MALFORMED,
    ids=[case[0] for case in MALFORMED],
)
def test_malformed_variant_is_rejected(case_id: str, filename: str, mutate: Mutator) -> None:
    payload = mutate(copy.deepcopy(example(filename)))
    assert_rejected(EXAMPLE_FILES[filename], payload)


def test_every_example_has_a_malformed_variant() -> None:
    """Each example must be paired with at least one rejection case."""
    covered = {case[1] for case in MALFORMED}
    assert covered == set(EXAMPLE_FILES)


# --------------------------------------------------------------------------
# contract-specific rules called out in the handoff
# --------------------------------------------------------------------------


def test_edge_without_reason_is_rejected() -> None:
    """`reason` is what lets infeasibility diagnosis name *why* two sessions clash."""
    payload = copy.deepcopy(example("edge_list_v1.example.json"))
    del payload["edges"][0]["reason"]
    error = assert_rejected("edge_list", payload)
    assert "reason" in str(error.message)


def test_edge_with_unknown_reason_is_rejected() -> None:
    payload = copy.deepcopy(example("edge_list_v1.example.json"))
    payload["edges"][0]["reason"] = "TIMETABLE"
    assert_rejected("edge_list", payload)


def test_every_edge_reason_is_present_in_the_example() -> None:
    """The example exercises all three conflict reasons, so consumers see each."""
    payload = example("edge_list_v1.example.json")
    reasons = {edge["reason"] for edge in payload["edges"]}
    assert reasons == {"FACULTY", "ROOM", "COHORT"}


def test_solved_without_assignment_is_rejected() -> None:
    payload = copy.deepcopy(example("solution_v1.solved.example.json"))
    del payload["assignment"]
    assert_rejected("solution", payload)


def test_solved_without_quality_is_rejected() -> None:
    payload = copy.deepcopy(example("solution_v1.solved.example.json"))
    del payload["quality"]
    assert_rejected("solution", payload)


def test_solved_carrying_a_diagnosis_is_rejected() -> None:
    """Exactly one of assignment / diagnosis may be present."""
    solved = copy.deepcopy(example("solution_v1.solved.example.json"))
    infeasible = example("solution_v1.infeasible.example.json")
    solved["diagnosis"] = infeasible["diagnosis"]
    assert_rejected("solution", solved)


def test_infeasible_without_diagnosis_is_rejected() -> None:
    payload = copy.deepcopy(example("solution_v1.infeasible.example.json"))
    del payload["diagnosis"]
    assert_rejected("solution", payload)


def test_infeasible_carrying_an_assignment_is_rejected() -> None:
    infeasible = copy.deepcopy(example("solution_v1.infeasible.example.json"))
    solved = example("solution_v1.solved.example.json")
    infeasible["assignment"] = solved["assignment"]
    assert_rejected("solution", infeasible)


def test_solved_example_has_two_rules_firing() -> None:
    """The worked example must show a real breakdown, not a bare score."""
    quality = example("solution_v1.solved.example.json")["quality"]
    fired = [rule for rule in quality["breakdown"] if rule["penalty"] != 0]
    assert len(fired) == 2
    assert all(rule["explanation"].strip() for rule in fired)


def test_edge_list_example_covers_the_hard_structures() -> None:
    """The four structures the solver has to get right, in one payload."""
    payload = example("edge_list_v1.example.json")

    # a four-batch parallel lab block
    block = payload["lab_blocks"][0]
    assert len(block["session_ids"]) == 4
    assert block["must_be_contiguous"] is True

    # a combined-division lecture (SE C & D)
    assert any(
        session["cohort_id"] == "coh-comb-se-cd" for session in payload["sessions"]
    )

    # a sub-room pair sharing one parent room
    parents = [
        room["parent_room_id"] for room in payload["rooms"] if room["parent_room_id"]
    ]
    assert any(parents.count(parent) >= 2 for parent in parents)

    # at least one pinned block
    assert payload["pinned_occupancy"]


def test_lab_block_duration_spans_the_short_break() -> None:
    """Adjacency is computed in teaching order, which is how a 10.00-12.00 lab works."""
    grid = example("edge_list_v1.example.json")["slot_grid"]
    adjacency = {tuple(pair) for pair in grid["adjacency"]}
    assert (1, 3) in adjacency, "period 1 and period 3 straddle the 11.00 short break"
    assert 2 not in grid["teaching_periods"]
