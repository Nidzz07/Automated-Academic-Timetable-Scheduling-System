"""Build the real EVEN SE+TE instance as one ingestion.v2 payload (ROADMAP S7).

Combines the class, lab and faculty timetables, classrooms.xlsx and
lab_capacities.yaml into ``data/generated/ingestion_v2_even.json``, validated
against ``contracts/ingestion_v2.schema.json``. Any error fails loudly; nothing
is written then. No database is touched (the seeder is S9).

What goes in:

- divisions and batches: the eight SE/TE grids, 80 and 20 students (D5);
- rooms: the D8 labs (sub-rooms per lab_capacities.yaml) and the D10
  classrooms (:func:`ingestion.lab_tt.room_inventory`);
- faculty: the 41-member list, with the printed load line where the faculty
  timetable has one; initials from the SE/TE legends, plus SRD per D25;
- observed sessions: every in-scope lecture and tutorial (one per division,
  D23) and practical (one per batch), and every frozen item that has a teacher:
  electives and FOM - II (D24, D26, merged across grids), SMCS (D26) and the
  MDM labs of the lab timetable (D24);
- lab blocks: one per class-timetable cell of in-scope practicals;
- pinned blocks: the coffee break (P2, once per day), each year's lunch (row 8:
  one per division per day) and the label-only frozen items (MDM, HSS, LLC,
  student activity, major project).

ingestion.v2 cannot mark a session as frozen, so the ids of every frozen
session and pinned block are written beside the payload to
``data/generated/ingestion_v2_even.frozen.json``.

Validator rule beyond the schema: no session may occupy its own year's lunch.

Run from the repo root::

    python -m ingestion.emit_v2
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from ingestion.anomalies import (
    FOM_II,
    SMCS,
    Sources,
    frozen_groups,
    load_sources,
)
from ingestion.class_tt import (
    BATCHES,
    COFFEE_PERIOD,
    DAYS,
    EVEN_CLASS_FILE,
    LUNCH_PERIOD,
    PERIOD_TIMES,
    Entry,
)
from ingestion.initials_legend import extract_legends, name_key
from ingestion.lab_tt import (
    D25_INITIALS,
    RoomRef,
    class_resolution,
    d25_member,
    division_key,
    load_lab_capacities,
    normalise_room,
)
from ingestion.seed_legends import legend_scope
from ingestion.seed_reference import DEPARTMENT_CODE, DEPARTMENT_NAME, REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "contracts" / "ingestion_v2.schema.json"
DEFAULT_JSON = REPO_ROOT / "data" / "generated" / "ingestion_v2_even.json"
FROZEN_JSON = REPO_ROOT / "data" / "generated" / "ingestion_v2_even.frozen.json"

#: D5: each division = 80 students; batch = 20 students; 4 batches per division.
DIVISION_STRENGTH = 80
BATCH_STRENGTH = 20
#: Periods a room can be used in some year: every period but the coffee break.
ROOM_PERIODS_PER_WEEK = len(DAYS) * (len(PERIOD_TIMES) - 1)

_PINNED_KIND = (
    (re.compile(r"MDM"), "mdm"),
    (re.compile(r"HSS"), "hss"),
    (re.compile(r"LLC"), "llc"),
    (re.compile(r"project"), "project"),
    (re.compile(r"student activity"), "activity"),
)


class InstanceError(ValueError):
    """The payload breaks the schema or a validator rule. Lists every problem."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def covered(start: int, duration: int) -> list[int]:
    """Wall-clock periods a session starting at ``start`` occupies (D7: it may
    span the coffee break, so P2 is skipped; a lunch period is not)."""
    periods: list[int] = []
    p = start
    while len(periods) < duration and p in PERIOD_TIMES:
        if p != COFFEE_PERIOD:
            periods.append(p)
        p += 1
    return periods


def _duration(periods: list[int]) -> int:
    return sum(p != COFFEE_PERIOD for p in periods)


@dataclass
class Builder:
    s: Sources
    payload: dict = field(default_factory=dict)
    #: session id -> lecture | tutorial | practical | frozen
    kinds: dict[str, str] = field(default_factory=dict)
    frozen: list[dict] = field(default_factory=list)
    subjects: dict[str, dict] = field(default_factory=dict)
    cohorts: dict[str, dict] = field(default_factory=dict)

    # ------------------------------------------------------------------ ids
    def division_id(self, key: str) -> str:
        return f"div-{key.lower()}"

    def batch_id(self, key: str, batch: str) -> str:
        return f"bat-{key.lower()}-{batch.lower()}"

    def faculty_id(self, name: str) -> str:
        return f"fac-{slug(name_key(name))}"

    def room_ids(self, ref: RoomRef | None) -> tuple[str | None, str | None]:
        if ref is None or ref.room is None:
            return None, None
        return f"room-{ref.room.lower()}", f"sub-{ref.sub_room.lower()}" if ref.sub_room else None

    # -------------------------------------------------------------- parts
    def build(self) -> dict:
        s = self.s
        p = self.payload
        p["schema_version"] = "ingestion.v2"
        p["source_file"] = " + ".join(
            (EVEN_CLASS_FILE.name, s.lab.source, s.faculty_tt.source)
        )
        p["semester"] = {"code": "EVEN", "academic_year": "2025-2026", "term": "Term: II (Even)"}
        p["departments"] = [{"id": "dept-ce", "code": DEPARTMENT_CODE, "name": DEPARTMENT_NAME}]
        p["programmes"] = [
            {"id": "prog-ce-btech", "department_id": "dept-ce", "code": "BTECH", "name": "B.Tech"}
        ]
        self._divisions()
        self._rooms()
        self._faculty()
        p["subjects"] = []
        p["qualifications"] = []
        p["cohorts"] = []
        p["observed_sessions"] = []
        p["lab_blocks"] = []
        p["pinned_blocks"] = []
        p["anomalies"] = []
        self._sessions()
        self._mdm_labs()
        self._lab_blocks()
        self._pinned()
        p["subjects"] = list(self.subjects.values())
        p["cohorts"] = list(self.cohorts.values())
        p["qualifications"] = self._qualifications()
        self._anomalies()
        return p

    def _divisions(self) -> None:
        years = {sem.year: sem.semester for sem in self.s.scheme.semesters}
        self.divisions: dict[str, str] = {}  # key -> label as printed
        divs, batches = [], []
        for t in self.s.class_tt.tables:
            if not t.parsed or t.division is None:
                continue
            key = division_key(t.division)
            self.divisions[key] = t.division
            divs.append({
                "id": self.division_id(key), "programme_id": "prog-ce-btech",
                "semester_number": years[key[:2]], "label": t.division,
                "strength": DIVISION_STRENGTH,
            })
            for b in BATCHES:
                batches.append({"id": self.batch_id(key, b), "division_id": self.division_id(key),
                                "label": b, "strength": BATCH_STRENGTH})
        self.payload["divisions"] = divs
        self.payload["batches"] = batches

    def division_cohort(self, key: str) -> str:
        cid = f"coh-{key.lower()}"
        self.cohorts.setdefault(cid, {
            "id": cid, "cohort_type": "division", "label": self.divisions[key],
            "member_batch_ids": [self.batch_id(key, b) for b in BATCHES],
        })
        return cid

    def batch_cohort(self, key: str, batch: str) -> str:
        cid = f"coh-{key.lower()}-{batch.lower()}"
        self.cohorts.setdefault(cid, {
            "id": cid, "cohort_type": "batch", "label": f"{self.divisions[key]} {batch}",
            "member_batch_ids": [self.batch_id(key, batch)],
        })
        return cid

    def group_cohort(self, label: str, keys: list[str], suffix: str = "") -> str:
        """A cross-division group (elective, FOM - II, MDM): all batches of its
        divisions, which D24 blocks."""
        cid = f"coh-grp-{slug(label)}" + (f"-{suffix}" if suffix else "")
        cohort = self.cohorts.setdefault(cid, {
            "id": cid, "cohort_type": "elective", "label": label, "member_batch_ids": [],
        })
        for key in keys:
            for b in BATCHES:
                if self.batch_id(key, b) not in cohort["member_batch_ids"]:
                    cohort["member_batch_ids"].append(self.batch_id(key, b))
        return cid

    def _rooms(self) -> None:
        self.payload["rooms"] = [
            {
                "id": f"room-{r.code.lower()}", "code": r.code, "capacity": r.capacity,
                "room_type": r.room_type, "separation": r.separation,
                "sub_rooms": [{"id": f"sub-{c.lower()}", "code": c, "capacity": cap}
                              for c, cap in r.sub_rooms],
            }
            for r in self.s.inventory.rooms.values()
        ]

    def _faculty(self) -> None:
        s = self.s
        pages = {pg.member: pg for pg in s.faculty_tt.pages if pg.member}
        rows = []
        for name in sorted(s.faculty.ce_faculty, key=name_key):
            page = pages.get(name)
            rows.append({
                "id": self.faculty_id(name), "department_id": "dept-ce", "full_name": name,
                "theory_hours": page.theory if page else None,
                "practical_hours": page.practical if page else None,
                "total_hours": page.total if page else None,
            })
        self.payload["faculty"] = rows

        initials = []
        for legend in extract_legends(EVEN_CLASS_FILE):
            scope = legend_scope(legend)
            key = division_key(scope.division)
            if key not in self.divisions:
                continue
            by_init = s.faculty.by_scope[scope]
            for entry in legend.entries:
                for name in by_init.get(entry.initials, []):
                    row = {
                        "faculty_id": self.faculty_id(name), "initials": entry.initials,
                        "division_id": self.division_id(key), "source": "legend",
                        "is_ambiguous": len(by_init[entry.initials]) > 1,
                        "legend_ref": f"EVEN t{legend.table_index} {scope.division}",
                    }
                    if not any(r["faculty_id"] == row["faculty_id"]
                               and r["initials"] == row["initials"]
                               and r["division_id"] == row["division_id"] for r in initials):
                        initials.append(row)
        initials.append({
            "faculty_id": self.faculty_id(d25_member(s.faculty)), "initials": D25_INITIALS,
            "division_id": None, "source": "manual", "is_ambiguous": False, "legend_ref": None,
        })
        self.payload["faculty_initials"] = initials

    def subject(self, e_subject: str, code: str | None, kind: str) -> str:
        """Subject id; scheme courses by scheme code, other subjects as printed."""
        if code:
            course = next(c for c in self.s.scheme.courses() if c.code == code)
            sid = f"subj-{code.lower()}"
            session_type = "both" if (course.L or course.T) and course.P else \
                "lab" if course.P else "theory"
            self.subjects.setdefault(sid, {"id": sid, "department_id": "dept-ce", "code": code,
                                           "name": course.name, "session_type": session_type})
            return sid
        sid = f"subj-{slug(e_subject)}"
        row = self.subjects.setdefault(sid, {"id": sid, "department_id": "dept-ce",
                                             "code": e_subject, "name": e_subject,
                                             "session_type": kind})
        if row["session_type"] != kind:
            row["session_type"] = "both"
        return sid

    def faculty_fields(self, status: str | None, candidates: list[str],
                       initials: str | None) -> dict:
        if status in ("resolved", "resolved_d25"):
            return {"faculty_initials_raw": initials, "faculty_id": self.faculty_id(candidates[0])}
        if status == "ambiguous":
            return {"faculty_initials_raw": initials, "faculty_id": None,
                    "faculty_candidates": [self.faculty_id(n) for n in candidates]}
        return {"faculty_initials_raw": initials, "faculty_id": None}

    def add_session(self, sid: str, kind: str, subject_id: str, faculty: dict, cohort_id: str,
                    room: RoomRef | None, day: str, periods: list[int], session_type: str,
                    source_cell: str) -> dict:
        room_id, sub_room_id = self.room_ids(room)
        row = {
            "id": sid, "subject_id": subject_id, **faculty, "cohort_id": cohort_id,
            "room_id": room_id, "sub_room_id": sub_room_id, "day": DAYS.index(day),
            "period": periods[0], "duration_periods": _duration(periods),
            "session_type": session_type, "source_cell": source_cell,
        }
        if "faculty_candidates" in row:  # keep the schema's key order readable
            row["faculty_candidates"] = row.pop("faculty_candidates")
        self.payload["observed_sessions"].append(row)
        self.kinds[sid] = kind
        return row

    def _sessions(self) -> None:
        s = self.s
        inv = s.inventory
        self.practicals: dict[tuple[int, int, int], list[tuple[str, Entry]]] = {}
        for e in s.class_tt.entries:
            if e.subject_raw is None or e.excluded:
                continue
            if e.faculty_initials_raw is None:
                raise InstanceError(f"{e.division} {e.where}: in-scope line with no initials")
            key = division_key(e.division)
            sid = f"obs-t{e.table}-r{e.row}-c{e.col}-l{e.line}"
            practical = e.session_type == "practical"
            cohort = self.batch_cohort(key, e.batch) if practical else self.division_cohort(key)
            frozen = e.scheme_code == SMCS
            room = normalise_room(e.room_raw, inv) if e.room_raw else None
            self.add_session(
                sid, "frozen" if frozen else e.session_type,
                self.subject(e.subject_raw, e.scheme_code, "lab" if practical else "theory"),
                self.faculty_fields(*class_resolution(e, s.faculty), e.faculty_initials_raw),
                cohort, room, e.day, e.periods, "lab" if practical else "theory", e.raw,
            )
            if frozen:
                self.frozen.append({"id": sid, "kind": "observed_session", "resolution": "D26",
                                    "label": e.raw})
            if practical:
                self.practicals.setdefault((e.table, e.row, e.col), []).append((sid, e))

        for group in frozen_groups(s.class_tt, s.lab):
            e = group.entries[0]
            if e.faculty_initials_raw is None:
                raise InstanceError(f"{e.division} {e.where}: frozen line with no initials")
            keys = list(dict.fromkeys(division_key(g.division) for g in group.entries))
            label = e.elective_group or e.subject_raw
            practical = e.elective_group is not None
            sid = f"obs-t{e.table}-r{e.row}-c{e.col}-l{e.line}"
            room = normalise_room(group.room_raw, inv) if group.room_raw else None
            self.add_session(
                sid, "frozen", self.subject(e.subject_raw, None, "lab" if practical else "theory"),
                self.faculty_fields(*class_resolution(e, s.faculty), e.faculty_initials_raw),
                self.group_cohort(label, keys), room, e.day, e.periods,
                "lab" if practical else "theory", e.raw,
            )
            self.frozen.append({"id": sid, "kind": "observed_session",
                                "resolution": "D26" if e.subject_raw == FOM_II else "D24",
                                "label": e.raw})

    def _mdm_labs(self) -> None:
        """MDM cells of the lab timetable: frozen with their teacher and room (D24).

        The lab timetable names no division for them, so each cell's group is
        every division whose class grid has an MDM block in the same slot.
        """
        s = self.s
        mdm_slots: dict[tuple[str, int], set[str]] = {}
        for e in s.class_tt.entries:
            if e.excluded and e.subject_raw is None and "MDM" in (e.exclude_reason or ""):
                for p in e.periods:
                    mdm_slots.setdefault((e.day, p), set()).add(division_key(e.division))
        for le in s.lab.entries:
            if le.kind != "mdm":
                continue
            keys = sorted({k for p in le.periods for k in mdm_slots.get((le.day, p), ())})
            if not keys:
                raise InstanceError(f"{le.where}: MDM cell {le.raw!r} matches no class-grid MDM "
                                    "block, so no division can be blocked")
            sid = f"obs-lab-t{le.table}-r{le.row}-c{le.col}"
            ref = RoomRef(le.room_label, le.room, le.sub_room)
            if le.faculty_initials_raw is None:
                raise InstanceError(f"{le.where}: MDM cell with no initials")
            self.add_session(
                sid, "frozen", self.subject(le.subject_raw or le.raw, None, "lab"),
                self.faculty_fields(le.faculty_status, le.faculty_candidates,
                                    le.faculty_initials_raw),
                self.group_cohort(le.subject_raw or le.raw, keys, sid.removeprefix("obs-")),
                ref, le.day, le.periods,
                "lab", le.raw,
            )
            self.frozen.append({"id": sid, "kind": "observed_session", "resolution": "D24",
                                "label": le.raw})

    def _lab_blocks(self) -> None:
        for (table, row, col), members in self.practicals.items():
            e = members[0][1]
            self.payload["lab_blocks"].append({
                "id": f"lab-t{table}-r{row}-c{col}",
                "division_id": self.division_id(division_key(e.division)),
                "day": DAYS.index(e.day), "start_period": e.periods[0],
                "duration_periods": _duration(e.periods),
                "parallel_session_ids": [sid for sid, _ in members],
            })

    def _pinned(self) -> None:
        pinned = self.payload["pinned_blocks"]
        for d, day in enumerate(DAYS):
            pinned.append({"id": f"pin-coffee-{day[:3].lower()}", "label": "SHORT BREAK",
                           "cohort_id": None, "day": d, "period": COFFEE_PERIOD,
                           "duration_periods": 1, "kind": "break"})
        for key in self.divisions:
            for d, day in enumerate(DAYS):
                pinned.append({"id": f"pin-lunch-{key.lower()}-{day[:3].lower()}",
                               "label": "BREAK", "cohort_id": self.division_cohort(key), "day": d,
                               "period": LUNCH_PERIOD[key[:2]], "duration_periods": 1,
                               "kind": "break"})
        for e in self.s.class_tt.entries:
            if not e.excluded or e.subject_raw is not None:
                continue
            reason = e.exclude_reason or ""
            kind = next((k for pattern, k in _PINNED_KIND if pattern.search(reason)), None)
            if kind is None:
                raise InstanceError(f"{e.division} {e.where}: no pinned kind for {e.raw!r} "
                                    f"({e.exclude_reason})")
            pid = f"pin-t{e.table}-r{e.row}-c{e.col}-l{e.line}"
            pinned.append({"id": pid, "label": e.raw.replace("\n", " | "),
                           "cohort_id": self.division_cohort(division_key(e.division)),
                           "day": DAYS.index(e.day), "period": e.periods[0],
                           "duration_periods": _duration(e.periods), "kind": kind})
            self.frozen.append({"id": pid, "kind": "pinned_block", "resolution": "D24",
                                "label": e.raw.replace("\n", " | ")})

    def _qualifications(self) -> list[dict]:
        pairs = dict.fromkeys(
            (row["faculty_id"], row["subject_id"])
            for row in self.payload["observed_sessions"] if row["faculty_id"]
        )
        return [{"faculty_id": f, "subject_id": sub, "source": "observed"} for f, sub in pairs]

    def _anomalies(self) -> None:
        s = self.s
        out = self.payload["anomalies"]
        class_file, lab_file = EVEN_CLASS_FILE.name, s.lab.source

        def add(code: str, message: str, source: str, cell: str | None,
                severity: str = "warning") -> None:
            out.append({"severity": severity, "code": code, "message": message,
                        "source_file": source, "source_cell": cell})

        for f in s.inventory.findings:
            if f.category == "duplicate_room":
                add("DUPLICATE_ROOM", f.message, "classrooms.xlsx", None)
            elif f.category == "unknown_room_usage":
                add("UNKNOWN_ROOM_USAGE", f.message, "classrooms.xlsx", None)
        malformed = [a.detail for a in s.class_tt.anomalies if a.kind == "malformed_line"]
        for row in self.payload["observed_sessions"]:
            source = lab_file if row["id"].startswith("obs-lab-") else class_file
            cell = row["source_cell"]
            if row["faculty_id"] is None and "faculty_candidates" not in row:
                add("UNRESOLVED_FACULTY_INITIALS",
                    f"'{row['faculty_initials_raw']}' names nobody in this division's legend "
                    "(or the cell names no division); the session has no teacher",
                    source, cell)
            elif "faculty_candidates" in row:
                add("AMBIGUOUS_FACULTY_INITIALS",
                    f"'{row['faculty_initials_raw']}' names {len(row['faculty_candidates'])} "
                    "people; none is chosen", source, cell)
            if any(repr(cell) in m for m in malformed):
                add("UNPARSEABLE_CELL", f"{cell!r}: no '/' between initials and room; read anyway",
                    source, cell)
            labels = re.findall(r"\d{3}\s*-\s*\w", cell)
            for label in labels:
                note = normalise_room(label, s.inventory).note
                if note and note[0] == "subroom_beyond_split":
                    add("SUBROOM_EXCEEDS_SEPARATION", note[1], source, cell)
        for row in self.payload["faculty"]:
            if row["theory_hours"] is None and row["practical_hours"] is None:
                add("MISSING_WORKLOAD",
                    f"{row['full_name']}: no load line in the faculty individual timetable",
                    s.faculty_tt.source, None)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def lunch_violations(payload: dict) -> list[str]:
    """Sessions occupying their own year's lunch (D6, row 8)."""
    year = {d["id"]: d["label"][:2] for d in payload["divisions"]}
    division_of = {b["id"]: b["division_id"] for b in payload["batches"]}
    years_of = {
        c["id"]: {year[division_of[b]] for b in c["member_batch_ids"]} for c in payload["cohorts"]
    }
    problems = []
    for row in payload["observed_sessions"]:
        periods = covered(row["period"], row["duration_periods"])
        if len(periods) < row["duration_periods"]:
            problems.append(f"{row['id']}: runs past P9")
        for y in sorted(years_of.get(row["cohort_id"], ())):
            if LUNCH_PERIOD.get(y) in periods:
                problems.append(f"{row['id']} ({row['source_cell']!r}): {y} session in its "
                                f"lunch period P{LUNCH_PERIOD[y]}")
    return problems


def reference_errors(payload: dict) -> list[str]:
    """Every id a row points at exists, and every collection's ids are unique."""
    problems = []
    ids: dict[str, set[str]] = {}
    for name in ("divisions", "batches", "rooms", "faculty", "subjects", "cohorts",
                 "observed_sessions", "lab_blocks", "pinned_blocks"):
        values = [row["id"] for row in payload[name]]
        if len(values) != len(set(values)):
            problems.append(f"{name}: duplicate ids")
        ids[name] = set(values)
    sub_rooms = {s["id"] for r in payload["rooms"] for s in r["sub_rooms"]}
    checks = [
        ("batches", "division_id", "divisions"),
        ("faculty_initials", "faculty_id", "faculty"),
        ("faculty_initials", "division_id", "divisions"),
        ("qualifications", "faculty_id", "faculty"),
        ("qualifications", "subject_id", "subjects"),
        ("observed_sessions", "subject_id", "subjects"),
        ("observed_sessions", "faculty_id", "faculty"),
        ("observed_sessions", "cohort_id", "cohorts"),
        ("observed_sessions", "room_id", "rooms"),
        ("lab_blocks", "division_id", "divisions"),
        ("pinned_blocks", "cohort_id", "cohorts"),
    ]
    for coll, key, target in checks:
        for row in payload[coll]:
            if row.get(key) is not None and row[key] not in ids[target]:
                problems.append(f"{coll}: {key} {row[key]!r} not in {target}")
    for row in payload["observed_sessions"]:
        if row["sub_room_id"] is not None and row["sub_room_id"] not in sub_rooms:
            problems.append(f"observed_sessions: sub_room_id {row['sub_room_id']!r} unknown")
    for c in payload["cohorts"]:
        problems += [f"cohorts: {c['id']} batch {b!r} unknown"
                     for b in c["member_batch_ids"] if b not in ids["batches"]]
    for block in payload["lab_blocks"]:
        problems += [f"lab_blocks: {block['id']} session {sid!r} unknown"
                     for sid in block["parallel_session_ids"]
                     if sid not in ids["observed_sessions"]]
    return problems


def validate(payload: dict) -> None:
    """Schema, references and the lunch rule. Raises :class:`InstanceError`."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    problems = [
        f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(payload)
    ]
    if not problems:
        problems = reference_errors(payload) + lunch_violations(payload)
    if problems:
        raise InstanceError(f"{len(problems)} problem(s):\n  " + "\n  ".join(problems))


# --------------------------------------------------------------------------- #
# Build, summary, output
# --------------------------------------------------------------------------- #


@dataclass
class Instance:
    payload: dict
    kinds: dict[str, str]
    frozen: list[dict]
    sources: Sources


def build(sources: Sources | None = None) -> Instance:
    s = load_sources() if sources is None else sources
    b = Builder(s)
    payload = b.build()
    validate(payload)
    return Instance(payload, b.kinds, b.frozen, s)


def summary(inst: Instance) -> dict[str, object]:
    p = inst.payload
    sessions = p["observed_sessions"]
    by_kind: dict[str, int] = {}
    for kind in inst.kinds.values():
        by_kind[kind] = by_kind.get(kind, 0) + 1
    rooms = {r["id"]: r for r in p["rooms"]}
    places = {r["id"]: max(1, len(r["sub_rooms"])) for r in rooms.values()
              if r["room_type"] == "lab"}
    class_ids = [r["id"] for r in rooms.values() if r["room_type"] == "class"]
    unknown_ids = [r["id"] for r in rooms.values() if r["room_type"] == "unknown"]
    caps = load_lab_capacities()
    lab_places = sum(lab["parallel_batches"] for lab in caps["labs"] if lab["btech_use"])

    theory_demand = sum(row["duration_periods"] for row in sessions
                        if inst.kinds[row["id"]] in ("lecture", "tutorial"))
    lab_demand = sum(row["duration_periods"] for row in sessions
                     if inst.kinds[row["id"]] == "practical")
    frozen_rows = [row for row in sessions if inst.kinds[row["id"]] == "frozen"]
    frozen_class = sum(row["duration_periods"] for row in frozen_rows
                       if row["room_id"] in class_ids)
    frozen_lab = sum(row["duration_periods"] * (1 if row["sub_room_id"] else places[row["room_id"]])
                     for row in frozen_rows if row["room_id"] in places)
    resolution = {"resolved": 0, "ambiguous": 0, "unresolved": 0}
    for row in sessions:
        state = "resolved" if row["faculty_id"] else \
            "ambiguous" if "faculty_candidates" in row else "unresolved"
        resolution[state] += 1
    return {
        "divisions": len(p["divisions"]),
        "batches": len(p["batches"]),
        "sessions_by_type": dict(sorted(by_kind.items())),
        "sessions_faculty": resolution,
        "lab_blocks": len(p["lab_blocks"]),
        "frozen_sessions": len(frozen_rows),
        "frozen_pinned_blocks": sum(f["kind"] == "pinned_block" for f in inst.frozen),
        "break_pinned_blocks": sum(b["kind"] == "break" for b in p["pinned_blocks"]),
        "faculty": len(p["faculty"]),
        "faculty_with_load_line": sum(f["total_hours"] is not None or f["theory_hours"] is not None
                                      or f["practical_hours"] is not None for f in p["faculty"]),
        "faculty_initials_rows": len(p["faculty_initials"]),
        "rooms": {"class": len(class_ids), "unknown": len(unknown_ids), "lab": len(places),
                  "sub_rooms": sum(len(r["sub_rooms"]) for r in rooms.values())},
        "classroom_periods": {
            "demand": theory_demand,
            "supply_class_rooms": len(class_ids) * ROOM_PERIODS_PER_WEEK - frozen_class,
            "supply_with_unknown_rooms":
                (len(class_ids) + len(unknown_ids)) * ROOM_PERIODS_PER_WEEK - frozen_class,
            "frozen_in_class_rooms": frozen_class,
        },
        "lab_batch_place_periods": {
            "demand": lab_demand,
            "supply": lab_places * ROOM_PERIODS_PER_WEEK - frozen_lab,
            "places_per_period": lab_places,
            "frozen_in_labs": frozen_lab,
        },
        "anomalies_in_payload": len(p["anomalies"]),
    }


def dumps(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="payload path")
    parser.add_argument("--frozen", type=Path, default=FROZEN_JSON, help="frozen-ids path")
    args = parser.parse_args(argv)
    inst = build()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(dumps(inst.payload), encoding="utf-8")
    args.frozen.write_text(dumps({
        "generated_by": "python -m ingestion.emit_v2",
        "payload": args.json.name,
        "note": "ingestion.v2 has no frozen flag; these ids are frozen at their slots (D24, D26)",
        "frozen": inst.frozen,
    }), encoding="utf-8")
    print(f"wrote {args.json}\nwrote {args.frozen}")
    print(dumps(summary(inst)), end="")


if __name__ == "__main__":
    main()
