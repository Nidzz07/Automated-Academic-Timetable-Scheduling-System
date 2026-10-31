# Constraint coverage: Chronos vs FET (S16e)

2026-10-31 · Dhruv (with Claude Code) · branch `docs/srs-uml`. FET is "free software for
automatically scheduling the timetable of a school, high-school or university", licensed under
the GNU Affero General Public License version 3 ([FET homepage](https://lalescu.ro/liviu/fet/)).

Every FET cell rests on FET's own pages, read on 2026-10-31:

| Short name | Page |
|---|---|
| Features | https://lalescu.ro/liviu/fet/features.html (FET's list of constraints and features) |
| Instructions | https://lalescu.ro/liviu/fet/doc/en/instructions.html |
| FAQ | https://lalescu.ro/liviu/fet/doc/en/faq.html |
| Algorithm | https://lalescu.ro/liviu/fet/doc/en/generation-algorithm-description.html |

Which FET version those pages describe was not checked, and FET itself was not run. **Not
checked** marks a claim those pages do not settle. "Yes" means FET's pages name a way to express
the requirement, not that the result matches Chronos's exactly. Chronos's rules are in
[docs/srs.md](srs.md) §6.

| Chronos requirement or feature | FET | FET constraint or feature | FET citation | Chronos file |
|---|---|---|---|---|
| H1 no faculty clash | Yes | Basic constraint C1: "a list of pairs of activities which cannot be simultaneous", for example because they share "the same teacher or the same students" | Algorithm | `solver/graph.py` (FACULTY edges), `solver/backtracking.py`, `solver/validate.py` (`FACULTY_CLASH`) |
| H2 no division or batch clash (a division blocks its batches) | Yes | The same C1; students are "organized into sets: years, groups and subgroups", and "FET allows overlapping years and groups and non-overlapping subgroups" | Algorithm; Features | `solver/graph.py` (COHORT edges from `db/export_edge_list.py`), `solver/validate.py` (`COHORT_CLASH`) |
| H3 no room clash beyond capacity (a lab holds several batches) | Partly | "Each room can host a single activity at the same time"; a large room hosting several activities is modelled as more rooms with preferred-rooms constraints | Instructions | `solver/backtracking.py` (`_room_is_available`, sub-rooms), `solver/validate.py` (`ROOM_OCCUPANCY`) |
| H4 room capacity ≥ group size | Yes | Room capacity: "if capacity of room is too low for the number of students in S FET cannot find timetable". Not listed on the features page | FAQ | `solver/backtracking.py` (`_room_suits`), `solver/validate.py` (`ROOM_CAPACITY`) |
| H5 practicals in labs, lectures in classrooms | Partly | "Preferred room(s)" for a subject, an activity tag, a subject and tag, or individually for a (sub)activity; no room type is documented | Features | `solver/backtracking.py` (`_room_suits`), `solver/validate.py` (`ROOM_TYPE`) |
| H6 a lab block's batches start together over contiguous periods | Yes | "Same starting time/day/hour" for a set of activities; an activity's hours run together (a two-hour activity is "before or after the break with all the hours of it") | Features; FAQ | `solver/backtracking.py` (lab blocks placed jointly), `solver/validate.py` (`LAB_CONTIGUITY`) |
| H7 breaks never used | Yes | "Break periods" | Features | `solver/slots.py` (teaching periods only), `solver/graph.py` (`slot_is_open`) |
| H8 each session placed exactly once | Yes | The algorithm "must put each activity at a time slot, respecting constraints" | Algorithm | `solver/backtracking.py`, `solver/validate.py` (a missing or duplicated session is a `ValueError`) |
| S-GAP student free gaps (soft, counted and weighted) | Yes | Students sets: "Max gaps per day/week", a maximum with a weight rather than a count | Features (weights: FAQ, "lower the weight of this constraint from 99% to 90% or less") | `solver/scoring.py` (`_student_gaps`), `solver/improve.py`, `solver/rules/quality_rules.yaml` |
| S-B2B teacher back-to-back (soft) | Partly | Teachers: "Max hours daily/continuously" | Features | `solver/scoring.py` (`_back_to_back`) |
| S-LOAD16 teachers above 16 h a week (a flag) | No | No weekly-hours constraint for teachers is listed; the features page lists daily hours and days per week | Features | `solver/scoring.py` (`_load_above`) |
| FAC_LOAD_IMBALANCE uneven days for a teacher | Partly | Teachers: "Max/min days per week", "Min hours daily", "Max hours daily/continuously"; no dispersion measure is documented | Features | `solver/scoring.py` (`_daily_load_spread`) |
| Per-year lunch (P5 SE, P4 TE, D6) | Partly | "Break periods" apply to every students set; students sets have "Not available periods". No per-year break is documented | Features | lunch pins in the edge list (`db/export_edge_list.py`), `solver/graph.py` (`slot_is_open`) |
| Lab blocks across the coffee break (D7) | No, with the break declared | "No, the activity must respect the break, so it is before or after the break with all the hours of it"; the FAQ also says one "can choose to not add the break constraint" | FAQ | `solver/slots.py` (`SlotGrid` adjacency joins P1 and P3), `solver/backtracking.py` (`_contiguous_start_slots`) |
| Split labs: sub-rooms, a whole lab locking its sub-rooms (D8, D58) | Partly | Several rooms with preferred-rooms constraints stand in for one large room. **Not checked**: a whole room and its parts locking each other | Instructions | `solver/backtracking.py` (`_room_is_available`, `_room_is_pinned`, `prefer_sub_rooms`), `solver/validate.py` |
| Frozen items (electives, MDM, out-of-scope sessions, exams; D24, D35, D37) | Yes | "a locked activity is never rescheduled"; a compulsory `ConstraintActivityPreferredStartingTime` "means that you fixed that activity"; "A single preferred starting time" | FAQ; Features | pins (`pinned_occupancy`, `solver/graph.py`), `fixed_slot` |
| Combined lectures (two divisions together; Chronos splits them per division, D40) | Yes | "Possibility of adding multiple teachers and students sets for each activity"; the FAQ: "you can add several students sets ... and several teachers per activity" | Features; FAQ | Chronos schedules one lecture per division (D40; `ingestion/emit_v2.py`: "every in-scope lecture and tutorial (one per division") |
| Faculty unavailability (D36) and absences | Yes | Teachers: "Not available periods" | Features | `faculty_availability` in the edge list; `solver/graph.py`; `solver/repair.py` (`faculty_unavailable` change) |
| Minimal-change repair after a change | Partly | "a locked activity is never rescheduled"; moving one activity in a locked ("fixed") timetable can make it impossible. No minimal-change repair is documented | FAQ | `solver/repair.py` (freeze and expand, restore, `improve` on moved sessions only) |
| Explanation of impossible changes, with verified relaxations | Partly | "In some cases FET will report impossible activity A1"; the FAQ advises removing other constraints until a timetable is possible. No minimal conflicting set and no verified relaxation are documented | FAQ | `solver/mus.py` (`explain`), `solver/presolve.py` |
| Substitutes from SPIT's faculty–subject sheets (D53) | No | Substitute teachers, absences and qualifications appear on neither the features page nor the FAQ | Features; FAQ | `solver/repair.py` (`substitute_candidates`, `substitute_faculty`), `backend/app/service.py` (`substitutes`, `qualified`), `data/instances/even-2025-26/qualifications.json` |
| Accepted changes that accumulate (D52, D56) | No | Saving or keeping a history of changes appears on neither page; results are "exported into HTML, XML and CSV formats" | Features; FAQ | `backend/app/service.py` (`_built`, `built_with`, `_official`, `clear_changes`), `db/models.py` (`SolveJob`) |
| Roles and audit (administrator, coordinator, faculty, student; D50) | No | Users, accounts, permissions and an audit log appear on neither the features page nor the FAQ | Features; FAQ | `backend/app/auth.py`, `backend/app/deps.py`, `backend/app/routers.py`, `backend/app/service.py` (`_audit`), `frontend/src/components/auth/AuditLog.tsx` |

## What the table says

- **FET expresses most of Chronos's hard rules.** H1, H2, H4 and H6–H8 are covered, and
  H3 and H5 through preferred rooms and extra rooms. Its features page lists more time and space
  constraints than Chronos uses. Chronos does not claim to be a more general timetabler.
- **Some of Chronos's rules have no documented FET equivalent.** These are SPIT-specific: lab
  blocks across the coffee break while the break stays a break, a per-year lunch, a whole split
  lab locking its batch places, and a weekly-hours flag.
- **FET's pages document nothing for Chronos's own contributions** (`docs/CONTEXT.md` §1):
  - minimal-change repair;
  - an explanation of impossible changes with a verified relaxation;
  - substitutes taken from the institution's sheets;
  - changes that accumulate;
  - roles and an audit log.

  On the first two, the FAQ documents only locked activities and reports of an impossible
  activity.

**Not checked, listed for the team:** whether FET can make a whole room and its parts lock each
other, as Chronos's split labs do; and which FET version these pages describe.
