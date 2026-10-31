# Chronos: Software Requirements Specification (S16e)

2026-10-31 · Dhruv (with Claude Code) · branch `docs/srs-uml`. Written against `main` at
commit 7c4d208 (S14s merged, PR #85). There was no earlier SRS in `docs/`: `docs/CONTEXT.md` §7
only lists "proposals, SRS, UML, reports" as what `docs/` would hold. So this is the first one.
Every requirement below names the code that meets it. Anything planned but not built is marked
**planned, not built**.

UML diagrams: [docs/uml.md](uml.md). Comparison with FET: [docs/fet-coverage.md](fet-coverage.md).
Algorithms: [docs/algorithms.md](algorithms.md).

## 1. Purpose

Chronos generates conflict-free weekly timetables for SPIT's Department of Computer Engineering
from the department's real data, and keeps them valid when something changes
(`docs/CONTEXT.md` §1). It reduces timetabling to graph vertex colouring with backtracking, so
any accepted timetable passes an independent validator. Two further capabilities set it apart:

- **Diagnosis:** when no timetable exists, it names a minimal set of conflicting constraints and
  a relaxation verified to restore feasibility.
- **Live rescheduling:** after an absence, a closed room, a drag or a substitution, it repairs
  the official timetable while moving as few sessions as it can.

No machine learning is used anywhere in the decision path; identical input gives identical
output (`docs/CONTEXT.md` §2, rule 1).

## 2. Scope

- **In scope (ROADMAP §2, D2).** Department of Computer Engineering, SPIT. Semester EVEN
  2025-26. Years SE (Semester IV) and TE (Semester VI). One real instance,
  `data/instances/even-2025-26/`, has 156 sessions, 31 lab blocks, 25 rooms and sub-rooms, and
  339 pinned entries (`docs/real-solve-even-2025-26.md` § Instance).
- **Excluded (D3).** Electives, minors, honours, LLC, HSSM, projects, Saturday working,
  institute-wide fixed slots, and courses whose teacher is not CE faculty (D44). Excluded items
  are listed in the anomaly report, never silently dropped. Those printed in the timetable are
  frozen at their slots (D24, D35).
- **The system must** avoid all clashes; respect breaks, lunch, room capacity and lab capacity;
  flag professors' back-to-back lectures; avoid student free gaps; and show a room timetable
  and a free-room view (ROADMAP §2).

## 3. Definitions

| Term | Meaning |
|---|---|
| Session | One lecture, tutorial or practical of one cohort with one teacher; a vertex of the conflict graph (`solver/graph.py`, `Session`). |
| Cohort | A division (80 students) or a batch (20 students, 4 per division) (D5). A division's session blocks all its batches (H2). |
| Lab block | The parallel practicals of a division's batches; they start together and run 2 consecutive teaching periods (D7) (`LabBlock` in `solver/backtracking.py` and `db/models.py`). |
| Split lab | A lab with sub-rooms (`SubRoom`), each one batch place (D8, D30). |
| Pin, frozen item | A `pinned_occupancy` entry: a slot held for teachers, rooms or cohorts that the solver never moves. Lunch, frozen electives and MDM, out-of-scope sessions and exams are all pins (D24, D35, D37, D41). |
| Edge list | The solver's input contract, `contracts/edge_list_v1.schema.json`. |
| `solution.v2` | The solver's output contract: a timetable with its quality block, or an infeasible result with a diagnosis (`contracts/solution_v2.schema.json`). |
| Job | One solve or repair request run in a worker process; a row of `solve_job` (`db/models.py`, `SolveJob`). |
| Official timetable | The solution served at `GET /instances/{id}/solution`: the newest finished solve or accepted repair that is valid for the accepted changes in force, else the committed `solution.json` (D49, D56). |
| Accepted change | An accepted repair's change. Absences, closed rooms and substitutions are included in every later solve and repair; a move is only a placement (D52). |
| P0–P9 | Internal period numbers (D6). The interface shows them as T0–T9 with 12-hour times (D60). |

## 4. Users and roles

Four roles, `db/models.py` `UserRole` and `frontend/src/types/roles.ts` `ROLE_CAPABILITIES`:

| Role | Can do | Enforced by |
|---|---|---|
| Administrator | Everything a coordinator can, plus clear accepted changes and read the audit log | `require_role(UserRole.ADMINISTRATOR)` on `DELETE /instances/{id}/changes` and `GET /audit` (`backend/app/routers.py`, `backend/app/deps.py`) |
| Coordinator | Solve, repair (absence, closed room, drag, substitution), accept a repair, see substitutes | `require_role(ADMINISTRATOR, COORDINATOR)` (`Solver` in `routers.py`) |
| Faculty | Read the timetable; the UI opens on and locks to their own timetable when the account is linked (D50) | Read routes need only a valid token (`current_actor`); the lock is in the UI (`App.tsx`) |
| Student | Read the timetable; the UI opens on and locks to the linked cohort (D50) | As for faculty |

D50: the API does not filter what a role reads, because timetables are not secret. The link is
`app_user.faculty_ref` / `cohort_ref` and travels in the token.

## 5. Functional requirements

Routes are those `backend/app/main.py` includes from `backend/app/routers.py`
(`health`, `auth`, `instances`, `jobs`, `audit`). Screens are under `frontend/src/`. Tests are
the files that exercise each one.

| Id | Requirement | Route | Screen | Tests |
|---|---|---|---|---|
| FR-1 | Log in with a username and password; receive a signed token with the role and the optional faculty or cohort link (D50). An expired or invalid token returns to the login screen. | `POST /auth/login` | `components/auth/LoginScreen.tsx` | `backend/tests/test_auth.py`; `components/auth/__tests__/Auth.test.tsx` |
| FR-2 | List the instances and read an instance's edge list, its names (`display.json`, D41) and its anomaly report. | `GET /instances`, `GET /instances/{id}/edge-list`, `GET /instances/{id}/display`, `GET /instances/{id}/anomalies` | `App.tsx` (instance picker), `components/timetable/AnomalyReport.tsx` | `backend/tests/test_api.py`; `__tests__/AnomalyReport.test.tsx`, `__tests__/RealData.test.tsx` |
| FR-3 | Show the official timetable (D49, D56) as a weekly grid, with lab blocks, combined lectures and pins drawn as such. | `GET /instances/{id}/solution` | `components/timetable/TimetableGrid.tsx`, `ParallelLabBlock.tsx`, `CombinedLectureBlock.tsx`, `PinnedBlock.tsx` | `backend/tests/test_api.py`, `test_fixes.py`; `__tests__/TimetableGrid.test.tsx` |
| FR-4 | Role views: faculty and students see a read-only timetable, opened on their own when linked (D50). | none (UI only) | `components/timetable/RoleSelector.tsx`, `App.tsx` | `__tests__/RoleViews.test.tsx`, `Auth.test.tsx` |
| FR-5 | Solve the instance as a background job: backtracking, then local search within the time limit (default 300 s, at most 1,800). The job ends `solved`, `infeasible` (explained, FR-7) or `timeout`, never infeasible on a timeout (D33). The job's status and phase can be polled. | `POST /instances/{id}/solve`, `GET /jobs/{id}` | `components/timetable/SolvePanel.tsx` | `backend/tests/test_api.py`; `__tests__/SolveFlow.test.tsx`; `solver/tests/test_backtracking.py`, `test_improve.py` |
| FR-6 | Score every solved timetable on the four rules of `solver/rules/quality_rules.yaml` and show the breakdown (D34). | (in `solution.v2`) | `components/timetable/QualityScoreCard.tsx` | `solver/tests/test_scoring.py`; `__tests__/QualityFlags.test.tsx` |
| FR-7 | Explain an infeasible solve or repair: a minimal conflicting set, or one proven by pre-solve, and a relaxation verified to restore feasibility, or MANUAL. Break pins are never suggested (S14e, S14g). | (in `solution.v2`) | `components/timetable/InfeasibilityDiagnosisPanel.tsx` | `solver/tests/test_mus.py`; `backend/tests/test_api.py`, `test_substitution.py`; `__tests__/InfeasibleDiagnosis.test.tsx` |
| FR-8 | Repair the official timetable after one change, moving as few sessions as possible. The change is a faculty unavailability, a room unavailability, a drag of one session to a slot and room, or a substitute teacher. The drop is checked in the browser first. | `POST /instances/{id}/repair`, `GET /jobs/{id}` | `components/timetable/RepairPanel.tsx`; drag on `TimetableGrid.tsx` (check in `adapters/timetable.ts`) | `solver/tests/test_repair.py`; `backend/tests/test_repair.py`; `__tests__/RepairFlow.test.tsx`, `__tests__/DragAndDrop.test.tsx` |
| FR-9 | Accept a solved repair to make it official, only if its base is still official and it was built with the accepted changes in force; otherwise 409 (D49, D56). | `POST /jobs/{id}/accept` | `RepairPanel.tsx` | `backend/tests/test_repair.py`, `test_fixes.py`; `__tests__/RepairFlow.test.tsx` |
| FR-10 | Show what a repair changed: its base solution and the edge lists the job and the instance use (D48, D52). | `GET /jobs/{id}/base-solution`, `GET /jobs/{id}/edge-list`, `GET /instances/{id}/edge-list/current` | `RepairPanel.tsx`, `App.tsx` | `backend/tests/test_fixes.py`; `__tests__/RepairFlow.test.tsx` |
| FR-11 | List the qualified substitutes for a session, from SPIT's sheets (`qualifications.json`, D53), who are free at its slot, with their score change and why the others are left out. | `GET /instances/{id}/sessions/{session_id}/substitutes` | `components/timetable/SubstitutePanel.tsx` | `backend/tests/test_substitution.py`, `test_fixes.py`; `__tests__/RepairFlow.test.tsx`; `solver/tests/test_repair.py` |
| FR-12 | List the accepted changes in force (D52), and let an administrator clear them; the official timetable then falls back as D56 says. | `GET /instances/{id}/changes`, `DELETE /instances/{id}/changes` | `components/timetable/AcceptedChangesPanel.tsx` | `backend/tests/test_repair.py`, `test_fixes.py`; `__tests__/RepairFlow.test.tsx` |
| FR-13 | Show each teacher's weekly load and warn above the 16 h target (D11). Recalculate after accepted changes, and show both teachers' load before and after a proposed substitution (S14m). | none (UI from the solution and edge lists) | `components/timetable/FacultyWorkloadCard.tsx`, `OverLimitWarning.tsx`, `RepairPanel.tsx` | `__tests__/FacultyWorkload.test.tsx`, `__tests__/OverLimit.test.tsx` |
| FR-14 | Show a room timetable and the free rooms at a chosen time (D15). | none (UI) | `components/timetable/RoomViews.tsx` (`RoomTimetable`, `FreeRoomsPanel`) | `__tests__/RoomViews.test.tsx` |
| FR-15 | Show the faculty free and engaged at a chosen slot (administrator, coordinator). | none (UI) | `components/timetable/FacultyAtSlotPanel.tsx` | `__tests__/FacultyWorkload.test.tsx` |
| FR-16 | Compare the generated timetable with the printed one: scores and the printed timetable's hard violations. | none (UI, from committed files) | `components/timetable/GeneratedVsPrintedCard.tsx`, `PrintedViolations.tsx` | `__tests__/RealData.test.tsx`, `__tests__/SolveFlow.test.tsx` |
| FR-17 | Record every login, solve, repair, accept and clear in an audit log, readable by an administrator. | `GET /audit` | `components/auth/AuditLog.tsx` | `backend/tests/test_auth.py`, `test_api.py`; `components/auth/__tests__/Auth.test.tsx` |
| FR-18 | Report the service's health. | `GET /health` | none | `backend/tests/test_api.py` |
| FR-19 | Create accounts and reset the demo from the command line (not a route; D59). | none (`backend/app/create_user.py`, `backend/app/demo_seed.py`) | none | `backend/tests/test_demo_seed.py` |

**D58 options, as built (S14s, PR #85), off by default.**

- `prefer_sub_rooms` (`solver/backtracking.py` `backtrack_solve`, `solver/improve.py` `improve`,
  `solver/repair.py` `repair`): try a split lab's sub-rooms before the whole lab.
- `last_ring_portfolio` (`repair`): cap the every-session-free ring, then try a fallback search.

With both off, every result is unchanged. The backend passes neither option, so the default
decides. Making them the default is a team decision (D58, S14u: **planned, not built**). The
measurements are in `docs/real-solve-even-2025-26.md` § D58 and `docs/repair-even-2025-26.md`
§ S14s.

## 6. Hard and soft rules

**Hard rules** (ROADMAP §6). Never violated. Every solved timetable passes
`solver.validate.validate_solution`, which shares no code with the search; `improve()` and
`repair()` run it on their result.

| Rule | Statement | Enforced in the search | Checked by the validator as |
|---|---|---|---|
| H1 | No faculty clash | FACULTY conflict edges (`solver/graph.py`) | `FACULTY_CLASH` |
| H2 | No division or batch clash; a division session blocks its batches | COHORT edges | `COHORT_CLASH` |
| H3 | No room clash beyond capacity: a classroom holds one session, a lab up to its batch places | one session per room or sub-room per period, a whole room locking its sub-rooms (`_room_is_available`) | `ROOM_OCCUPANCY` |
| H4 | Room capacity ≥ group size | room domains (`_room_suits`) | `ROOM_CAPACITY` |
| H5 | Practicals in labs, lectures and tutorials in classrooms | room domains (`_room_suits`) | `ROOM_TYPE` |
| H6 | Lab blocks contiguous (D7) | lab blocks placed jointly over teaching-adjacent periods | `LAB_CONTIGUITY` |
| H7 | Breaks and the year's lunch never used | only teaching periods; lunch is a cohort pin (D6) | `PINNED_BLOCK`; a start on a break is malformed input |
| H8 | Each required session placed exactly once | every session is one variable | a missing or duplicated session raises `ValueError` |

**Soft rules** (D34, `solver/rules/quality_rules.yaml` version "1",
`solver/scoring.py`). `score = 100 − Σ weight × raw`.

| Rule | Measures | Weight |
|---|---|---|
| S-GAP | Idle teaching periods inside a cohort's day (D13) | 2.0 |
| S-B2B | A teacher in two adjacent teaching periods in different sessions (D14) | 1.0 |
| S-LOAD16 | Teachers above 16 h a week (D11) | 1.0 |
| FAC_LOAD_IMBALANCE | Each teacher's heaviest day minus lightest day, summed | 0.5 |

## 7. Non-functional requirements

| Area | Requirement | How it is met |
|---|---|---|
| Security | Only logged-in users read; only administrators and coordinators change; only administrators clear changes and read the audit log | Bearer token on every instance and job route (`current_actor`); `require_role` (`backend/app/deps.py`) |
| Security | Passwords are never stored in clear | scrypt hashes with a constant-time comparison and a dummy hash for unknown users (`backend/app/auth.py`) |
| Security | Tokens are signed and expire | HS256 JWT; `SECRET_KEY` of at least 32 characters required at start-up; 30-minute default expiry (`AuthSettings`) |
| Security | Production database access is deliberate (D55, D57) | The API and every script refuse any non-local database host unless `CHRONOS_ALLOW_REMOTE_DB=1` (`db/local_guard.py`, `migrations/env.py`). Only the Render service sets it, by hand; never `.env` files, the repository, tests or agents |
| Reliability | A solved timetable never breaks a hard rule | the independent validator (§6) plus a seeded property test (`solver/tests/test_property_solved_is_valid.py`) |
| Reliability | A timeout is never reported as infeasible | job status `timeout` (D33); `repair` raises `TimeoutError` |
| Reliability | Every payload served matches its contract | `check_contract` against `contracts/` before serving (`backend/app/service.py`) |
| Reliability | Jobs survive a restart | jobs are rows of `solve_job`; a restart marks interrupted jobs `error` |
| Reliability | Same input, same output | seeded randomness, sorted tie-breaks, node budgets (`docs/algorithms.md`); results cut by a wall-clock limit can differ between machines (documented) |
| Performance | A solve or repair never blocks the API | jobs run in a process pool of 2 workers (`ProcessPoolExecutor`, `backend/app/service.py`) |
| Performance | Bounded run time | every job has `time_limit_s` (default 300 s, at most 1,800), which covers the explanation too (S14k) |
| Performance | Measured (not a guarantee) | Real instance: backtracking 187.6 ms, 92 nodes; with local search at 200,000 moves 9,176.7 ms (`docs/evaluation-even-2025-26.md` § 1). Repair: median 326.8 ms over the 19 changes repair and regeneration both solved (§ 7) |
| Usability | No internal codes as main text; periods T0–T9 and 12-hour times (D60) | `frontend/src/lib/wording.ts`, `frontend/src/lib/format.ts`; tests `lib/__tests__/wording.test.ts`, `format.test.ts` |
| Usability | Names, not ids, in the interface (D41, D51) | `display.json`, served at `GET /instances/{id}/display` |
| Deployment | One service serving the API at `/api` and the built frontend at `/` (D55) | `backend/app/prod.py`, `backend/Dockerfile.prod` (one uvicorn worker), tests `backend/tests/test_prod.py`. The Render service and its Supabase database: **planned, not built** (S16c) |
| Maintainability | Rule weights change without code (`docs/CONTEXT.md` rule 4) | `solver/rules/quality_rules.yaml`, checked by `load_rules` |
| Maintainability | Solver purity: no web, ORM or database imports in `solver/` (D61: PyYAML in `scoring.py` only) | purity tests (`TestSolverPurity`, `TestSolverPurityBacktracking`, `solver/tests/test_validate.py::TestIndependence`) |

## 8. Assumptions

| Assumption | Decision |
|---|---|
| A division has 80 students; a batch has 20; a division has 4 batches | D5 |
| Grid: Mon–Fri, P0–P9, P2 coffee for all, lunch P5 for SE and P4 for TE | D6 |
| A practical is one 2-hour block per batch per week; it may span the coffee break, never lunch | D7 |
| Lab capacities from `data/real/lab_capacities.yaml`; 16 batch places in all | D8, D27, D28 |
| Rooms: `classrooms.xlsx`; 6th- and 7th-floor rooms plus labs 507 and 509; 605 and 609 only if they seat 80 | D10, D42 |
| Workload target 16 h a week, soft; a practical counts 2 h per batch | D11 |
| Faculty are available in every teaching period unless the timetables say otherwise | D12, D36 |
| One tutorial per division, 1 h, in a classroom | D23 (supersedes D9) |
| Items excluded by D3 but printed in the timetable are frozen; so are out-of-scope sessions in D8/D10 rooms and printed exam blocks | D24, D35, D37 |
| Combined lectures are one lecture per division | D40 |
| CE faculty means `Faculty___Subjects.xlsx` plus the D25/D38 resolutions | D44, D45 |
| Accepted changes accumulate | D52 |
| A substitute must be listed for the subject in SPIT's sheets; Chronos suggests, a coordinator decides | D53 |
| The official timetable is always valid for the accepted changes in force | D56 |

## 9. Out of scope

- Everything ROADMAP §2 and D3 exclude: FE and BE, electives, minors, honours, LLC, HSSM,
  projects, institute-wide fixed slots, Saturday working, and the ODD semester.
- Other departments: the schema is department-scoped so they can be added (`docs/CONTEXT.md`
  rule 5), but only CE is built and demonstrated.
- Natural-language input and any learned model (`docs/CONTEXT.md` rule 1).
- **Planned, not built:**
  - the deployed service and its demo (S16c, S16d);
  - instance data read from the database rather than committed files;
  - end-to-end browser tests (`tests/e2e/` does not exist).
