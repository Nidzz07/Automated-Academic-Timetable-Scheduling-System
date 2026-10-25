"""solver.bounds (S12i): lower bounds on the teaching periods a week needs.

The clique bound is checked against networkx's maximum-weight clique (networkx in
tests only) on small random conflict graphs; the real EVEN instance's bounds are
checked against the 40 teaching periods per year (ROADMAP section 5) and against
the cliques every cohort's and teacher's own sessions form.
"""

from __future__ import annotations

import ast
import copy
import json
import random
import sys
from pathlib import Path

import networkx as nx
import pytest

import solver.bounds
from solver.benchmarks.real_repair import INSTANCE
from solver.bounds import lower_bounds
from solver.graph import build_conflict_graph


def _random_edge_list(rng: random.Random, n: int, p: float) -> dict:
    sessions = [{"id": f"s{i:02d}", "subject_id": "subj", "faculty_id": "f", "cohort_id": f"c{i}",
                 "session_type": "theory", "duration_periods": rng.choice((1, 1, 2)),
                 "cohort_size": 20, "requires_lab": False, "fixed_slot": None}
                for i in range(n)]
    edges = [{"u": a["id"], "v": b["id"], "reason": rng.choice(("FACULTY", "COHORT"))}
             for i, a in enumerate(sessions) for b in sessions[i + 1:] if rng.random() < p]
    return {
        "schema_version": "edge_list.v1",
        "slot_grid": {"days": 1, "periods_per_day": 2, "teaching_periods": [0, 1],
                      "adjacency": [[0, 1]]},
        "sessions": sessions, "edges": edges,
        "rooms": [{"id": "r", "code": "R", "capacity": 20, "is_lab": False,
                   "parent_room_id": None}],
        "faculty_availability": [{"faculty_id": "f", "unavailable_slots": []}],
        "lab_blocks": [], "pinned_occupancy": [],
    }


def _networkx_best(edge_list: dict) -> int:
    graph = nx.Graph()
    for s in edge_list["sessions"]:
        graph.add_node(s["id"], weight=s["duration_periods"])
    graph.add_edges_from((e["u"], e["v"]) for e in edge_list["edges"])
    return nx.max_weight_clique(graph, weight="weight")[1]


def _is_clique(edge_list: dict, ids: list[str]) -> bool:
    graph = build_conflict_graph(edge_list)
    return all(b in graph.neighbours(a) for i, a in enumerate(ids) for b in ids[i + 1:])


def test_exact_clique_matches_networkx() -> None:
    for seed in range(60):
        rng = random.Random(seed)
        edge_list = _random_edge_list(rng, rng.randint(1, 18), rng.choice((0.2, 0.5, 0.8)))
        clique = lower_bounds(edge_list)["clique"]
        assert clique["method"] == "exact"
        assert clique["periods"] == _networkx_best(edge_list), seed
        assert _is_clique(edge_list, clique["session_ids"])
        weights = {s["id"]: s["duration_periods"] for s in edge_list["sessions"]}
        assert clique["periods"] == sum(weights[s] for s in clique["session_ids"])


def test_past_the_budget_the_greedy_clique_is_still_a_clique(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(solver.bounds, "EXACT_NODES", 0)
    for seed in range(20):
        rng = random.Random(seed)
        edge_list = _random_edge_list(rng, 15, 0.5)
        clique = lower_bounds(edge_list)["clique"]
        assert clique["method"] == "greedy"
        assert _is_clique(edge_list, clique["session_ids"])
        assert 0 < clique["periods"] <= _networkx_best(edge_list)


def test_deterministic_and_input_untouched() -> None:
    edge_list = _random_edge_list(random.Random(3), 18, 0.5)
    before = copy.deepcopy(edge_list)
    first = lower_bounds(edge_list)
    assert edge_list == before
    shuffled = copy.deepcopy(edge_list)
    random.Random(1).shuffle(shuffled["sessions"])
    random.Random(2).shuffle(shuffled["edges"])
    assert lower_bounds(shuffled) == first == lower_bounds(edge_list)


@pytest.fixture(scope="module")
def real() -> tuple[dict, dict]:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    return edge_list, lower_bounds(edge_list)


def test_real_instance_bounds(real: tuple[dict, dict]) -> None:
    """The clique bound fits the 40 teaching periods per year and is at least every
    cohort's and teacher's own session periods (each set is a clique). The loads count
    pins (a year's lunch among them) and unavailable slots, so they are measured against
    the grid's 45 teaching slots, not the 40 that already leave lunch out."""
    edge_list, bounds = real
    clique = bounds["clique"]
    assert clique["method"] == "exact" and _is_clique(edge_list, clique["session_ids"])
    per_cohort: dict[str, int] = {}
    per_teacher: dict[str, int] = {}
    for s in edge_list["sessions"]:
        per_cohort[s["cohort_id"]] = per_cohort.get(s["cohort_id"], 0) + s["duration_periods"]
        per_teacher[s["faculty_id"]] = per_teacher.get(s["faculty_id"], 0) + s["duration_periods"]
    assert max(per_cohort.values()) <= max(per_teacher.values()) <= clique["periods"] <= 40
    assert bounds["teaching_slots"] == 45
    for load in (bounds["teacher"], bounds["cohort"]):
        assert load["periods"] == load["sessions"] + load["held"] <= bounds["teaching_slots"]
    assert bounds["cohort"]["periods"] >= max(per_cohort.values())


def test_bounds_module_imports_only_the_stdlib_and_solver() -> None:
    assert solver.bounds.__file__ is not None
    tree = ast.parse(Path(solver.bounds.__file__).read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names}
    names |= {node.module for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module}
    tops = {name.split(".")[0] for name in names}
    assert tops <= set(sys.stdlib_module_names) | {"solver"}, tops
