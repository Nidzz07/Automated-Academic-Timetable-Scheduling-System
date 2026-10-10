# CURRENT-PROGRESS.md — Chronos

> **Living document. Update it at the end of every work session.**
> Read `docs/CONTEXT.md` for what the system is, `ROADMAP.md` (repo root) for what to build
> next, and this file for what is already done.

**Last updated:** 2026-10-06 · **by:** _(fill in)_ — repo-hygiene pass with Claude Code: committed merge-conflict markers resolved, PR #15 state recorded · **Current phase:** 0–2 in progress; no phase exit criterion met yet

---

## Update protocol

At the end of every session, whoever worked (or whoever drove the agent) updates:

1. The **status table** below — tick what is genuinely done, not what is nearly done.
2. **Recently completed** — one line per item, newest first, with the date and initials.
3. **Blockers** — anything stopping you, and who can unblock it.
4. **Decision log** — any non-obvious choice, so nobody re-litigates it in week 9.

A task is **done** when it is merged to `main`, CI is green, and it has a test. Not before.

---

## Phase status

| Phase                                | Weeks  | Status         | Exit criterion met? |
| ------------------------------------ | ------ | -------------- | ------------------- |
| 0 — Foundation and contracts        | 1      | 🟡 In progress | ⬜                  |
| 1 — Schema, graph builder, UI shell | 2–3   | 🟡 In progress | ⬜                  |
| 2 — Real data, core solver          | 4–5   | 🟡 In progress | ⬜                  |
| 3 — API, scoring, role views        | 6–7   | ⬜ Not started | ⬜                  |
| 4 — Novelty features                | 8–9   | ⬜ Not started | ⬜                  |
| 5 — Validation and benchmarking     | 10–11 | ⬜ Not started | ⬜                  |
| 6 — Deployment and delivery         | 12     | ⬜ Not started | ⬜                  |

Legend: ⬜ not started · 🟡 in progress · ✅ complete · ⚠️ blocked · ✂️ cut (note why)

---

## Track status

| Track                      | Owner | Branch                                                        | Current task                                                                                                                                                                                                                                                                                                                                     | State |
| -------------------------- | ----- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| A — Solver                | Rohan | `track/solver`                                              | Phase 2 Track A [M] items merged (PR#13, #15). Step 3 done, uncommitted: Welsh-Powell hard-constraint bug fixed, synthetic generator + baseline (`docs/solver-baseline-2026-10-06.md`). Open: lab-block room enumeration dominates solve time; pigeonhole infeasibility not proven in 300 s. Next: Phase 3 `solver/scoring.py` (not started) | 🟡    |
| B — Data & Backend        | Nidhi | `track/data-*` feature branches (all merged; latest PR #10) | Reference seed and division-scoped faculty initials merged (41 faculty, migration 0004). Initials mapping not yet human-verified; faculty T/P workloads not seeded. Phase 2 ingestion parsers (`class_tt.py`, `lab_tt.py`, `anomalies.py`) not started                                                                                     | 🟡    |
| C — Frontend & Validation | Dhruv | `track/frontend`                                            | Phase 1 grid and Phase 2 drag-and-drop / role views / mock API merged (PR#6, #14), all running against contract fixtures and a mock client — not yet wired to a real API                                                                                                                                                                        | 🟡    |

---

## Phase 0 checklist — Foundation and contract freeze

- [X] Repo reconciled against `CONTEXT.md` §7 layout
- [ ] Branch protection on `main`; three track branches created
- [ ] CI running `pytest`, `ruff`, `tsc --noEmit`, `vitest` on push
- [X] `contracts/ingestion_v1.schema.json` written
- [X] `contracts/edge_list_v1.schema.json` written
- [X] `contracts/solution_v1.schema.json` written
- [X] Example payload committed for each contract
- [X] Schema-validation test passing on both sides of each contract
- [X] `SlotId` convention agreed; `is_adjacent()` handles the short break
- [ ] `solver/rules/quality_rules.yaml` seeded with four rules
- [X] `docker-compose.yml` for local Postgres

**Exit:** contract tests green in CI, and all three members can state the three contracts from
memory.

---

## Phase 1 checklist — Schema, graph builder, UI shell

### Track B — Data

- [X] SQLAlchemy models for the full entity model
- [X] `department_id` scoping present; `Room` is institute-level
- [ ] Alembic migration 0001 applied to Supabase
- [X] `Cohort` polymorphic resolution implemented
- [ ] 32 faculty seeded with T/P workloads
- [X] 20 rooms seeded, sub-rooms expanded from the separation column
- [ ] Faculty initials → name mapping derived and **human-verified**
- [ ] *(S)* Synthetic instance generator
- [ ] *(S)* Constraint-derivation SQL

### Track A — Solver

- [X] `graph.py` builds a conflict graph from an edge-list payload
- [X] Cohort overlap handles containment (batch ⊂ division, combined divisions)
- [X] Combined-division lecture becomes a single vertex
- [X] `colouring.py` — Welsh-Powell honouring faculty availability
- [X] Unit tests on hand-built instances
- [X] `networkx` cross-check in tests only
- [X] *(S)* O(1) adjacency lookups

### Track C — Frontend

- [ ] Vite + React + TS + Tailwind + shadcn/ui scaffold
- [ ] Grid renders an 8×5 week from a static `solution_v1` fixture
- [ ] Renders: double-period lab, four parallel batches, combined lecture, pinned block
- [ ] TypeScript types mirror the contracts
- [ ] *(S)* Theming and tablet-width responsiveness

**Exit:** greedy colouring produces a conflict-free timetable on a synthetic 40-session instance
and it renders in the browser.

---

## Phase 2 checklist — Real data, core solver

### Track B — Ingestion

- [ ] `ingestion/rooms.py` — xlsx + separation expansion
- [ ] `ingestion/faculty.py` — names, T/P workloads, assigned sessions
- [ ] `ingestion/class_tt.py` — both class timetables, per-source field order
- [ ] `ingestion/lab_tt.py` — room-wise labs, room overrides, utilisation %
- [ ] Pinned blocks classified, not failed on
- [ ] `ingestion/anomalies.py` — report committed as evidence
- [ ] Seeder writes canonical JSON to the database transactionally
- [ ] **Real CE EVEN data in the database**
- [ ] *(S)* ODD semester ingested
- [ ] *(S)* Re-ingestion is idempotent

### Track A — Solver

- [X] `backtracking.py` — forward checking with exact undo, MRV ordering
- [X] `LabBlock` — N parallel batch sessions allocated jointly
- [X] Double-slot contiguity on teaching-sequence adjacency
- [X] Sub-room awareness (same room, different sub-room is legal)
- [X] Pinned blocks as fixed occupancy
- [X] Capacity check against cohort size
- [ ] *(S)* Iterative backtracking if depth becomes a problem
- [X] `solver/validate.py` — independent hard-constraint checker; every solved result is held to it _(PR #15; `solver/tests/test_validate.py`)_
- [X] Fix: `fixed_slot` intersected with availability, never substituted for it (proposal §5.1 obs. 1) _(PR #15; `TestRegressionFixedSlotVsAvailability`)_ — in `backtracking.py` only; `colouring.py` still has it, see Blockers
- [X] Fix: every period of a multi-period placement checked, in a LabBlock or not (proposal §5.1 obs. 2) _(PR #15; `TestRegressionMultiPeriodOccupancy`)_ — in `backtracking.py` only; `colouring.py` still has it, see Blockers
- [X] `Room.room_type` (class | lab | unknown) replaces `Room.is_lab` inside the solver _(PR #15; `TestRoomType`)_

**Placeholders in Track A — NOT features, do not tick anything on their account:**

- ⚠️ **Infeasibility diagnosis is NOT implemented.** `BacktrackResult.to_solution_dict` emits
  `_placeholder_diagnosis`: one `unplaced.<id>` / `UNSATISFIABLE_DOMAIN` entry per unplaced
  session and "Relax constraints on session X". That is not a minimal unsatisfiable subset.
  The shape is kept for `solution_v1`; `solution.v2` moves it to `method = search_exhaustion`.
  The real thing is `solver/mus.py`, Phase 4 — still unticked below.
- ⚠️ **Quality score is NOT computed.** A solved result defaults to
  `quality = {"score": 100.0, "breakdown": []}` — a hardcoded stand-in, not a perfect score.
  `solution_v1` requires a numeric `score` on every solved result and cannot say "not
  evaluated", so it stays (with a loud code comment) until `solver/scoring.py` lands in Phase 3
  and `solution.v2` change 6 adds per-rule status.

### Track C — Frontend

- [ ] Drag-and-drop with provisional drop and revert-on-reject
- [ ] Four role-differentiated views
- [ ] Mock API layer
- [ ] *(S)* Vitest coverage of grid and drag
- [ ] *(S)* Anomaly report viewer

**Exit:** real CE EVEN instance solved conflict-free; at least one published lab-utilisation
percentage reproduced.

---

## Phase 3 checklist — API, scoring, role views

### Track B

- [ ] `POST /timetables/generate`, `GET /timetables/{id}`, validate, `PATCH /sessions/{id}`
- [ ] JWT auth, four personas, server-side authorisation on every route
- [ ] Pydantic models validated against contracts
- [ ] `AuditEntry` on every mutating action
- [ ] *(S)* OpenAPI docs tidied

### Track A

- [ ] `scoring.py` — YAML rule engine with registry
- [ ] Four rules implemented
- [ ] `FAC_LOAD_IMBALANCE` uses T/P-weighted workload
- [ ] `score()` returns `(total, breakdown)`
- [ ] YAML validated against registry at load
- [ ] *(S)* Weights calibrated against the real published timetable

### Track C

- [ ] Real API wired via TanStack Query
- [ ] Quality score panel with rule-by-rule breakdown
- [ ] Generate flow with progress and error states
- [ ] *(S)* Faculty workload view with T/P split
- [ ] *(S)* Grid filters

**Exit:** click Generate in the browser, see a scored timetable from real data.

---

## Phase 4 checklist — Novelty features

### Absence rescheduling

- [ ] `Qualification` populated and human-verified
- [ ] `POST /absences`, `POST /substitutions`
- [ ] Candidate query: qualified + free, ordered by T/P workload
- [ ] Workload recalculated for both faculty
- [ ] Coordinator dual view (free ‖ engaged) for a selected slot
- [ ] Substitution confirm flow; both timetables update
- [ ] Every swap audited
- [ ] *(S)* "No qualified faculty free" path offers repair

### Diagnosis and repair

- [ ] `mus.py` — deletion-based extraction; timeout counts as infeasible _(today's infeasible output is a placeholder — see Phase 2 Track A)_
- [ ] Core translated to named faculty / rooms / cohorts
- [ ] Smallest relaxation suggested
- [ ] `repair.py` — freeze-and-expand with BFS ring expansion
- [ ] Displaced-session set returned with every repair
- [ ] `POST /timetables/{id}/repair`, `GET /diagnoses/{id}`
- [ ] Diagnosis panel in the UI
- [ ] *(S)* Repair preview

**Exit:** coordinator resolves an absence end to end; infeasible instance returns a readable
diagnosis.

---

## Phase 5 checklist — Validation and benchmarking

- [ ] Hypothesis property test: no timetable ever contains a conflict _(a seeded-random property test now exists: `solver/tests/test_property_solved_is_valid.py`, 400 instances, seed 20261003 — backtracking only; Welsh-Powell fails it, see Blockers)_
- [ ] Edge cases: empty, single session, no replacement, infeasible, over-subscribed division
- [ ] Benchmark: runtime vs instance size (plot)
- [ ] Benchmark: **displaced sessions, repair vs regeneration** (mean + CI)
- [ ] Benchmark: greedy-only vs greedy + backtracking quality
- [ ] Lab-utilisation percentages reproduced
- [ ] Generated timetable compared against the department's real one
- [ ] API integration tests; frontend tests
- [ ] *(S)* Constraint-coverage table vs FET
- [ ] *(C)* Weight sensitivity analysis

**Exit:** every report number exists as a committed, reproducible plot or table.

---

## Phase 6 checklist — Deployment and delivery

- [ ] Production deploy (API, frontend, database)
- [ ] Seeded demo data with safe reset
- [ ] Report written
- [ ] Demo arc rehearsed
- [ ] README a stranger can follow
- [ ] *(S)* Screencast fallback
- [ ] *(S)* `docs/` SRS and UML match what was built

---

## Recently completed

_Newest first. Format: `YYYY-MM-DD · initials · what landed · PR #`_

- `2026-10-06` · Nidhi (run), reviewed by Dhruv · **Track A Step 3: Welsh-Powell fix, synthetic generator, honest baseline.**
  `solver/colouring.py` now checks every occupied period (not just the start), colours each lab
  block as one unit, and holds fixed slots to every check; lab blocks are kept on
  `ConflictGraph`. The strict xfail is removed (338 of 394 complete colourings were invalid
  before; 0 of 179 now); 16 regression tests, 15 of which fail on the old code, plus an exact
  networkx `largest_first` cross-check. New `solver/benchmarks/` (seeded `edge_list_v1`
  generator with small / medium / large / infeasible presets, and a baseline script). The
  generator lives in `solver/benchmarks/synthetic.py` (stdlib only, maintained by Track A); Track
  B reuses it for its [S] synthetic-generator item rather than building another. All presets are
  synthetic, not SPIT data; only `large`'s room inventory comes from `data/real/classrooms.xlsx`.
  Baseline, seeds 1–3: every preset up to `large` (242 sessions) solved and validator-clean,
  with zero backtracks; `large` ~37–43 s, dominated by lab-block room-tuple enumeration; the
  pigeonhole infeasible preset times out at 300 s. See `docs/solver-baseline-2026-10-06.md`.
  · _no PR yet (uncommitted)_
- `2026-10-06` · Nidhi, Rohan, Dhruv · **Contract v2 proposal signed off by all three tracks.**
  `docs/contract-change-proposal-v2.md` §11 rows 1–7 all marked Agree with no changes (row 7, the
  `FAC_LOAD_IMBALANCE` ROADMAP clarification, needed only Rohan's Agree). **No schema files have
  been created yet** — `contracts/` still holds only the v1 schemas, so nothing has entered the
  Contract change log. Next: the v2 schema files (`ingestion_v2.schema.json`,
  `solution_v2.schema.json`, `relaxation_actions_v2.json`, with examples and contract tests, per
  proposal §7), then the per-track implementation. · _no PR yet (branch `contracts/v2-signoff`)_
- `2026-10-03` · Dhruv · **Track A correctness fixes (merged to `main` in PR #15 on 2026-10-06).** Two bugs from
  `docs/contract-change-proposal-v2.md` §5.1 let `backtracking.py` report "solved" for a timetable
  breaking a hard constraint. (1) `available_slots_for` returned `[fixed_slot]` before checking
  availability — a fixed slot is now intersected with faculty availability and pinned
  faculty/cohort occupancy; empty ⇒ infeasible. (2) Only a placement's first period was checked —
  one helper, `_occupied_slots`, now gives every period a placement occupies, and availability,
  neighbour clashes, room occupancy and forward checking all use it; `duration_periods > 1` outside
  a LabBlock is enforced too. Found while testing: a LabBlock member with a `fixed_slot` was
  pre-placed alone, the block was then skipped, and its other members were never placed — yet the
  result said "solved". Fixed sessions are no longer pre-placed (their domain is just the fixed
  start). New `solver/validate.py` re-checks every hard constraint independently of the search;
  every solved result in the solver tests and a 400-instance seeded property test go through it.
  On that generator the pre-fix solver returned 333 "solved" results, 287 of them invalid.
  · PR #15
- `2026-09-26` · Rohan · Phase 1 & 2 Track A (Solver) landed: `solver/graph.py` (conflict graph with cohort containment), `solver/colouring.py` (Welsh-Powell greedy with availability & pinned awareness), and `solver/backtracking.py` (backtracking search with forward checking, trail-based exact undo, MRV ordering, LabBlock joint placement, sub-room awareness, capacity checks, and `solution_v1` serialisation). 159 tests green across full suite. · PR #5, #13
- `2026-09-25` · NRD · Reference seed landed — 20 rooms + 8 sub-rooms, 33 faculty, 25 subjects, 64 qualifications, and the partial 8-of-33 initials map, from the three spreadsheets in `data/real/`. Two schema corrections came with it (migrations 0002, 0003 — see Decision log). 210 tests passing. · PR #3 (`track/data-seed`)
- `2026-09-25` · NRD · `db/models.py` + Alembic migration 0001 landed; 148 tests passing; `Cohort` polymorphism, institute-level `Room`, and a remote-DB safety guard in `migrations/env.py`. · PR #1, #2 (`track/data`)
- `2026-09-24` · NRD · Phase 0 contracts + `solver/slots.py` + CI workflow landed — three frozen JSON Schemas with example payloads, 41 schema-validation tests, the wall-clock slot module with 48 tests, GitHub Actions running `ruff check` + `pytest`, and a root `pyproject.toml`. 89 tests green. · _no PR (direct to `main`, pre-branch-protection)_

---

## Blockers

| Since      | Blocker                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Blocks whom                                                                                                   | Needs                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 2026-10-03 | ✅**Resolved 2026-10-06** (branch `track/solver-baseline`, uncommitted; see `docs/solver-baseline-2026-10-06.md`). Was: `solver/colouring.py` (Welsh-Powell) produces invalid timetables: it checks only a multi-period session's start slot, colours lab-block members independently, and places `fixed_slot` sessions with no availability, pinned or neighbour check. On the 400-instance property generator, 338 of 394 complete colourings violate a hard constraint. Recorded as a strict `xfail`; the validator was not loosened. Single-period, block-free, fixed-free instances are clean (400/400). | Anyone using greedy output as a timetable or as a backtracking seed; Phase 5 greedy-vs-backtracking benchmark | Nothing — resolved (was: Rohan — fix or scope Welsh-Powell to the single-period subclass)    |
| 2026-10-03 | `edge_list_v1` rooms carry `is_lab: boolean`, not the three-valued `room_type`; `unknown` cannot reach the solver                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Exact`RECLASSIFY_ROOM` semantics for rooms 605/609                                                          | All three — decide whether a future edge-list revision carries`room_type` (contract change) |

---

## Decision log

Record any choice a future session might otherwise re-litigate.

| Date       | Decision                                                                                                                                                                                                                                                                                                                                                                                         | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Decided by                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| 2026-10-03 | A`fixed_slot` restricts where a session may **start**; it is intersected with availability (faculty, cohort, pinned) and every other constraint, never substituted for it. Empty intersection ⇒ infeasible.                                                                                                                                                                             | A frozen session in a slot its teacher cannot attend is not a timetable. Substituting meant`FIXED_SLOT` vs `FACULTY_UNAVAILABLE` could never surface in a MUS.                                                                                                                                                                                                                                                                                                                                                                 | Dhruv (Track A fix; Rohan to confirm) |
| 2026-10-03 | Solver`Room` carries `room_type` (class \| lab \| unknown); only `lab` hosts a `requires_lab` session. Under `edge_list_v1` it is derived from `is_lab` (true→lab, false→class). Rooms 605/609 (`unsure` → `unknown`) stay unusable for labs until reclassified — exactly the `RECLASSIFY_ROOM` relaxation.                                                                | `unknown` must never be silently treated as a lab. The edge list is frozen, so the three-valued type lives inside the solver only.                                                                                                                                                                                                                                                                                                                                                                                               | Dhruv (Rohan to confirm)              |
| 2026-10-03 | `solver/validate.py` imports nothing from `backtracking`/`colouring`/`graph` (only `solver.slots`). Malformed payloads (unknown/missing/duplicate session, bad room ids, start on a break) **raise**; constraint breaks are **reported** with the proposal §5.1 kinds. A multi-period session whose chain runs off the day is `LAB_CONTIGUITY` even outside a LabBlock. | A bug in the search's helpers must not be able to hide in its checker. The reconciled kind enum has no separate "duration" kind.                                                                                                                                                                                                                                                                                                                                                                                                   | Dhruv                                 |
| 2026-09-25 | The ingestion contract's`room_type` (class/lab/unknown) and the DB's `room_used_as` (5 raw values) are deliberately **different layers**, not a bug to unify                                                                                                                                                                                                                           | `room_type` is the coarse signal the solver needs; `used_as` is raw fidelity for the anomaly reporter. Phase 2's `ingestion/rooms.py` must map used_as → room_type explicitly: class→class, lab→lab, 'as a lab'→lab, 'Mtech lab'→lab, unsure→unknown.                                                                                                                                                                                                                                                                  | Nidhi                                 |
| —         | Scope: CE only, ODD + EVEN, schema designed for CSE/EXTC                                                                                                                                                                                                                                                                                                                                         | Real data is CE; multi-dept later must not need a migration                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | All three                             |
| —         | Ingestion parser is a real phase, not hand-curated data                                                                                                                                                                                                                                                                                                                                          | Demonstrable feature: ingests the department's actual files                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | All three                             |
| 2026-09-25 | Migration 0002:`room_used_as` holds the **five verbatim strings** from classrooms.xlsx — `class`, `lab`, `unsure`, `as a lab`, `Mtech lab` — and the invented `unknown` is dropped                                                                                                                                                                                         | The enum was written before the real data was in hand. Folding`as a lab` into `lab` or `unsure` into `unknown` would erase distinctions the anomaly reporter exists to surface (`Mtech lab` reads like a real scheduling constraint). **Note:** `contracts/ingestion_v1.schema.json` still declares `rooms[].room_type` as class \| lab \| unknown — a *normalised* classification, a different thing from this raw column. That contract is frozen and untouched; the Phase 2 parser maps between the two. | Nidhi                                 |
| 2026-09-25 | Migration 0003:`Subject.session_type` is **nullable**, and every seeded subject has it null                                                                                                                                                                                                                                                                                              | No source spreadsheet states theory/lab/both. It is only observable from the timetable .docx files, so Phase 2 ingestion backfills it from real cells.`both` is not a safe default — it would make all 25 subjects look lab-capable to the room allocator.                                                                                                                                                                                                                                                                      | Nidhi                                 |
| 2026-09-25 | The seeded**subject list derives from `Faculty___Subjects.xlsx`**, not from the inverted `Subject-wise_faculty.xlsx`                                                                                                                                                                                                                                                                   | The inverted sheet drops`MDM-I Lab` and merges `MDM-III Theory (CC)` + `MDM-III Lab (CC)` into one `MDM-III (CC)`. Seeding from it orphaned three qualification pairs and inserted a merged code no faculty row names. Deriving from the faculty sheet gives 25 subjects and **zero orphaned pairs**.                                                                                                                                                                                                                | Nidhi                                 |
| 2026-09-25 | `migrations/env.py` refuses to run against any non-local database host unless `CHRONOS_ALLOW_REMOTE_DB=1` is explicitly set                                                                                                                                                                                                                                                                  | Prevents an accidental migration against shared Supabase staging.`backend/.env` pointed at Supabase at the time, so a plain `alembic upgrade head` would have hit it.                                                                                                                                                                                                                                                                                                                                                          | Nidhi                                 |
| 2026-09-25 | `Session.room_id` and `Session.sub_room_id` are mutually exclusive but **both-nullable** — not "exactly one required"                                                                                                                                                                                                                                                                 | `contracts/ingestion_v1.schema.json` allows `room_id: null` for sessions whose room reference is missing or unresolved (CONTEXT.md §3.5 known data defects). The anomaly reporter must be able to **store** those sessions rather than discard them.                                                                                                                                                                                                                                                                    | Nidhi                                 |
| 2026-09-24 | Edge-list contract indexes periods on the**wall clock, 0–9**, with `teaching_periods` marking the 8 schedulable slots (2 = short break, 5 = lunch)                                                                                                                                                                                                                                      | Lets`is_adjacent()` distinguish clock-adjacency from teaching-sequence adjacency, so a double lab can span the short break (periods 1→3) and lunch (4→6) — which the real data does (`ET Lab /DDA /509 (10.00 -12.00)`). Ingestion keeps its own teaching-order `period: 0..7`; translating between the two axes is the data layer's job and the axis must never leak into `solver/`.                                                                                                                                   | NRD                                   |

---

## Contract change log

Changing a contract requires all three members to agree. Log every change here.

| Date       | Contract                     | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Agreed by                                                  |
| ---------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| 2026-09-24 | `edge_list_v1.schema.json` | Added`default` annotations to the four `slot_grid` fields (`days`, `periods_per_day`, `teaching_periods`, `adjacency`) recording the canonical SPIT grid. **Non-breaking — `default` is annotation-only in JSON Schema, so validation behaviour is unchanged** (the 41 pre-existing contract tests pass untouched). Done so `solver/slots.py` can be drift-checked against the schema file itself rather than against a duplicated literal. | NRD — pending Rohan's and Dhruv's sign-off once onboarded |

---

## Cut list

Anything dropped from `ROADMAP.md`, with the reason. Keeps the report honest about scope.

| Phase | Item | Why cut | Date |
| ----- | ---- | ------- | ---- |
| —    | —   | —      | —   |
