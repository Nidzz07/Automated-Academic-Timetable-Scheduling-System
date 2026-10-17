"""Quality scoring: the four soft rules of ROADMAP section 6 (S10, D34).

A solved timetable is scored against ``solver/rules/quality_rules.yaml``. Rules
and weights are versioned data, so a department changes a weight without a code
change (CONTEXT.md rule 4); :func:`load_rules` refuses anything but exactly the
four D34 rules. :func:`score` returns the ``solution.v2`` quality block
(proposal row 6): one ``evaluated`` entry per rule with its raw measure,
``penalty = weight * raw`` and an explanation naming the ids involved, and
``score = 100 - sum of penalties``, the arithmetic of both contract examples.

Everything is read from the edge list and the start slots alone, like
:mod:`solver.validate`: occupancy is walked on the payload's grid, cohorts that
share students are found through COHORT edges (the edge list has no
division -> batch hierarchy), and pinned occupancy is read entry by entry.

**What a pin counts as.** ``edge_list_v1`` pins carry no kind, and nothing
infers lunch from a pin's shape (ROADMAP D41). So the rules use only what a pin
books: its cohorts are busy then, its teachers teach then, and a pin that books
a teacher or a room is a class (D24: a frozen item blocks its teacher and room).
A pin that books only cohorts - a year's lunch (Row 8 assessment) - is busy but
is not a class.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # the rule set is versioned YAML (CONTEXT.md rule 4); solver/'s one non-stdlib import

from solver.slots import DAY_NAMES, SlotGrid, SlotId

__all__ = ["RULES_FILE", "Rule", "RuleSet", "load_rules", "score"]

RULES_FILE = Path(__file__).with_name("rules") / "quality_rules.yaml"


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    description: str
    weight: float
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True, slots=True)
class _Timetable:
    """A solved timetable as the rules read it."""

    edge_list: dict[str, Any]
    grid: SlotGrid
    occupied: dict[str, tuple[SlotId, ...]]  # session -> every slot it holds
    taught: dict[str, dict[SlotId, str | None]]  # faculty -> slot -> session, None for a pin


def _timetable(edge_list: dict[str, Any], starts: dict[str, SlotId]) -> _Timetable:
    grid = SlotGrid.from_payload(edge_list["slot_grid"])
    periods = grid.teaching_periods
    occupied: dict[str, tuple[SlotId, ...]] = {}
    taught: dict[str, dict[SlotId, str | None]] = {}
    for s in edge_list["sessions"]:
        start = starts[s["id"]]
        first = periods.index(start.period)
        occupied[s["id"]] = tuple(
            SlotId(start.day, p) for p in periods[first:first + s["duration_periods"]]
        )
        for slot in occupied[s["id"]]:
            taught.setdefault(s["faculty_id"], {})[slot] = s["id"]
    for pin in edge_list["pinned_occupancy"]:
        slot = grid.slot(pin["day"], pin["period"])
        if grid.is_teaching_period(slot.period):
            for fid in pin["faculty_ids"]:
                taught.setdefault(fid, {}).setdefault(slot, None)
    return _Timetable(edge_list, grid, occupied, taught)


# ---------------------------------------------------------------------------
# The four rules: each gives (raw, explanation)
# ---------------------------------------------------------------------------


def _student_gaps(t: _Timetable) -> tuple[int, str]:
    """S-GAP (D13): idle teaching periods inside each cohort's day.

    For every cohort with a session (divisions and batches) and every day: the
    teaching periods strictly between its first and last class in which none of
    its students is busy. A cohort's students are busy in the sessions of every
    cohort it shares students with - itself and each cohort a COHORT edge joins
    it to, so a batch sits in its division's lectures and a division is busy
    while any of its batches is - and in every pin naming one of those cohorts.
    Classes are sessions and pins that book a teacher or a room. A cohort-only
    pin (a lunch) is busy, so never idle, but never opens or closes a day.
    Breaks are not teaching periods, so they are never idle. A scan of each
    day's periods over hash sets (Data Structures).

    shortcut: label-only frozen items (MDM, HSS, LLC, activity) reach the edge
    list as cohort-only pins too, so they never open or close a day; read pin
    kinds instead if the edge list ever carries them.
    """
    cohort_of = {s["id"]: s["cohort_id"] for s in t.edge_list["sessions"]}
    shares = {cohort: {cohort} for cohort in cohort_of.values()}
    for edge in t.edge_list["edges"]:
        if edge["reason"] == "COHORT":
            a, b = cohort_of[edge["u"]], cohort_of[edge["v"]]
            shares[a].add(b)
            shares[b].add(a)
    classes: dict[str, set[SlotId]] = {}
    held: dict[str, set[SlotId]] = {}
    for sid, cohort in cohort_of.items():
        classes.setdefault(cohort, set()).update(t.occupied[sid])
    for pin in t.edge_list["pinned_occupancy"]:
        target = classes if pin["faculty_ids"] or pin["room_ids"] else held
        for cohort in pin["cohort_ids"]:
            target.setdefault(cohort, set()).add(t.grid.slot(pin["day"], pin["period"]))

    idle: dict[str, list[SlotId]] = {}
    for cohort in sorted(shares):
        bounds = set().union(*(classes.get(c, ()) for c in shares[cohort]))
        busy = bounds.union(*(held.get(c, ()) for c in shares[cohort]))
        for day in range(t.grid.days):
            periods = [slot.period for slot in bounds if slot.day == day]
            if not periods:
                continue
            idle.setdefault(cohort, []).extend(
                SlotId(day, p) for p in t.grid.teaching_periods
                if min(periods) < p < max(periods) and SlotId(day, p) not in busy
            )
    raw = sum(len(slots) for slots in idle.values())
    if not raw:
        return 0, "No cohort has an idle teaching period between its first and last class."
    listed = "; ".join(f"{c}: {', '.join(map(str, s))}" for c, s in idle.items() if s)
    return raw, f"{raw} idle teaching periods - {listed}."


def _back_to_back(t: _Timetable) -> tuple[int, str]:
    """S-B2B (D14): consecutive teaching periods one teacher teaches with no break.

    For every faculty member, each adjacency pair of the payload grid - an edge
    of the day's path of teaching periods (DSGT) - whose two slots they teach in
    two different sessions. So one multi-period lab alone is not back-to-back
    (D14) and a lab next to another session is. A pinned slot naming them counts
    as taught (D24), but two pinned slots never make a pair: the edge list cannot
    tell one frozen two-hour item from two, and no timetable can move them.
    """
    pairs: list[str] = []
    for fid in sorted(t.taught):
        slots = t.taught[fid]
        for day in range(t.grid.days):
            for a, b in sorted(t.grid.adjacency):
                x, y = SlotId(day, a), SlotId(day, b)
                if x in slots and y in slots and slots[x] != slots[y]:
                    pairs.append(f"{fid} {x} and {y}")
    if not pairs:
        return 0, "No faculty member teaches two consecutive teaching periods."
    return len(pairs), f"{len(pairs)} back-to-back pairs - {'; '.join(pairs)}."


def _load_above(t: _Timetable, threshold_hours: float) -> tuple[int, str]:
    """S-LOAD16 (D11): faculty members whose weekly load is above the target.

    Load in hours is the teaching slots taught: a lecture or tutorial 1 h per
    period (D23: one tutorial per division), a practical 2 h per batch (D11: its
    two periods), a frozen item once per pinned slot. Who teaches what fixes it,
    so every timetable of an instance gets the same flags. A count per teacher
    over a hash map (Data Structures).
    """
    over = {fid: len(t.taught[fid]) for fid in sorted(t.taught)
            if len(t.taught[fid]) > threshold_hours}
    if not over:
        return 0, f"No faculty member teaches more than {threshold_hours:g} h a week."
    listed = ", ".join(f"{fid} {hours} h" for fid, hours in over.items())
    return len(over), f"{len(over)} faculty members above {threshold_hours:g} h a week - {listed}."


def _daily_load_spread(t: _Timetable) -> tuple[int, str]:
    """FAC_LOAD_IMBALANCE (proposal row 7): how unevenly each teacher's week is spread.

    For each faculty member: the hours taught on each day of the grid (the same
    T/P-weighted hours as S-LOAD16, so a practical's two periods are two hours),
    then the range, heaviest day minus lightest day; ``raw`` sums the ranges over
    faculty. The range is the simplest dispersion statistic (Statistical Methods
    in Computer Science, CE205), and row 7 names it. Every day of the week counts,
    a day without teaching as 0 h: counting only the days someone teaches would
    rate a whole week packed into Monday as perfectly balanced. So a teacher with
    fewer hours than days always has a 0 h day, and their range is at least their
    heaviest day.
    """
    spreads: list[str] = []
    raw = 0
    for fid in sorted(t.taught):
        hours = [sum(slot.day == day for slot in t.taught[fid]) for day in range(t.grid.days)]
        heavy, light = hours.index(max(hours)), hours.index(min(hours))
        if hours[heavy] > hours[light]:
            raw += hours[heavy] - hours[light]
            spreads.append(f"{fid} {hours[heavy]} h on {DAY_NAMES[heavy]}, "
                           f"{hours[light]} h on {DAY_NAMES[light]}")
    if not raw:
        return 0, "Every faculty member teaches the same hours on each day of the week."
    return raw, f"Daily load spreads sum to {raw} h - {'; '.join(spreads)}."


#: Rule id -> (measure, its parameters); exactly the four of ROADMAP D34.
_RULES: dict[str, tuple[Callable[..., tuple[int, str]], tuple[str, ...]]] = {
    "S-GAP": (_student_gaps, ()),
    "S-B2B": (_back_to_back, ()),
    "S-LOAD16": (_load_above, ("threshold_hours",)),
    "FAC_LOAD_IMBALANCE": (_daily_load_spread, ()),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_rules(path: Path = RULES_FILE) -> RuleSet:
    """Read and check the rule set; anything but exactly the four D34 rules fails.

    Rules are data checked against a registry of measures at load, so a weight
    changes without a code change (configuration over code, Software Engineering).

    Raises:
        ValueError: on a missing or non-string ``version``, an unknown, missing
            or repeated rule id, a rule key or parameter the measure does not
            take, or a weight that is not a number at least 0.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "rules"}:
        raise ValueError(f"{path.name}: the top level must be exactly 'version' and 'rules'")
    if not isinstance(data["version"], str) or not data["version"]:
        raise ValueError(f"{path.name}: 'version' must be a non-empty string")
    if not isinstance(data["rules"], list):
        raise ValueError(f"{path.name}: 'rules' must be a list")
    rules: list[Rule] = []
    for raw in data["rules"]:
        if not isinstance(raw, dict) or set(raw) != {"id", "description", "weight", "parameters"}:
            raise ValueError(f"{path.name}: a rule needs exactly id, description, weight and "
                             f"parameters, got {raw!r}")
        rule_id, weight, params = raw["id"], raw["weight"], raw["parameters"]
        if rule_id not in _RULES:
            raise ValueError(f"{path.name}: unknown quality rule id {rule_id!r}; "
                             f"ROADMAP D34 allows only {', '.join(_RULES)}")
        if isinstance(weight, bool) or not isinstance(weight, int | float) or weight < 0:
            raise ValueError(f"{path.name}: {rule_id} weight must be a number >= 0, got {weight!r}")
        if not isinstance(raw["description"], str) or not raw["description"].strip():
            raise ValueError(f"{path.name}: {rule_id} needs a description")
        if (not isinstance(params, dict) or set(params) != set(_RULES[rule_id][1])
                or not all(isinstance(v, int | float) and not isinstance(v, bool)
                           for v in params.values())):
            raise ValueError(f"{path.name}: {rule_id} parameters must be exactly "
                             f"{list(_RULES[rule_id][1])} as numbers, got {params!r}")
        rules.append(Rule(rule_id, raw["description"], float(weight), dict(params)))
    if sorted(r.id for r in rules) != sorted(_RULES):
        raise ValueError(f"{path.name}: the rule set must hold each of {', '.join(_RULES)} "
                         f"exactly once, got {[r.id for r in rules]}")
    return RuleSet(data["version"], tuple(rules))


def score(edge_list: dict[str, Any], starts: dict[str, SlotId]) -> dict[str, Any]:
    """The ``solution.v2`` quality block of a solved timetable (proposal row 6).

    *starts* maps every session of *edge_list* to its start slot. Every rule
    walks ids, days and periods in sorted order, so the same timetable always
    gets the same block, explanation text included. The rule set is read from
    :data:`RULES_FILE` on every call.
    """
    rules = load_rules()
    t = _timetable(edge_list, starts)
    breakdown: list[dict[str, Any]] = []
    for rule in rules.rules:
        raw, explanation = _RULES[rule.id][0](t, **rule.parameters)
        breakdown.append({
            "rule_id": rule.id,
            "status": "evaluated",
            "weight": rule.weight,
            "raw": raw,
            "penalty": rule.weight * raw,
            "explanation": explanation,
        })
    return {
        "score": 100.0 - sum(entry["penalty"] for entry in breakdown),
        "rules_version": rules.version,
        "breakdown": breakdown,
        "not_evaluated_rule_ids": [],
    }
