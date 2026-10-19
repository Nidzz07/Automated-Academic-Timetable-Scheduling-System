"""The real EVEN SE+TE timetable as printed, in terms of our instance (ROADMAP S12b).

For every session of ``data/instances/even-2025-26/edge_list.json`` this takes
the day and start period printed in the class timetable (the ingestion.v2
observed session it was seeded from, :func:`ingestion.emit_v2.build`), and the
printed room if it is in the edge list's room set, otherwise none (D10, D29).
A session that cannot be placed at its printed slot is listed with the reason,
never guessed.

The result is checked with :func:`solver.validate.validate_slot_placements`
(time only: slots, conflict edges, lunch and other pins, contiguity) and scored
with :func:`solver.scoring.score`, so the generated timetable can be compared
with what SPIT actually runs. Every violation is reported; nothing is relaxed.
Session ids are joined through hash maps (Data Structures).

Writes:

- ``data/instances/even-2025-26/real_baseline.assignment.json``: session id ->
  day, start period, room or null. Not a contract.
- ``data/instances/even-2025-26/real_baseline.report.json``: every violation
  (kind, sessions, slots, entities, with names from display.json) and the
  score breakdown, for the UI. Not a contract.
- ``docs/real-baseline-even-2025-26.md``: the report.

Run from the repo root::

    python -m ingestion.real_baseline
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ingestion.emit_v2 import Instance, build, dumps
from ingestion.lab_tt import normalise_room
from ingestion.seed_reference import REPO_ROOT
from solver.scoring import score
from solver.slots import SlotId
from solver.validate import Violation, validate_slot_placements

INSTANCE_DIR = REPO_ROOT / "data" / "instances" / "even-2025-26"
EDGE_LIST_JSON = INSTANCE_DIR / "edge_list.json"
DISPLAY_JSON = INSTANCE_DIR / "display.json"
SOLUTION_JSON = INSTANCE_DIR / "solution.json"
ASSIGNMENT_JSON = INSTANCE_DIR / "real_baseline.assignment.json"
REPORT_JSON = INSTANCE_DIR / "real_baseline.report.json"
REPORT_MD = REPO_ROOT / "docs" / "real-baseline-even-2025-26.md"


@dataclass
class Baseline:
    #: mapped session id -> {day, period, room_id, sub_room_id}
    assignment: dict[str, dict[str, Any]]
    #: session id -> why it has no printed slot
    unmapped: dict[str, str]
    #: mapped session id -> (why its room is null, decision)
    no_room: dict[str, tuple[str, str]]
    #: mapped session id -> the printed cell line
    printed: dict[str, str]
    #: mapped session id -> the printed room text, None if none
    printed_room: dict[str, str | None]
    violations: list[Violation]
    quality: dict[str, Any]


def map_sessions(edge_list: dict, inst: Instance) -> Baseline:
    """Printed slot and room of every edge-list session; then validate and score."""
    printed = {row["id"]: row for row in inst.payload["observed_sessions"]}
    entries = {f"obs-t{e.table}-r{e.row}-c{e.col}-l{e.line}": e
               for e in inst.sources.class_tt.entries}
    room_set = {r["id"] for r in edge_list["rooms"]}
    teaching = set(edge_list["slot_grid"]["teaching_periods"])
    assignment: dict[str, dict[str, Any]] = {}
    unmapped: dict[str, str] = {}
    no_room: dict[str, tuple[str, str]] = {}
    for s in edge_list["sessions"]:
        sid, row = s["id"], printed.get(s["id"])
        if row is None:
            unmapped[sid] = "not in the parsed timetables"
            continue
        if row["duration_periods"] != s["duration_periods"]:
            unmapped[sid] = (f"printed for {row['duration_periods']} periods; the edge list "
                             f"needs {s['duration_periods']}")
            continue
        if row["period"] not in teaching:
            unmapped[sid] = f"printed start P{row['period']} is not a teaching period"
            continue
        room, sub = row["room_id"], row["sub_room_id"]
        if (sub or room) not in room_set:
            entry = entries.get(sid)
            if entry is None or entry.room_raw is None:
                no_room[sid] = ("no room printed", "-")
            elif room is not None:
                no_room[sid] = (f"room {sub or room} is not in the edge list's room set", "-")
            else:
                note = normalise_room(entry.room_raw, inst.sources.inventory).note
                no_room[sid] = (note[1], note[2])
            room = sub = None
        assignment[sid] = {"day": row["day"], "period": row["period"],
                           "room_id": room, "sub_room_id": sub}

    # The checker and the scorer need every session placed: hold them to the mapped ones.
    mapped = {**edge_list,
              "sessions": [s for s in edge_list["sessions"] if s["id"] in assignment],
              "edges": [e for e in edge_list["edges"]
                        if e["u"] in assignment and e["v"] in assignment],
              "lab_blocks": [{**b, "session_ids": [m for m in b["session_ids"] if m in assignment]}
                             for b in edge_list["lab_blocks"]
                             if any(m in assignment for m in b["session_ids"])]}
    starts = {sid: (a["day"], a["period"]) for sid, a in assignment.items()}
    return Baseline(
        assignment, unmapped, no_room,
        {sid: printed[sid]["source_cell"] for sid in assignment},
        {sid: e.room_raw.strip() if (e := entries.get(sid)) and e.room_raw else None
         for sid in assignment},
        validate_slot_placements(mapped, starts),
        score(mapped, {sid: SlotId(*slot) for sid, slot in starts.items()}),
    )


def assignment_file(b: Baseline) -> dict[str, Any]:
    return {
        "note": "Not a contract. The real EVEN timetable as printed, per edge_list.json session: "
                "printed day and start period; printed room if in the edge list's room set, "
                "else null (D10, D29). See docs/real-baseline-even-2025-26.md.",
        "generated_by": "python -m ingestion.real_baseline",
        "edge_list": EDGE_LIST_JSON.name,
        "assignment": dict(sorted(b.assignment.items())),
        "unmapped": dict(sorted(b.unmapped.items())),
    }


def display_name(display: dict, eid: str) -> str:
    """A faculty, cohort (a batch by its unique label) or room id's name, else the id."""
    cohort = display["cohorts"].get(eid)
    return (display["faculty"].get(eid) or (cohort and cohort.get("label", cohort["name"]))
            or display["rooms"].get(eid) or eid)


def report_file(b: Baseline, edge_list: dict, display: dict) -> dict[str, Any]:
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    return {
        "note": "Not a contract. The real EVEN timetable as printed: the time-only check's "
                "violations, names from display.json (D41), and the quality score. See "
                "docs/real-baseline-even-2025-26.md.",
        "generated_by": "python -m ingestion.real_baseline",
        "edge_list": EDGE_LIST_JSON.name,
        "violations": [{
            **v.to_dict(),
            "sessions": {sid: {
                "subject": display["subjects"][sessions[sid]["subject_id"]]["code"],
                "cohort": display_name(display, sessions[sid]["cohort_id"]),
                "faculty": display_name(display, sessions[sid]["faculty_id"]),
                "printed": b.printed[sid],
            } for sid in v.session_ids},
            "entities": {eid: display_name(display, eid) for eid in v.entity_ids},
        } for v in b.violations],
        "quality": b.quality,
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def _cell(text: str) -> str:
    return text.replace("\n", " ").replace("|", "\\|")


def report(b: Baseline, edge_list: dict, display: dict) -> str:
    sessions = {s["id"]: s for s in edge_list["sessions"]}
    days = display["days"]

    def name(eid: str) -> str:
        return display_name(display, eid)

    def slot(day: int, period: int) -> str:
        return f"{days[day][:3]} P{period}"

    def session(sid: str) -> str:
        s = sessions[sid]
        return _cell(f"{display['subjects'][s['subject_id']]['code']} · {name(s['cohort_id'])} · "
                     f"{name(s['faculty_id'])} (`{b.printed[sid]}`)")

    def held_by(v: Violation) -> str:
        labels = [
            f"{name(e)}: {pin['kind']} `{pin['label']}`"
            + (f" ({pin['decision']})" if "decision" in pin else "")
            for occ, pin in zip(edge_list["pinned_occupancy"], display["pins"], strict=True)
            for e in v.entity_ids
            if any(SlotId(occ["day"], occ["period"]) == s for s in v.slots)
            and e in occ["faculty_ids"] + occ["cohort_ids"]
        ]
        return _cell("; ".join(dict.fromkeys(labels)))

    n = len(sessions)
    rooms = sum(a["room_id"] is not None for a in b.assignment.values())
    by_kind = Counter(v.kind for v in b.violations)
    clashes = [v for v in b.violations if v.kind == "FACULTY_CLASH"]
    combined = sum(
        len({(sessions[sid]["subject_id"], b.printed_room[sid]) for sid in v.session_ids}) == 1
        and b.printed_room[v.session_ids[0]] is not None for v in clashes)
    q = b.quality

    out = [
        "# The real EVEN 2025-26 SE+TE timetable as printed (S12b)",
        "",
        "Track B · generated by `python -m ingestion.real_baseline`; do not edit by hand.",
        "",
        "What SPIT actually runs, expressed in terms of"
        " `data/instances/even-2025-26/edge_list.json` so the generated timetable can be"
        " compared with it. Each session takes the day and start period printed in the class"
        " timetable, and the printed room only if it is in the edge list's room set (D10, D29)."
        " The time-only check"
        " (`solver.validate.validate_slot_placements`: slots, conflict edges, lunch and other pins,"
        " contiguity) and `solver.scoring.score` run on it unchanged; every violation is listed."
        " Names come from `display.json` (D41).",
        "",
        "`data/instances/even-2025-26/real_baseline.assignment.json` (session id -> day, start"
        " period, room or null) is **not a contract**: a side file for comparison only.",
        "",
        "## Mapping",
        "",
        "| | |",
        "|---|---|",
        f"| Sessions in the edge list | {n} |",
        f"| Mapped to their printed day and start period | {len(b.assignment)} |",
        f"| Unmapped | {len(b.unmapped)} |",
        f"| Mapped with a printed room in the edge list's room set | {rooms} |",
        f"| Mapped with room null | {len(b.no_room)} |",
        "",
    ]
    if b.unmapped:
        out += ["Unmapped sessions (left out of the check and the score):", "",
                "| Session | Reason |", "|---|---|"]
        out += [f"| `{sid}` | {_cell(why)} |" for sid, why in sorted(b.unmapped.items())]
    else:
        out.append("Every session was found at its printed slot with its edge-list duration.")
    out += ["", "Room null, by reason:", "", "| Reason | Decision | Sessions |", "|---|---|---|"]
    out += [f"| {_cell(why)} | {dec} | {k} |"
            for (why, dec), k in sorted(Counter(b.no_room.values()).items())]

    out += ["", "## Hard-constraint violations (time only)", ""]
    if not b.violations:
        out.append("None.")
    else:
        out += ["| Kind | Count |", "|---|---|"]
        out += [f"| {kind} | {k} |" for kind, k in by_kind.items()]
        out += ["", f"{len(b.violations)} in all, one row each:", "",
                "| Kind | Slot | Sessions | Held by |", "|---|---|---|---|"]
        out += [
            f"| {v.kind} | {', '.join(slot(s.day, s.period) for s in v.slots)} | "
            f"{'<br>'.join(session(sid) for sid in v.session_ids)} | "
            f"{held_by(v) if v.kind == 'PINNED_BLOCK' else ''} |"
            for v in b.violations
        ]
        if clashes:
            out += ["", f"{combined} of the {len(clashes)} FACULTY_CLASH violations are one"
                    " subject, one teacher and one printed room for two divisions at one slot: a"
                    " combined lecture, which D40 schedules as one lecture per division."]
        if by_kind["PINNED_BLOCK"]:
            out += ["", "Each PINNED_BLOCK row is a session printed in a slot that the pins under"
                    " *Held by* hold for its cohort (a frozen item blocks every batch of its"
                    " divisions, D24)."]

    out += ["", "## Quality score", "",
            f"Score **{q['score']:g}** (rules version {q['rules_version']}).", "",
            "| Rule | Weight | Raw | Penalty |", "|---|---|---|---|"]
    out += [f"| {r['rule_id']} | {r['weight']:g} | {r['raw']} | {r['penalty']:g} |"
            for r in q["breakdown"]]
    out += ["", "## Compared with the generated timetable", ""]
    out.append(
        "`data/instances/even-2025-26/solution.json` exists, but this report does not compare it"
        " yet." if SOLUTION_JSON.exists() else
        "`data/instances/even-2025-26/solution.json` is not on main (S12a timed out, D33), so"
        " there is no side-by-side table yet."
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    edge_list = json.loads(EDGE_LIST_JSON.read_text(encoding="utf-8"))
    display = json.loads(DISPLAY_JSON.read_text(encoding="utf-8"))
    b = map_sessions(edge_list, build())
    ASSIGNMENT_JSON.write_text(dumps(assignment_file(b)), encoding="utf-8", newline="\n")
    REPORT_JSON.write_text(dumps(report_file(b, edge_list, display)), encoding="utf-8",
                           newline="\n")
    REPORT_MD.write_text(report(b, edge_list, display), encoding="utf-8", newline="\n")
    print(f"wrote {ASSIGNMENT_JSON}\nwrote {REPORT_JSON}\nwrote {REPORT_MD}")
    print(f"{len(b.assignment)} mapped, {len(b.unmapped)} unmapped, "
          f"{len(b.violations)} violations, score {b.quality['score']:g}")


if __name__ == "__main__":
    main()
