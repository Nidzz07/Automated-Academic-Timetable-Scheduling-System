"""Tests for :mod:`solver.scoring` (S10): the rule file, each rule, determinism.

Scoring is a pure function of an edge list and start slots, so every case writes
its timetable down directly instead of solving it, and every expected number is
counted by hand in the docstring.
"""

from __future__ import annotations

import ast
import copy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from solver.backtracking import backtrack_solve
from solver.benchmarks.synthetic import PRESETS, generate
from solver.graph import build_conflict_graph
from solver.scoring import RULES_FILE, load_rules, score
from solver.slots import SlotId, all_slots
from solver.tests.test_backtracking import _edge, _payload, _session
from solver.tests.test_d6_grid import _d6
from solver.tests.test_solution_v2 import D34, assert_quality_block

REPO = Path(__file__).resolve().parents[2]


def _rule(edge_list: dict[str, Any], starts: dict[str, tuple[int, int]], rule_id: str
          ) -> dict[str, Any]:
    quality = score(edge_list, {sid: SlotId(*slot) for sid, slot in starts.items()})
    assert_quality_block(quality)
    return next(e for e in quality["breakdown"] if e["rule_id"] == rule_id)


def _pin(day: int, period: int, *, faculty: tuple[str, ...] = (), rooms: tuple[str, ...] = (),
         cohorts: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"day": day, "period": period, "faculty_ids": list(faculty),
            "room_ids": list(rooms), "cohort_ids": list(cohorts)}


def _lab(sid: str, faculty: str, cohort: str) -> dict[str, Any]:
    return _session(sid, faculty, cohort, duration=2, requires_lab=True, session_type="lab")


# ----------------------------------------------------------------------
# The rule file
# ----------------------------------------------------------------------


def test_rule_file_is_d34_with_s_gap_weighted_most() -> None:
    rules = load_rules()
    assert rules.version == "1"
    assert [r.id for r in rules.rules] == D34
    weights = {r.id: r.weight for r in rules.rules}
    assert weights["S-GAP"] > max(w for rid, w in weights.items() if rid != "S-GAP")  # D13
    assert rules.rules[2].parameters == {"threshold_hours": 16}  # D11


def _first_rule_renamed(data: dict[str, Any]) -> None:
    data["rules"][0]["id"] = "S-IDLE"


BROKEN: list[tuple[str, Callable[[dict[str, Any]], Any], str]] = [
    ("unknown-id", _first_rule_renamed, "unknown quality rule id 'S-IDLE'"),
    ("missing-rule", lambda d: d["rules"].pop(), "exactly once"),
    ("repeated-rule", lambda d: d["rules"].append(dict(d["rules"][0])), "exactly once"),
    ("no-version", lambda d: d.pop("version"), "top level"),
    ("numeric-version", lambda d: d.update(version=1), "version"),
    ("negative-weight", lambda d: d["rules"][1].update(weight=-1), "weight"),
    ("boolean-weight", lambda d: d["rules"][1].update(weight=True), "weight"),
    ("unknown-parameter", lambda d: d["rules"][2]["parameters"].update(days=5), "parameters"),
    ("parameter-on-the-wrong-rule",
     lambda d: d["rules"][0].update(parameters={"threshold_hours": 16}), "parameters"),
    ("unknown-key", lambda d: d["rules"][3].update(rationale="x"), "exactly id, description"),
]


@pytest.mark.parametrize(("case", "mutate", "match"), BROKEN, ids=[c[0] for c in BROKEN])
def test_a_broken_rule_file_fails_loudly(
    tmp_path: Path, case: str, mutate: Callable[[dict[str, Any]], Any], match: str
) -> None:
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "quality_rules.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_rules(path)


# ----------------------------------------------------------------------
# S-GAP (D13)
# ----------------------------------------------------------------------


def test_s_gap_counts_idle_teaching_periods_but_never_a_break() -> None:
    """Canonical grid: classes at P0 and P4 leave P1 and P3 idle; P2 is the coffee break."""
    e = _payload([_session("a", "f1", "c1"), _session("b", "f2", "c1")])
    entry = _rule(e, {"a": (0, 0), "b": (0, 4)}, "S-GAP")
    assert entry["raw"] == 2
    assert entry["explanation"].startswith("2 idle teaching periods - c1: Monday 10.00-11.00")


def test_s_gap_a_batch_sits_in_its_divisions_lectures() -> None:
    """Division D lectures Monday P0; batch D-A has a lab at P6-P7; batch D-B a
    lecture on Tuesday. COHORT edges put D's lecture in each batch's day and the
    batches' sessions in D's. Monday: D and D-A both idle at P1, P3, P4 (P5 is
    the canonical lunch break), so 3 + 3; D-B and Tuesday have one class each."""
    e = _payload(
        [_session("lec", "f1", "D"), _lab("lab", "f2", "D-A"), _session("tue", "f3", "D-B")],
        edges=[_edge("lec", "lab", "COHORT"), _edge("lec", "tue", "COHORT")],
    )
    entry = _rule(e, {"lec": (0, 0), "lab": (0, 6), "tue": (1, 0)}, "S-GAP")
    assert entry["raw"] == 6
    assert "D-B" not in entry["explanation"]


def test_s_gap_lunch_is_never_idle_and_never_ends_a_day() -> None:
    """D6 grid; c1's lunch, P5, is pinned for c1 alone every day (Row 8 shape).
    Monday: classes at P3 and P6, so P4 is idle and P5 is lunch: 1. Tuesday:
    classes at P0 and P1, and lunch does not stretch the day: 0. Wednesday: a
    frozen elective at P8 books a teacher and a room, so it closes the day
    after a class at P3: P4, P6 and P7 are idle: 3."""
    ids = {"mon3": (0, 3), "mon6": (0, 6), "tue0": (1, 0), "tue1": (1, 1), "wed3": (2, 3)}
    e = _payload(
        [_session(sid, f"f-{sid}", "c1") for sid in ids],
        pinned_occupancy=[_pin(d, 5, cohorts=("c1",)) for d in range(5)]
        + [_pin(2, 8, faculty=("f9",), rooms=("r9",), cohorts=("c1",))],
    )
    e["slot_grid"] = _d6()["slot_grid"]
    assert _rule(e, ids, "S-GAP")["raw"] == 4


# ----------------------------------------------------------------------
# S-B2B (D14)
# ----------------------------------------------------------------------


def test_s_b2b_counts_consecutive_periods_on_the_grids_adjacency() -> None:
    """P0-P1, then P1-P3 across the coffee break: two pairs."""
    e = _payload([_session("p0", "f1", "c1"), _session("p1", "f1", "c2"),
                  _session("p3", "f1", "c3")])
    entry = _rule(e, {"p0": (0, 0), "p1": (0, 1), "p3": (0, 3)}, "S-B2B")
    assert entry["raw"] == 2
    assert "f1 Monday 09.00-10.00 and Monday 10.00-11.00" in entry["explanation"]


def test_s_b2b_one_lab_alone_is_not_back_to_back_but_next_to_a_lecture_is() -> None:
    """The lab holds P1 and P3; a lecture at P4 touches P3."""
    assert _rule(_payload([_lab("lab", "f1", "c1")]), {"lab": (0, 1)}, "S-B2B")["raw"] == 0
    e = _payload([_lab("lab", "f1", "c1"), _session("lec", "f1", "c2")])
    assert _rule(e, {"lab": (0, 1), "lec": (0, 4)}, "S-B2B")["raw"] == 1


def test_s_b2b_two_pinned_slots_never_make_a_pair_but_a_session_beside_them_does() -> None:
    e = _payload([_session("s", "f1", "c1")],
                 pinned_occupancy=[_pin(1, 0, faculty=("f1",)), _pin(1, 1, faculty=("f1",))])
    assert _rule(e, {"s": (1, 6)}, "S-B2B")["raw"] == 0
    assert _rule(e, {"s": (1, 3)}, "S-B2B")["raw"] == 1


def test_s_b2b_follows_the_payloads_adjacency_across_lunch() -> None:
    """P4 and P6: consecutive on the canonical grid, which joins them across its
    lunch break; not on the D6 grid, where P5 teaches in between."""
    e = _payload([_session("a", "f1", "c1"), _session("b", "f1", "c2")])
    assert _rule(e, {"a": (0, 4), "b": (0, 6)}, "S-B2B")["raw"] == 1
    e["slot_grid"] = _d6()["slot_grid"]
    assert _rule(e, {"a": (0, 4), "b": (0, 6)}, "S-B2B")["raw"] == 0


# ----------------------------------------------------------------------
# S-LOAD16 (D11) and FAC_LOAD_IMBALANCE (row 7)
# ----------------------------------------------------------------------


def test_s_load16_flags_every_teacher_above_16_hours() -> None:
    """f1: nine practicals of 2 h (D11), 18 h. f2: sixteen 1 h lectures, 16 h,
    not above. f3: fifteen lectures and two frozen slots, one of them pinned
    twice, 17 h (a frozen item counts once per slot)."""
    lab_starts = [s for s in all_slots() if s.period in (0, 3, 6, 8)][:9]
    sessions = [_lab(f"p{i}", "f1", f"b{i}") for i in range(9)]
    sessions += [_session(f"l{i}", "f2", f"x{i}") for i in range(16)]
    sessions += [_session(f"m{i}", "f3", f"y{i}") for i in range(15)]
    starts = {f"p{i}": (s.day, s.period) for i, s in enumerate(lab_starts)}
    starts |= {f"l{i}": (s.day, s.period) for i, s in enumerate(all_slots()[:16])}
    starts |= {f"m{i}": (s.day, s.period) for i, s in enumerate(all_slots()[:15])}
    pins = [_pin(4, 8, faculty=("f3",)), _pin(4, 9, faculty=("f3",)), _pin(4, 9, faculty=("f3",))]
    entry = _rule(_payload(sessions, pinned_occupancy=pins), starts, "S-LOAD16")
    assert entry["raw"] == 2
    assert entry["explanation"] == "2 faculty members above 16 h a week - f1 18 h, f3 17 h."


def test_load_imbalance_sums_each_teachers_heaviest_minus_lightest_day() -> None:
    """f1: 3 h, all on Monday: 3. f2: 1 h every day: 0. f3: a 2 h practical on
    Tuesday and 1 h on Wednesday, nothing Monday: 2. f4: one frozen slot on
    Thursday: 1. A day without teaching counts as 0 h."""
    sessions = [_session(f"a{p}", "f1", f"c-a{p}") for p in (0, 1, 3)]
    sessions += [_session(f"b{d}", "f2", f"c-b{d}") for d in range(5)]
    sessions += [_lab("c1", "f3", "c-c1"), _session("c2", "f3", "c-c2")]
    starts = {f"a{p}": (0, p) for p in (0, 1, 3)} | {f"b{d}": (d, 0) for d in range(5)}
    starts |= {"c1": (1, 0), "c2": (2, 0)}
    e = _payload(sessions, pinned_occupancy=[_pin(3, 6, faculty=("f4",))])
    entry = _rule(e, starts, "FAC_LOAD_IMBALANCE")
    assert entry["raw"] == 6
    assert "f1 3 h on Monday, 0 h on Tuesday" in entry["explanation"]
    assert "f2" not in entry["explanation"]


# ----------------------------------------------------------------------
# The whole block
# ----------------------------------------------------------------------


def test_scoring_is_deterministic_and_ignores_payload_order() -> None:
    e = generate(PRESETS["medium"], 1)
    starts = backtrack_solve(build_conflict_graph(e), e).assignment
    first = score(e, starts)
    assert score(e, starts) == first
    reordered = copy.deepcopy(e)
    for key in ("sessions", "edges", "pinned_occupancy", "faculty_availability"):
        reordered[key].reverse()
    assert score(reordered, dict(reversed(list(starts.items())))) == first


def test_solver_imports_only_the_stdlib_and_yaml_only_where_rules_load() -> None:
    """CONTEXT.md rules 2 and 3, with the S10 exception: PyYAML in scoring.py only."""
    for path in sorted((REPO / "solver").rglob("*.py")):
        if "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                assert (root == "solver" or root in sys.stdlib_module_names
                        or (root == "yaml" and path.name == "scoring.py")), (path.name, root)
