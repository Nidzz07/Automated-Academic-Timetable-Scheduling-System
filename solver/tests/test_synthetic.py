"""Tests for the synthetic instance generator (:mod:`solver.benchmarks.synthetic`).

Every preset must produce an ``edge_list_v1``-valid payload, the same seed must
give byte-identical JSON (in this process and in a fresh interpreter with a
different hash seed), and the generated structure must match what the config
asks for. The infeasible preset is checked by its pigeonhole certificate, not
by running the solver on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from functools import cache
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from solver.benchmarks.synthetic import PRESETS, division_demand, generate, to_json
from solver.graph import build_conflict_graph
from solver.slots import SLOT_COUNT, TEACHING_PERIODS

REPO = Path(__file__).resolve().parents[2]
SEEDS = (1, 2, 20261006)


@cache
def _edge_list_validator() -> Draft202012Validator:
    schema = json.loads((REPO / "contracts" / "edge_list_v1.schema.json").read_text("utf-8"))
    return Draft202012Validator(schema)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_is_edge_list_v1_valid(preset: str, seed: int) -> None:
    edge_list = generate(PRESETS[preset], seed)
    _edge_list_validator().validate(edge_list)
    build_conflict_graph(edge_list)  # referential integrity, block declarations


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_same_seed_is_byte_identical(preset: str) -> None:
    assert to_json(generate(PRESETS[preset], 7)) == to_json(generate(PRESETS[preset], 7))


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_different_seeds_differ(preset: str) -> None:
    assert to_json(generate(PRESETS[preset], 1)) != to_json(generate(PRESETS[preset], 2))


def test_byte_identical_across_interpreters_and_hash_seeds() -> None:
    """A fresh interpreter with another PYTHONHASHSEED gives the same bytes -
    so nothing depends on set or dict iteration order."""
    code = (
        "import hashlib, sys\n"
        "from solver.benchmarks.synthetic import PRESETS, generate, to_json\n"
        "sys.stdout.write(hashlib.sha256(to_json(generate(PRESETS['large'], 5))"
        ".encode()).hexdigest())\n"
    )
    digests = set()
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True,
            check=True,
        )
        digests.add(out.stdout)
    assert len(digests) == 1


@pytest.mark.parametrize("preset", ["small", "medium", "large"])
def test_structure_matches_the_config(preset: str) -> None:
    config = PRESETS[preset]
    edge_list = generate(config, 1)
    sessions = edge_list["sessions"]

    theory = [s for s in sessions if s["session_type"] == "theory"]
    labs = [s for s in sessions if s["session_type"] == "lab"]
    per_division = config.theory_subjects_per_division * config.hours_per_theory_subject
    assert len(theory) == config.divisions * per_division + config.combined_lectures
    assert len(edge_list["lab_blocks"]) == config.divisions * config.lab_blocks_per_division
    assert len(labs) == len(edge_list["lab_blocks"]) * config.batches_per_division
    assert len(edge_list["faculty_availability"]) == config.faculty
    assert len(edge_list["pinned_occupancy"]) == config.divisions * config.pinned_slots_per_division

    physical = [r for r in edge_list["rooms"] if r["parent_room_id"] is None]
    assert len(physical) == len(config.rooms)
    assert len(edge_list["rooms"]) - len(physical) == sum(len(r.sub_rooms) for r in config.rooms)

    for entry in edge_list["faculty_availability"]:
        assert len(entry["unavailable_slots"]) == config.unavailable_slots_per_faculty
        assert all(s["period"] in TEACHING_PERIODS for s in entry["unavailable_slots"])


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_lab_blocks_are_well_formed(preset: str) -> None:
    edge_list = generate(PRESETS[preset], 1)
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    for block in edge_list["lab_blocks"]:
        members = [sessions[sid] for sid in block["session_ids"]]
        assert block["must_be_contiguous"] is True
        assert all(m["requires_lab"] and m["duration_periods"] == block["duration_periods"]
                   for m in members)
        # A shared teacher would make the block unplaceable by construction.
        assert len({m["faculty_id"] for m in members}) == len(members)
        assert len({m["cohort_id"] for m in members}) == len(members)


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_edges_match_their_reasons(preset: str) -> None:
    """FACULTY edges join same-teacher sessions, every same-teacher pair has one,
    and a batch session conflicts with its own division's lectures."""
    edge_list = generate(PRESETS[preset], 1)
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    faculty_pairs = {
        frozenset((e["u"], e["v"])) for e in edge_list["edges"] if e["reason"] == "FACULTY"
    }
    cohort_pairs = {
        frozenset((e["u"], e["v"])) for e in edge_list["edges"] if e["reason"] == "COHORT"
    }
    ids = sorted(sessions)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            same_teacher = sessions[a]["faculty_id"] == sessions[b]["faculty_id"]
            assert (frozenset((a, b)) in faculty_pairs) == same_teacher
            ca, cb = sessions[a]["cohort_id"], sessions[b]["cohort_id"]
            if ca == cb or cb.startswith(f"{ca}-b") or ca.startswith(f"{cb}-b"):
                assert frozenset((a, b)) in cohort_pairs, (ca, cb)
    reasons = Counter(e["reason"] for e in edge_list["edges"])
    assert reasons["FACULTY"] > 0 and reasons["COHORT"] > 0


def test_infeasible_preset_carries_a_pigeonhole_certificate() -> None:
    """Division d00 must be taught one period more than it has free."""
    for seed in SEEDS:
        demand, free = division_demand(generate(PRESETS["infeasible"], seed), "d00")
        assert demand == free + 1
        assert free <= SLOT_COUNT


@pytest.mark.parametrize("preset", ["small", "medium", "large"])
def test_feasible_presets_have_no_pigeonhole_division(preset: str) -> None:
    """Not a feasibility proof - only that no division is over-subscribed."""
    config = PRESETS[preset]
    edge_list = generate(config, 1)
    for k in range(config.divisions):
        demand, free = division_demand(edge_list, f"d{k:02d}")
        assert demand <= free, (k, demand, free)


def test_benchmarks_package_imports_only_stdlib_and_solver() -> None:
    """solver/ purity (CONTEXT.md rules 2 and 3) holds for the benchmark tooling too."""
    import ast

    for path in sorted((REPO / "solver" / "benchmarks").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                assert root == "solver" or root in sys.stdlib_module_names, (path.name, root)


def test_large_preset_size() -> None:
    """Synthetic, not SPIT data: the counts are chosen to match CONTEXT.md 3.1
    (10 divisions, 4 batches each, 41 faculty, 20 physical rooms, roughly
    180-250 sessions); only the rooms are copied from classrooms.xlsx."""
    config = PRESETS["large"]
    edge_list = generate(config, 1)
    assert config.divisions == 10
    assert config.batches_per_division == 4
    assert config.faculty == 41
    assert len(config.rooms) == 20
    assert 180 <= len(edge_list["sessions"]) <= 250
