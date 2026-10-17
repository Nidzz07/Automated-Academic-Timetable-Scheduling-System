"""One combined anomaly report for the EVEN SE+TE sources (ROADMAP S7).

Collects every data-quality finding from the teaching scheme, the room
inventory (classrooms.xlsx, lab_capacities.yaml), the class timetable, the lab
timetable, the class-vs-lab practical cross-check and the faculty timetable.
Each anomaly carries a category, its source file, a location (table / row /
cell), a message, and either the ROADMAP decision that resolves it or "needs
human". Nothing is repaired here (CONTEXT.md 3.5).

Run from the repo root::

    python -m ingestion.anomalies   # writes ingestion/anomaly_report.txt and
                                    # data/generated/anomalies_even.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ingestion.class_tt import (
    COFFEE_PERIOD,
    EVEN_CLASS_FILE,
    ClassTimetable,
    Entry,
    FacultyIndex,
    faculty_index,
    parse_class_timetable,
    subject_key,
)
from ingestion.faculty import FacultyTimetable, parse_faculty_timetable
from ingestion.lab_tt import (
    D38_INITIALS,
    LAB_CAPACITIES_YAML,
    NEEDS_HUMAN,
    Finding,
    Inventory,
    LabTimetable,
    RoomRef,
    attributed,
    canonical_group,
    class_resolution,
    cross_check,
    division_key,
    label_key,
    normalise_room,
    parse_lab_timetable,
    room_inventory,
)
from ingestion.out_of_scope import Block, Frozen, blocks
from ingestion.scheme import SCHEME_YAML, TeachingScheme, load_scheme
from ingestion.seed_reference import CLASSROOMS_XLSX, REPO_ROOT, parse_faculty_subjects

DEFAULT_REPORT = Path(__file__).resolve().parent / "anomaly_report.txt"
DEFAULT_JSON = REPO_ROOT / "data" / "generated" / "anomalies_even.json"

#: D26 names this subject.
FOM_II = "FOM - II"
SMCS = "CE205"


@dataclass(frozen=True)
class Anomaly:
    category: str
    source_file: str
    location: str
    message: str
    #: ROADMAP decision id, or "needs human".
    resolution: str


@dataclass
class Sources:
    """Every parsed source, parsed once. ``cross`` must run before ``faculty_tt``:
    it marks the lab entries the class timetable already accounts for."""

    scheme: TeachingScheme
    faculty: FacultyIndex
    inventory: Inventory
    class_tt: ClassTimetable
    lab: LabTimetable
    cross: list[Finding]
    faculty_tt: FacultyTimetable
    #: D44: "CE faculty" for D3 - Faculty___Subjects.xlsx, into which D25 and D38 resolve.
    ce_faculty: frozenset[str] = frozenset()
    #: Occupancy outside the SE/TE grids (D35, D37, faculty-page MDM per D24).
    blocks: list[Block] = field(default_factory=list)
    block_findings: list[Finding] = field(default_factory=list)


def load_sources() -> Sources:
    scheme = load_scheme()
    faculty = faculty_index()
    inventory = room_inventory()
    class_tt = parse_class_timetable(scheme=scheme, faculty=faculty)
    lab = parse_lab_timetable(class_tt=class_tt, faculty=faculty, inventory=inventory)
    cross = cross_check(class_tt, lab)
    faculty_tt = parse_faculty_timetable(class_tt, lab, faculty)
    s = Sources(scheme, faculty, inventory, class_tt, lab, cross, faculty_tt,
                frozenset(f.full_name for f in parse_faculty_subjects()))
    s.blocks, s.block_findings = blocks(class_tt, lab, faculty_tt, faculty, inventory,
                                        s.ce_faculty, frozen_seen(s), teaching_slots(s))
    return s


def teacher(e: Entry, s: Sources) -> str | None:
    """The one person a class-timetable line names (D25, D38 applied), or None."""
    return attributed(*class_resolution(e, s.faculty))


def is_d44(e: Entry, s: Sources) -> bool:
    """D44: an in-scope line whose teacher is not CE faculty is frozen (AS201 PCS)."""
    name = teacher(e, s) if e.subject_raw and not e.excluded else None
    return name is not None and name not in s.ce_faculty


def is_frozen(e: Entry, s: Sources) -> bool:
    """D24: every D3-excluded item in the grid; D26: FOM - II and SMCS; D44."""
    return e.excluded or e.scheme_code == SMCS or is_d44(e, s)


def _generation_room(raw: str | None, inv: Inventory) -> RoomRef | None:
    ref = normalise_room(raw, inv) if raw else None
    return ref if ref and ref.room else None


def frozen_seen(s: Sources) -> list[Frozen]:
    """Every frozen SE/TE line of the class and lab timetables, for matching."""
    out = [Frozen(teacher(e, s), e.faculty_initials_raw, e.day,
                  frozenset(p for p in e.periods if p != COFFEE_PERIOD), e.subject_raw,
                  _generation_room(e.room_raw, s.inventory))
           for e in s.class_tt.entries if e.subject_raw and is_frozen(e, s)]
    out += [Frozen(attributed(le.faculty_status, le.faculty_candidates), le.faculty_initials_raw,
                   le.day, frozenset(le.teaching_periods), le.subject_raw or le.raw,
                   RoomRef(le.room_label, le.room, le.sub_room) if le.room else None)
            for le in s.lab.entries if le.kind in ("elective", "mdm")]
    return out


def teaching_slots(s: Sources) -> dict[tuple[str, str], set[int]]:
    """(teacher, day) -> periods the class and lab timetables give them in SE/TE."""
    out: dict[tuple[str, str], set[int]] = {}
    for e in s.class_tt.entries:
        if e.subject_raw and (name := teacher(e, s)):
            out.setdefault((name, e.day), set()).update(e.periods)
    for le in s.lab.entries:
        if le.kind in ("practical", "elective") and (
                name := attributed(le.faculty_status, le.faculty_candidates)):
            out.setdefault((name, le.day), set()).update(le.periods)
    return out


# --------------------------------------------------------------------------- #
# Collecting
# --------------------------------------------------------------------------- #

#: class_tt anomaly kind -> the decision that settles it.
_CLASS_RESOLUTION = {
    "division_wide_tutorial": "D23",
    "break_partial": "D6",
    "coffee_mismatch": "D6",
    "lunch_mismatch": "D6",
    "overlaps_break": "D24",
}


def _class_resolution(kind: str, division: str, detail: str) -> str:
    if kind in ("unmatched_subject", "parallel_division_sessions") and FOM_II in detail:
        return "D26"
    if kind == "initials_not_in_division_legend":
        if detail.startswith("SRD "):
            return "D25"
        if ((division_key(division) or "")[:2], detail.split()[0]) in D38_INITIALS:
            return "D38"
    return _CLASS_RESOLUTION.get(kind, NEEDS_HUMAN)


def _exclusion(e: Entry) -> Anomaly:
    raw = e.raw.replace("\n", " | ")
    if e.subject_raw == FOM_II:
        resolution, how = "D26", "an alternative to SMCS, frozen at its slot"
    else:
        resolution, how = "D24", "frozen at its slot with its division, teacher and room"
    return Anomaly("excluded_item", EVEN_CLASS_FILE.name, f"{e.division} {e.where}",
                   f"{raw!r}: {e.exclude_reason}; {how}", resolution)


def lecture_rooms(s: Sources) -> list[Anomaly]:
    """Task 6: lecture and tutorial rooms the timetable uses that D10 or D29 excludes."""
    in_scope: Counter[str] = Counter()
    frozen: Counter[str] = Counter()
    for e in s.class_tt.entries:
        division_wide = e.subject_raw and not e.batch and not e.elective_group
        if e.room_raw is None or not (e.session_type in ("lecture", "tutorial") or division_wide):
            continue
        (frozen if is_frozen(e, s) else in_scope)[e.room_raw] += e.duration
    out: list[Anomaly] = []
    removed = 0
    for raw in sorted(set(in_scope) | set(frozen)):
        ref = normalise_room(raw, s.inventory)
        room = s.inventory.rooms.get(ref.room) if ref.room else None
        if room is not None and room.room_type == "class":
            continue
        if room is None:
            category, resolution = "lecture_room_excluded", ref.note[2] if ref.note else NEEDS_HUMAN
            why = ref.note[1] if ref.note else "not in the generation room set"
        else:
            category, resolution = "lecture_room_not_class", NEEDS_HUMAN
            why = f"room {room.code} has room_type {room.room_type!r}, not 'class'"
        removed += in_scope[raw]
        out.append(Anomaly(
            category, EVEN_CLASS_FILE.name, f"room {raw}",
            f"{why}; removes {in_scope[raw]} in-scope lecture/tutorial periods per week "
            f"(frozen lecture lines there: {frozen[raw]})",
            resolution,
        ))
    out.append(Anomaly(
        "lecture_room_total", EVEN_CLASS_FILE.name, "all lecture rooms",
        f"{removed} of {sum(in_scope.values())} in-scope lecture/tutorial periods per week are "
        "printed in rooms the generation room set does not offer as classrooms; the solver "
        "re-rooms them",
        "D10",
    ))
    return out


@dataclass
class FrozenGroup:
    """One frozen line (D24, D26), seen in one or more division grids."""

    entries: list[Entry]
    #: The room used for it; None when the grids disagree and nothing settles it.
    room_raw: str | None
    #: Set when the grids disagree on the room.
    note: str | None = None


def frozen_groups(class_tt: ClassTimetable, lab: LabTimetable) -> list[FrozenGroup]:
    """Excluded lines with a teacher, merged across division grids.

    An elective line ('NLP / PE-I-A / RK / 606-4') is printed in every TE grid;
    it is one session. Where the grids disagree on the room, the lab timetable's
    line for the same slot settles it if it names exactly one room; otherwise
    the room is left empty. Either way the disagreement is reported.
    """
    groups: dict[tuple, list[Entry]] = {}
    for e in class_tt.entries:
        if e.excluded and e.subject_raw:
            key = (e.day, tuple(e.periods), subject_key(e.subject_raw),
                   canonical_group(e.elective_group), e.faculty_initials_raw)
            groups.setdefault(key, []).append(e)
    out: list[FrozenGroup] = []
    for key, entries in groups.items():
        rooms = list(dict.fromkeys(e.room_raw for e in entries if e.room_raw))
        if len({label_key(r) for r in rooms}) <= 1:
            out.append(FrozenGroup(entries, rooms[0] if rooms else None))
            continue
        day, periods, subject, group, initials = key
        lab_rooms = list(dict.fromkeys(
            le.room_label for le in lab.entries
            if le.kind == "elective" and le.day == day and tuple(le.periods) == periods
            and subject_key(le.subject_raw or "") == subject
            and canonical_group(le.elective_group) == group
            and le.faculty_initials_raw == initials
        ))
        chosen = lab_rooms[0] if len(lab_rooms) == 1 else None
        seen = ", ".join(f"{e.division} {e.room_raw!r}" for e in entries)
        settled = f"the lab timetable names {chosen!r}; used" if chosen else \
            f"the lab timetable names {lab_rooms or 'nothing'}; room left empty"
        out.append(FrozenGroup(entries, chosen,
                               f"{entries[0].raw!r}: the grids disagree on the room ({seen}); "
                               + settled))
    return out


def collect(s: Sources) -> list[Anomaly]:
    out: list[Anomaly] = []
    scheme_file = SCHEME_YAML.name
    for semester in s.scheme.semesters:
        for course in semester.courses:
            if course.include is False:
                out.append(Anomaly(
                    "scheme_excluded", scheme_file, f"Semester {semester.semester} {course.code}",
                    f"{course.code} {course.name}: {course.exclude_reason}", "D3",
                ))
        if semester.note:
            out.append(Anomaly("scheme_note", scheme_file, f"Semester {semester.semester}",
                               semester.note, "D3"))

    for f in s.inventory.findings:
        source = (LAB_CAPACITIES_YAML if f.location.startswith(LAB_CAPACITIES_YAML.name)
                  else CLASSROOMS_XLSX).name
        out.append(Anomaly(f.category, source, f.location, f.message, f.resolution))

    class_file = EVEN_CLASS_FILE.name
    for a in s.class_tt.anomalies:
        out.append(Anomaly(a.kind, class_file, f"{a.division} {a.where}", a.detail,
                           _class_resolution(a.kind, a.division, a.detail)))
    for e in s.class_tt.entries:
        if e.excluded:
            out.append(_exclusion(e))
        elif e.scheme_code == SMCS:
            out.append(Anomaly("frozen_d26", class_file, f"{e.division} {e.where}",
                               f"{e.raw!r}: SMCS runs parallel to FOM - II; frozen at its slot",
                               "D26"))
        elif is_d44(e, s):
            out.append(Anomaly("frozen_d44", class_file, f"{e.division} {e.where}",
                               f"{e.raw!r}: {teacher(e, s)} is not in Faculty___Subjects.xlsx, "
                               "so not CE faculty; frozen at its slot with its cohort, teacher "
                               "and room", "D44"))
    out += lecture_rooms(s)
    for g in frozen_groups(s.class_tt, s.lab):
        if g.note:
            out.append(Anomaly("frozen_room_conflict", class_file,
                               ", ".join(f"{e.division} {e.where}" for e in g.entries),
                               g.note, NEEDS_HUMAN))

    lab_file = s.lab.source
    out += [Anomaly(f.category, lab_file, f.location, f.message, f.resolution)
            for f in s.lab.findings]
    both = f"{class_file} + {lab_file}"
    out += [Anomaly(f.category, both, f.location, f.message, f.resolution) for f in s.cross]
    out += [Anomaly(f.category, s.faculty_tt.source, f.location, f.message, f.resolution)
            for f in s.faculty_tt.findings]
    out += [Anomaly(f.category, "EVEN class + lab + faculty timetables", f.location, f.message,
                    f.resolution) for f in s.block_findings]
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def counts(anomalies: list[Anomaly]) -> dict[str, object]:
    return {
        "total": len(anomalies),
        "needs_human": sum(a.resolution == NEEDS_HUMAN for a in anomalies),
        "by_resolution": dict(sorted(Counter(a.resolution for a in anomalies).items())),
        "by_category": dict(Counter(a.category for a in anomalies)),
    }


def to_json(anomalies: list[Anomaly]) -> str:
    data = {
        "generated_by": "python -m ingestion.anomalies",
        "counts": counts(anomalies),
        "anomalies": [asdict(a) for a in anomalies],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def format_report(s: Sources, anomalies: list[Anomaly]) -> str:
    rule = "=" * 78
    c = counts(anomalies)
    out = [
        "Chronos - EVEN anomaly report, SE and TE (generated by `python -m ingestion.anomalies`)",
        "",
        "Sources: data/reference/teaching_scheme.yaml, data/real/classrooms.xlsx,",
        "data/real/lab_capacities.yaml and the EVEN class, lab and faculty timetables.",
        "Each anomaly: category, source file, location, message, and the ROADMAP decision",
        "that resolves it, or 'needs human'. Nothing is repaired (CONTEXT.md 3.5).",
        "Full detail: data/generated/anomalies_even.json (gitignored).",
        "",
        rule,
        "1. Summary",
        rule,
        f"  total {c['total']}, needs human {c['needs_human']}",
        "  by resolution: " + ", ".join(f"{k} {v}" for k, v in c["by_resolution"].items()),
        "  by category:",
    ]
    out += [f"    {k:<36} {v:>4}" for k, v in c["by_category"].items()]
    out.append("")

    out += [rule, "2. Lab utilisation: printed vs computed (coffee break excluded)", rule]
    for t in s.lab.tables:
        if t.printed is None:
            out.append(f"  t{t.index:<2} {t.room_label or '?':<7} no utilisation line")
            continue
        num, den, pct = t.printed
        mark = "match" if t.matches_printed else "MISMATCH"
        out.append(f"  t{t.index:<2} {t.room_label:<7} printed {num:>2}/{den} = {pct:>6.2f} %"
                   f"   computed {t.occupied:>2}/{den} = {t.computed_percent:>6.2f} %   {mark}")
    out.append("")

    out += [rule, "3. Faculty load lines: printed vs computed (D11, D23)", rule]
    for page in s.faculty_tt.pages:
        load = s.faculty_tt.loads.get(page.member or "")
        computed = f"{load.theory}T+{load.practical_total}P={load.total}" if load else "none"
        out.append(f"  t{page.table:<2} {page.name_raw:<26} printed {page.load_raw or '-':<14}"
                   f" computed {computed}")
    out.append("")

    out += [rule, "4. Anomalies by source and category", rule]
    for source in dict.fromkeys(a.source_file for a in anomalies):
        mine = [a for a in anomalies if a.source_file == source]
        out.append(f"  ## {source} ({len(mine)})")
        for category in dict.fromkeys(a.category for a in mine):
            group = [a for a in mine if a.category == category]
            out.append(f"  [{category}] ({len(group)})")
            for a in group:
                out.append(f"    {a.location}")
                out.append(f"      {a.message}")
                out.append(f"      -> {a.resolution}")
        out.append("")
    return "\n".join(out)


def build() -> tuple[Sources, list[Anomaly], str]:
    s = load_sources()
    anomalies = collect(s)
    return s, anomalies, format_report(s, anomalies)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="report path")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="JSON path")
    args = parser.parse_args(argv)
    _, anomalies, report = build()
    args.out.write_text(report, encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(to_json(anomalies), encoding="utf-8")
    print(f"wrote {args.out}\nwrote {args.json}")


if __name__ == "__main__":
    main()
