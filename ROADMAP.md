# Chronos — Roadmap and Tracker

Last updated: 2026-10-11 · Maintained by all three members.
Agents: read this file and CLAUDE.md before any task. §1 (ownership) and §3 (decisions) are binding.

## 0. How to use this file
- This is the single source of truth for scope, decisions, ownership, sequence and status.
- Tick checkboxes (§7) and update the Status column (§8) in the same PR that completes the work.
- A decision in §3 is changed only by adding a new dated row that supersedes it; old rows are never rewritten.
- Every Sunday one member updates §8 and §9.

## 1. Team and ownership
| Track | Owner | Directories |
|---|---|---|
| A — Solver Core & Algorithms | Dhruv Hemant Gangurde | solver/ |
| B — Backend & Data Layer | Nidhi Rajkamal Dhyani | backend/, db/, migrations/, ingestion/, data/, contracts/ (custodian) |
| C — Frontend & Validation | Rohan Shashikant Dhumal | frontend/, bench/, tests/e2e/ |

- contracts/: any change needs all three members' Agree.
- docs/, ROADMAP.md, CLAUDE.md, README.md: any member may edit, through a PR.
- Review rule: every PR into main needs one approving review from someone other than the author.
  - Track A PRs: Nidhi reviews.
  - Track B PRs: Rohan reviews.
  - Track C PRs: Nidhi reviews.
  - contracts/ PRs: all three approve.
  - Work done inside another track's directory: that directory's owner reviews.
- Everyone commits under their own git identity only.

## 2. Scope (v1)
- Department: Computer Engineering (CE), SPIT. Semester: EVEN 2025-26.
- Years in scope: SE (Semester IV) and TE (Semester VI). FE and BE are out of scope for v1.
- Out of scope for v1: electives (PE/OE), minors (MDM), honours, LLC, HSSM, courses taught by other departments, projects, institute-wide fixed slots, Saturday working, the ODD semester.
- The system must: avoid all clashes; respect breaks, lunch, room capacity and lab capacity; flag professors' back-to-back lectures; avoid student free gaps; show a room timetable and a free-room view.

## 3. Decisions (binding)
| ID | Decision | Source | Date |
|---|---|---|---|
| D1 | Ownership as in §1 (A Dhruv, B Nidhi, C Rohan). Early drafts that said otherwise are wrong. | Team | 2026-10-10 |
| D2 | Scope as in §2: SE (Sem IV) and TE (Sem VI) only. | Team (Q1 default) | 2026-10-11 |
| D3 | Excluded: electives, minors, honours, LLC, HSSM, projects (PR3-I etc.), Saturday working, institute-wide fixed slots, and any course whose teacher is not in our CE faculty list. Excluded items are listed in the anomaly report, never silently dropped. | Team (Q3, Q4) | 2026-10-11 |
| D4 | Weekly L/T/P hours come from data/real/academic_scheme.pdf via data/reference/teaching_scheme.yaml. Who teaches which subject to which division/batch comes from the EVEN class and lab timetables (.docx). Mismatches are reported, never guessed. | Team (Q2) | 2026-10-11 |
| D5 | Each division = 80 students; batch = 20 students; 4 batches per division. | Nidhi | 2026-10-11 |
| D6 | Grid: Mon–Fri, periods P0–P9 (see §5). P2 = coffee break for all. Lunch = P5 for SE, P4 for TE. Lunch is per year, not global. | Nidhi (Q5) | 2026-10-11 |
| D7 | One practical = one 2-hour block = 2 consecutive teaching periods per batch per week. A block may span the coffee break but never a lunch period. Batches may run in parallel. | Nidhi | 2026-10-11 |
| D8 | Labs and parallel capacity: data/real/lab_capacities.yaml (507:1, 509:2, 603:3, 604:1, 606:2, 607B:1, 608:1, 702:3, 703:2; 607A M.Tech only, excluded). Total 16 B.Tech batch places per period. Any listed lab can host any CE practical. | Nidhi (hand-checked) | 2026-10-11 |
| D9 | Tutorials: 1 hour per batch per week, in a classroom. | Team (Q7) | 2026-10-11 |
| D10 | Rooms: classrooms.xlsx is authoritative. 6th- and 7th-floor rooms (plus labs 507, 509) belong to CE. Ground, 1st and 2nd floor rooms are shared with ASMH and have no busy-time data, so they are not used in v1. | Nidhi | 2026-10-11 |
| D11 | Faculty: the existing 41-member list. Workload: average 16 h/week, a soft target. Faculty above 16 h are flagged. A practical counts as 2 h per batch taught. No daily cap. | Nidhi (Q8) | 2026-10-11 |
| D12 | Faculty unavailability: none known, so everyone is available in all teaching periods Mon–Fri. | Team (Q9) | 2026-10-11 |
| D13 | Student free gaps (an idle teaching period between a division's first and last session of a day, excluding breaks) are a strong soft rule: penalised and flagged, not hard. | Team (Q10) | 2026-10-11 |
| D14 | A professor teaching in two consecutive teaching periods is flagged and penalised. A single 2-hour lab block is not back-to-back by itself. | Team (Q11) | 2026-10-11 |
| D15 | A room timetable and a "free rooms at a given time" view are required (Track C, from solver output). | Nidhi | 2026-10-11 |
| D16 | Step-3 solver work (Welsh-Powell fix, synthetic benchmark): run by Nidhi, committed by Nidhi, reviewed by Dhruv. | Team (Q12) | 2026-10-11 |
| D17 | Contract v2 §11 row 7: signature cells are not rewritten. A dated note records Dhruv's (Track A owner's) Agree. | Team (Q12) | 2026-10-11 |
| D18 | Rohan's three git identities are merged with a .mailmap. | Team (Q12) | 2026-10-11 |
| D19 | The synthetic generator lives in solver/benchmarks/ (stdlib only, Track A). It is for tests and benchmarks only; nothing synthetic is presented as SPIT data. | Team | 2026-10-06 |
| D20 | Faculty initials are stored in the DB table faculty_initials (migration 0004) instead of a YAML file. | Nidhi | 2026-10-03 |
| D21 | Infeasibility: polynomial pre-solve checks (counting and Hall/Hopcroft–Karp matching) run before search; the search has a time budget. A timeout is reported as "timeout", never as "infeasible". | Team | 2026-10-11 |
| D22 | v1 contracts are frozen. v2 (proposal rows 1–7, signed 2026-10-06) is used only once contracts/*_v2 files are on main. | Team | 2026-10-06 |

## 4. Real data inventory (data/real/ unless stated)
| File | What it gives | Status |
|---|---|---|
| CE_Class_Time_Table-EVEN_sem_25-26.docx | Division timetables: who teaches what, rooms, slots | Present; parser = S6 |
| Lab CE_Time_Table-Even_sem_25-26.docx | Room-wise lab timetable | Present; parser = S7 |
| Faculty Individual timetable Even 2025-26.docx | Per-faculty timetables, T+P load lines | Present; parser = S7 |
| CE_Class_Time_Table-ODD_sem_25-26.docx | ODD timetables | Present; out of scope for v1 |
| classrooms.xlsx | Rooms, capacity, sub-rooms | Present; confirmed correct |
| Faculty___Subjects.xlsx, Subject-wise_faculty.xlsx | Faculty–subject qualification | Present; seeded, not human-verified |
| academic_scheme.pdf | L/T/P hours per course | Added in S2 |
| lab_capacities.yaml | Parallel batches per lab (D8) | Added in S2; hand-checked |
| ../reference/teaching_scheme.yaml | Sem IV and VI courses with L/T/P, transcribed from the PDF | Added in S2; hand-checked |

## 5. Time grid (D6)
| Period | Time | SE (Sem IV) | TE (Sem VI) |
|---|---|---|---|
| P0 | 09:00–10:00 | teach | teach |
| P1 | 10:00–11:00 | teach | teach |
| P2 | 11:00–11:15 | coffee | coffee |
| P3 | 11:15–12:15 | teach | teach |
| P4 | 12:15–13:15 | teach | LUNCH |
| P5 | 13:15–14:15 | LUNCH | teach |
| P6 | 14:15–15:15 | teach | teach |
| P7 | 15:15–16:15 | teach | teach |
| P8 | 16:15–17:15 | teach | teach |
| P9 | 17:15–18:15 | teach | teach |
Days: Mon–Fri. 8 teaching periods per day per year = 40 per week.

## 6. Constraints
Hard (never violated):
- H1: no faculty clash. H2: no division/batch clash (a division session blocks all its batches).
- H3: no room clash beyond capacity (classroom: 1 session; lab: up to parallel_batches batches).
- H4: room capacity ≥ group size. H5: room type (practicals in labs; lectures and tutorials in classrooms).
- H6: lab blocks contiguous (D7). H7: breaks and the year's lunch are never used.
- H8: each required session is placed exactly once.

Soft (scored and flagged, in solver/rules/quality_rules.yaml):
- S-GAP: student free gaps (D13, strong weight).
- S-B2B: professor back-to-back (D14).
- S-LOAD16: faculty weekly load above 16 h (D11, flag).
- FAC_LOAD_IMBALANCE: spread of each faculty member's load across the days of the week (contract v2 row 7).

## 7. Status by phase and track
Legend: [x] done and merged · [~] partial · [ ] not started. (Sn) = the step in §8 that finishes it.

### Phase 0 — Foundations
- [x] Repo layout · [x] docker-compose · [x] v1 schemas · [x] slots.py (A)
- [x] CI: ruff, pytest with Postgres, migrations, frontend jobs (required checks on GitHub: to verify)
- [~] Contract examples validated on both sides: Python done; TypeScript (S5)
- [ ] quality_rules.yaml (S10)

### Phase 1 — Data model, graph, grid UI
- B: [x] models (3NF), department scoping, cohort polymorphism · [~] reference seed: T/P loads missing (S7) · [~] faculty_initials table: needs human verification · [ ] constraint derivation / export (S9)
- A: [x] conflict graph, O(1) adjacency · [~] Welsh-Powell: fix awaiting merge (S1) · [x] graph tests with networkx cross-check · [ ] chromatic lower bound (optional)
- C: [x] scaffold, grid, lab, combined and pinned cells · [~] TS types from schemas (S5)
- Exit: [ ] real solver output rendered in the browser (S12)

### Phase 2 — Real data and backtracking
- B: [ ] teaching scheme + class_tt parser (S6) · [ ] lab_tt, faculty loads, anomaly report (S7) · [ ] seeder + DB→edge-list export (S9)
- A: [x] backtracking (forward checking, MRV, exact undo), lab blocks, sub-rooms, pinned blocks, capacity, validate.py · [ ] pre-solve, lazy lab rooms, timeout (S4) · [ ] per-year lunch (S8)
- C: [x] drag and drop with revert, role views, mock API, Vitest · [ ] anomaly report viewer (S11)
- Exit: [ ] real EVEN SE+TE instance solved and validated (S12)

### Phase 3 — Quality and API
- A: [ ] scoring.py + rules (S10)
- B: [ ] FastAPI endpoints, auth, audit (S13)
- C: [ ] TanStack Query (S5) · [ ] quality panel, workload view, room timetable, free rooms (S11) · [ ] generate flow on the real API (S13)

### Phase 4 — Diagnosis and repair
- A: [ ] mus.py, relaxation, repair.py (S14)
- B: [ ] absences and substitution API; qualifications verified (S14)
- C: [ ] diagnosis panel and repair preview on real data (S14)

### Phase 5 — Evaluation (S15)
- [ ] Runtime vs size · [ ] compare with the real EVEN timetable · [ ] greedy vs backtracking · [ ] lab utilisation · [ ] API tests · [ ] property tests

### Phase 6 — Report and demo (S16)
- [~] README · [ ] report · [ ] slides · [ ] demo script

## 8. Sequence of work
| Step | Owner | Branch | Depends on | Reviewer | Status |
|---|---|---|---|---|---|
| S1 | Nidhi | track/solver-baseline | — | Dhruv | In progress |
| S2 | Nidhi | chore/docs-truth | S1 merged | Dhruv + Rohan | Not started |
| S3 | Nidhi | contracts/v2-schemas | S2 merged | all three | Not started |
| S4 | Dhruv | track/solver-presolve | S1 merged | Nidhi | Not started |
| S5 | Rohan | track/frontend-contracts | — | Nidhi | Not started |
| S6 | Nidhi | track/data-class-tt | S2 merged | Rohan | Not started |
| S7 | Nidhi | track/data-lab-faculty | S6 merged | Rohan | Not started |
| S8 | Dhruv | track/solver-v2-grid | S3 merged, S4 merged | Nidhi | Not started |
| S9 | Nidhi | track/data-seed-export | S7 merged, S3 merged | Rohan | Not started |
| S10 | Dhruv | track/solver-scoring | S8 merged | Nidhi | Not started |
| S11 | Rohan | track/frontend-v2-rooms | S3, S5 merged | Nidhi | Not started |
| S12 | All | integration/real-even | S9, S10, S11 | all three | Not started |
| S13 | Nidhi + Rohan | track/backend-api, track/frontend-api | S12 | cross | Not started |
| S14 | All | per track | S13 | cross | Not started |
| S15 | All | eval/* | S14 | cross | Not started |
| S16 | All | docs/report | S15 | cross | Not started |

## 9. Weekly plan (week 1 = 2026-09-21)
- W4 (Oct 12–18): S1, S2, S3, S4, S5, start S6
- W5 (Oct 19–25): finish S6, S7, S8
- W6 (Oct 26–Nov 1): S9, S10, S11
- W7 (Nov 2–8): S12 integration (Phase 1 and 2 exits)
- W8 (Nov 9–15): S13 API and real client
- W9–W10 (Nov 16–29): S14 diagnosis, repair, substitution
- W11 (Nov 30–Dec 6): S15 evaluation
- W12 (Dec 7–13): S16 report, slides, demo, buffer

## 10. Workflow
- Branch from up-to-date main, one branch per step, named as in §8.
- Agents never stage, commit or push. A human reviews the agent's report, commits, pushes, opens a PR, waits for CI to pass, gets the review, then merges.
- Local tests always run against Docker Postgres (CHRONOS_DB_PORT, DATABASE_URL to localhost). Never set CHRONOS_ALLOW_REMOTE_DB. A run with skipped DB tests does not count.
- No ML in any decision path. solver/ imports only the stdlib and solver.* (networkx in tests only). Algorithms are hand-written and traceable to named CS courses.

## 11. Risks and open questions
- R1: Per-year lunch (D6) may not be expressible in edge_list_v1. Assessed in S3 (proposal row 8).
- R2: The EVEN timetable may not follow the PDF scheme exactly. S6 reports every mismatch.
- R3: Faculty initials and qualifications are not human-verified.
- R4: Pigeonhole infeasibility is slow to prove. S4 adds pre-solve checks and a timeout.
- R5: Local DB tests silently skip if Docker is down. Always check that there are 0 skips.
- Open: promoting migrations to Supabase; whether bench/ (C) reuses solver/benchmarks (A).

## 12. Carried over from the previous ROADMAP
Copied in S2 from the pre-2026-10-11 ROADMAP (`git show 6724bcc:ROADMAP.md`), names corrected per D1. Where anything below disagrees with §1, §3 or §10, those sections win.

### 12.1 Parallel work protocol
Three agentic tools on one repository **will** collide unless the boundaries are explicit.

#### Directory ownership is exclusive
| Directory | Owner | Others may |
|---|---|---|
| `solver/` | Dhruv | read, open issues |
| `ingestion/`, `db/`, `backend/` | Nidhi | read, open issues |
| `frontend/`, `bench/`, `tests/e2e/` | Rohan | read, open issues |
| `contracts/` | **all three jointly** | change only by agreement |
| `docs/CONTEXT.md`, `ROADMAP.md` | all three | edit freely, but commit alone |

If your task needs a change in someone else's directory, do not make it. Open an issue, or agree
the contract change first.

#### Branching
- `main` is protected. No direct pushes; CI must pass.
- One long-lived branch per member: `track/solver`, `track/data`, `track/frontend`.
- Feature branches off your track branch: `track/solver/mus-extraction`.
- **Merge to `main` at least twice a week.** Long-lived divergence is what actually kills parallel
  student projects — not merge conflicts, but two people building against different assumptions
  for three weeks.
- Rebase your track branch on `main` before every merge.

#### Agent-specific discipline
- Give the agent **one track's directory** as its working scope. Do not let it "fix" a failing
  test in another track's directory — that is where silent contract drift starts.
- Start every session by having the agent read `docs/CONTEXT.md`, `ROADMAP.md` and
  `docs/CURRENT-PROGRESS.md`. Agent rules live in the root `CLAUDE.md`, which Claude Code loads
  automatically.
- End every session by having it update `docs/CURRENT-PROGRESS.md`.
- Never let two agents run against the same working tree at once. Separate clones or
  `git worktree` if you must work simultaneously on one machine.

#### Weekly cadence
A 30-minute sync, same time each week:
1. What merged to `main` since last week
2. What is blocked, and on whom
3. Any contract change requested
4. Update `CURRENT-PROGRESS.md` together

### 12.2 Conflict fallback
| Risk | Likelihood | Mitigation | Cut line |
|---|---|---|---|
| Three agents conflict in git | **High** | Exclusive directory ownership, twice-weekly merges | Serialise: one member merges for everyone |

### 12.3 [S]/[C] items not in §7
Tags as in the old plan: [S] = should (cut only if behind schedule, note the cut), [C] = could (stretch).
- Phase 1, B: [S] Synthetic instance generator, parameterised by divisions/batches/subjects (now Track A, `solver/benchmarks/`, D19).
- Phase 1, C (Rohan): [S] Light/dark theme, responsive down to tablet width. [C] Storybook or a `/dev` route showing every cell variant side by side.
- Phase 2, B (Nidhi): [S] ODD semester ingested too (out of v1 scope, §2). [S] Idempotent re-ingestion — running twice does not duplicate rows.
- Phase 2, A (Dhruv): [S] Iterative (explicit-stack) backtracking if recursion depth becomes a concern past ~200 sessions. [C] Solve per-division first, then globalise for shared faculty and rooms, if the full instance proves slow.
- Phase 3, B (Nidhi): [S] OpenAPI docs reviewed and tidied. [S] Repository/service layer so routers stay thin.
- Phase 3, A (Dhruv): [S] Calibrate weights against the department's real published timetable. [C] Per-division score breakdown in addition to institute-wide.
- Phase 3, C (Rohan): [S] Filter the grid by division, batch, faculty or room.
- Phase 4: [S] Explicit "no qualified faculty free" path that offers repair instead.
- Phase 5: [S] Constraint-coverage table — what FET cannot express that Chronos can. [S] Load test on the generate endpoint. [C] Sensitivity analysis on quality weights.
- Phase 6: [S] Screencast fallback in case live demo fails. [S] `docs/` updated so SRS and UML match what was actually built.

## 13. Changelog
- 2026-10-11: New roadmap. Ownership corrected (D1). Real-data decisions D2–D22 recorded. Sequence S1–S16 defined.