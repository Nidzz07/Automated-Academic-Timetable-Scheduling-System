# ROADMAP.md — Chronos Implementation Plan

> **Read `CONTEXT.md` first.** This file says what to build and in what order.
> `CURRENT-PROGRESS.md` says what is already done — check it before starting work.

**Duration:** 12 weeks · **Team:** 3, working in parallel · **Scope:** CE department, ODD + EVEN
semesters, designed (not built) for CSE and EXTC.

---

## How to read this plan

Every phase has three parallel **tracks** that can run simultaneously, plus **integration points**
where they must sync. Each task is tagged:

| Tag | Meaning |
|---|---|
| **[M]** | Must — the phase is not complete without it |
| **[S]** | Should — cut only if behind schedule, note the cut in `CURRENT-PROGRESS.md` |
| **[C]** | Could — stretch goal, attempt only if the phase finished early |

Tracks: **A** = Solver (Rohan) · **B** = Data & Backend (Nidhi) · **C** = Frontend & Validation (Dhruv)

---

## Phase overview

| Phase | Weeks | Goal | Exit criterion |
|---|---|---|---|
| **0** | 1 | Foundation and contract freeze | Three contracts committed and validated by a test on both sides |
| **1** | 2–3 | Schema, graph builder, UI shell | Greedy colouring produces a valid timetable on a synthetic 40-session instance |
| **2** | 4–5 | Real data ingested, core solver | Real CE EVEN data in the database; backtracking solves it |
| **3** | 6–7 | API, quality scoring, role views | End-to-end: click generate in the browser, see a scored timetable |
| **4** | 8–9 | The two novelty features | A coordinator resolves an absence; an infeasible instance returns a diagnosis |
| **5** | 10–11 | Validation and benchmarking | Property tests green; benchmark numbers in hand |
| **6** | 12 | Deployment and delivery | Deployed URL, seeded demo, report, rehearsed demo |

**Non-negotiable checkpoints:** end of Week 3 (first valid timetable), Week 5 (real data solving),
Week 9 (both novelty features), Week 11 (benchmark numbers).

---

## Phase 0 — Foundation and contract freeze (Week 1)

All three members work **together** this week. Nothing parallel can start until the contracts
exist, because they are what let the three tracks proceed without blocking each other.

### Tasks

- **[M]** Reconcile the existing repo against `CONTEXT.md` §7 — create missing directories, move
  anything misplaced. (Driven by `CURRENT-STATUS.md`.)
- **[M]** Agree branch discipline and write it into `CONTEXT.md` (see *Parallel work protocol*).
- **[M]** GitHub Actions: on every push, run `pytest`, `ruff`, `tsc --noEmit`, `vitest`.
- **[M]** Write `contracts/ingestion_v1.schema.json` — the canonical JSON a parser emits.
- **[M]** Write `contracts/edge_list_v1.schema.json` — sessions + conflict edges, each edge
  carrying `reason` ∈ {FACULTY, ROOM, COHORT}.
- **[M]** Write `contracts/solution_v1.schema.json` — success (assignment + score breakdown) or
  failure (minimal conflicting subset + suggested relaxation).
- **[M]** One example payload per contract in `contracts/examples/`, and a test on each side that
  validates against the schema. This is what stops the tracks drifting apart.
- **[M]** Decide slot identity: canonical `SlotId` = `(day: 0–4, period: 0–7)` with a lookup table
  to wall-clock times, and an `is_adjacent(a, b)` helper that works across the short break.
- **[S]** Seed `solver/rules/quality_rules.yaml` with the four rules and placeholder weights.
- **[S]** `docker-compose.yml` for local Postgres, so nobody is blocked on Supabase connectivity.

### Exit criterion

A test in `tests/contracts/` loads each example payload, validates it against its schema, and
passes in CI. Every member can articulate the three contracts without looking.

---

## Phase 1 — Schema, graph builder, UI shell (Weeks 2–3)

First week of genuine parallel work. Each track builds against fixtures, not against each other.

### Track B — Data (Nidhi)

- **[M]** SQLAlchemy models for the full entity model in `CONTEXT.md` §4, normalised to 3NF.
  Institute → Department → Programme → Semester → Division → Batch; Room → SubRoom; Faculty;
  Subject; Qualification; Cohort; Session; LabBlock; PinnedBlock; Timetable; AbsenceRecord;
  AuditEntry.
- **[M]** Every table carries `department_id` where applicable. `Room` does **not** — it is
  institute-level. This is what makes CSE/EXTC a data problem later, not a migration.
- **[M]** Alembic migration 0001, reversible, applied to Supabase.
- **[M]** `Cohort` as a polymorphic type over Division / Batch / ElectiveGroup /
  CombinedDivisions, with a `members()` resolution that returns the underlying batch set.
- **[M]** Hand-seed the reference data that does not need a parser: 32 faculty with T/P workloads,
  20 rooms with sub-rooms expanded from the separation column, the subject list.
- **[M]** Derive and **verify** the faculty initials → full name mapping; commit it as
  `data/reference/faculty_initials.yaml` with any unresolved initials listed explicitly.
- **[S]** Synthetic instance generator, parameterised by divisions/batches/subjects, for
  benchmarking at scales the real data does not reach.
- **[S]** Constraint-derivation SQL producing conflict edges directly from the hierarchy.

### Track A — Solver (Rohan)

- **[M]** `solver/graph.py` — build a conflict graph from an edge-list payload. Faculty, room and
  cohort-overlap edges, each tagged with its reason.
- **[M]** Cohort overlap must handle **containment**, not just equality: `SE-Comp A batch 1`
  overlaps `SE-Comp A`, and `SE C & D` overlaps both `SE-C` and `SE-D`.
- **[M]** Combined-division lecture → a single vertex over the union cohort.
- **[M]** `solver/colouring.py` — Welsh-Powell greedy, honouring faculty availability windows,
  returning `(assignment, unplaced)`.
- **[M]** Unit tests on hand-built instances where the correct answer is known by inspection,
  including a cross-check against `networkx` colouring (tests only).
- **[S]** `degree()`, `neighbours()` as O(1) adjacency lookups — the repair loop hammers these.
- **[C]** Chromatic lower-bound estimate to warn when the slot grid is too small.

### Track C — Frontend (Dhruv)

- **[M]** Vite + React 18 + TypeScript + Tailwind + shadcn/ui scaffold.
- **[M]** Timetable grid component rendering an 8×5 week from a **static fixture** matching
  `solution_v1` — no backend dependency.
- **[M]** Render the tricky cases from real data: a double-period lab block, four parallel batch
  sessions in one slot, a combined-division lecture, a pinned block.
- **[M]** TypeScript types generated from or hand-mirrored against the contracts.
- **[S]** Light/dark theme, responsive down to tablet width.
- **[C]** Storybook or a `/dev` route showing every cell variant side by side.

### Integration point — end of Week 3

Track B emits a real edge-list payload; Track A colours it; the result is pasted into Track C's
fixture and renders. Done manually, no API yet.

### Exit criterion

**Greedy colouring produces a conflict-free timetable on a synthetic 40-session instance, and the
result renders in the browser.** This is the first demo-able moment — get there on time.

---

## Phase 2 — Real data ingested, core solver (Weeks 4–5)

The heaviest phase. Track B's parser is the long pole.

### Track B — Ingestion (Nidhi)

- **[M]** `ingestion/rooms.py` — parse `classrooms.xlsx`, expand the separation column into
  SubRoom rows.
- **[M]** `ingestion/faculty.py` — parse the faculty timetable docx: names, T/P workloads, and
  their assigned sessions (which independently confirms the class timetables).
- **[M]** `ingestion/class_tt.py` — parse both class timetable docx files. **Per-source field
  order** (see `CONTEXT.md` §3.3); do not attempt one universal regex.
- **[M]** `ingestion/lab_tt.py` — parse the room-wise lab timetable, including the room override
  in parentheses and the stated utilisation percentage.
- **[M]** Recognise and classify pinned blocks (MDM, HSS, LLC, Student Activity, Major Project,
  breaks, ESE exams) rather than failing on them.
- **[M]** `ingestion/anomalies.py` — an anomaly report, not silent correction. Must flag at
  minimum: duplicate room 507, `unsure` room usage, sub-room references exceeding declared
  separation, unresolved faculty initials, unparseable cells.
- **[M]** Seeder writing the canonical JSON into the database inside one transaction.
- **[M]** Real CE EVEN data fully in the database, with the anomaly report committed as evidence.
- **[S]** ODD semester ingested too.
- **[S]** Idempotent re-ingestion — running twice does not duplicate rows.

### Track A — Solver (Rohan)

- **[M]** `solver/backtracking.py` — backtracking with forward checking and MRV ordering.
  Forward checking must record exactly what it pruned so undo is precise.
- **[M]** Lab handling: a `LabBlock` allocates N parallel batch sessions **jointly** across time
  and room, with double-slot contiguity computed on teaching-sequence adjacency.
- **[M]** Sub-room awareness: two sessions may share a physical room in different sub-rooms, but
  not the same sub-room.
- **[M]** Pinned blocks enter as fixed occupancy before solving starts.
- **[M]** Capacity check — room or sub-room capacity ≥ cohort size.
- **[S]** Iterative (explicit-stack) backtracking if recursion depth becomes a concern past ~200
  sessions.
- **[C]** Solve per-division first, then globalise for shared faculty and rooms, if the full
  instance proves slow.

### Track C — Frontend (Dhruv)

- **[M]** Drag-and-drop with `dnd-kit`: a drop is provisional until validated, and reverts with
  the violated constraint named.
- **[M]** Role-differentiated views: administrator, coordinator, faculty, student.
- **[M]** Mock API layer (MSW or equivalent) so the UI is testable before the real API lands.
- **[S]** Vitest + React Testing Library coverage of the grid and the drag interaction.
- **[S]** Anomaly report viewer — renders Track B's ingestion anomalies.

### Integration point — end of Week 5

Real data → edge list → solver → valid timetable, run from a script. Compare the solver's output
against the department's actual published timetable and record where they differ and why.

### Exit criterion

**The real CE EVEN instance is in the database and the solver produces a conflict-free timetable
for it.** Reproduce at least one published lab-utilisation percentage from the parsed data.

---

## Phase 3 — API, quality scoring, role views (Weeks 6–7)

### Track B — Backend (Nidhi)

- **[M]** FastAPI endpoints: `POST /timetables/generate`, `GET /timetables/{id}`,
  `POST /timetables/{id}/validate`, `PATCH /sessions/{id}` (manual edit).
- **[M]** JWT auth with four personas; authorisation enforced server-side on every route.
- **[M]** Pydantic request/response models validated against the contracts.
- **[M]** `AuditEntry` written on every mutating action.
- **[S]** OpenAPI docs reviewed and tidied — it is a viva artefact.
- **[S]** Repository/service layer so routers stay thin.

### Track A — Solver (Rohan)

- **[M]** `solver/scoring.py` — YAML rule engine with a rule registry keyed by rule ID.
- **[M]** The four rules: `FAC_BACK_TO_BACK`, `FAC_LOAD_IMBALANCE`, `STU_IDLE_GAPS`,
  `FAC_DAILY_OVERLOAD`.
- **[M]** `FAC_LOAD_IMBALANCE` uses **T/P-weighted** workload (`6T+8P=14`), not a session count.
- **[M]** `score()` returns `(total, breakdown)` where breakdown names every rule that fired and
  its contribution. Never return a bare number.
- **[M]** YAML validated at load against the registry — an unknown rule ID fails loudly at
  startup.
- **[S]** Calibrate weights against the department's real published timetable — it should score
  reasonably well, which is itself a sanity check on the rules.
- **[C]** Per-division score breakdown in addition to institute-wide.

### Track C — Frontend (Dhruv)

- **[M]** Wire the real API with TanStack Query, replacing the mock layer.
- **[M]** Quality score panel with the rule-by-rule breakdown (Recharts).
- **[M]** Generate flow with progress and error states.
- **[S]** Faculty workload view showing T/P split.
- **[S]** Filter the grid by division, batch, faculty or room.

### Integration point — end of Week 7

An administrator clicks Generate in the browser and sees a scored timetable built from real data.

### Exit criterion

**End-to-end works in the browser.** Everything after this is the novelty features and evidence.

---

## Phase 4 — The two novelty features (Weeks 8–9)

This phase spans all three tracks. Plan it jointly in a session at the start of Week 8 — it is
the one place where the verticals genuinely interlock.

### Feature 1 — Live rescheduling on faculty absence

- **[M]** *(B)* `Qualification` fully populated — which faculty can teach which subject. Derive
  from observed teaching in the real data, then have a human verify it.
- **[M]** *(B)* `POST /absences` and `POST /substitutions`; `AbsenceRecord` persisted.
- **[M]** *(B)* Candidate query: qualified for the subject **and** free in that slot, ordered by
  ascending T/P-weighted workload.
- **[M]** *(A)* Workload recalculation for both the absent and the replacing faculty.
- **[M]** *(C)* Coordinator dual view — free faculty (with workload) beside engaged faculty (with
  the session they are attached to), for any selected slot.
- **[M]** *(C)* Substitution confirm flow; both individual faculty timetables update.
- **[M]** *(B)* Every swap written to the audit log.
- **[S]** Explicit "no qualified faculty free" path that offers repair instead.

### Feature 2 — Infeasibility diagnosis and minimal-disruption repair

- **[M]** *(A)* `solver/mus.py` — deletion-based minimal unsatisfiable subset extraction. A
  timed-out trial counts as "still infeasible" so a non-minimal core is never reported as minimal.
- **[M]** *(A)* Translate the core into institutional terms using the `reason` and entity IDs
  carried on each edge — named faculty, rooms and cohorts, never clause indices.
- **[M]** *(A)* Smallest relaxation suggestion.
- **[M]** *(A)* `solver/repair.py` — freeze-and-expand. Ring expansion is BFS over the conflict
  graph; frozen sessions become fixed constraints, not variables.
- **[M]** *(A)* Return the displaced-session set with every repair — this is the headline metric.
- **[M]** *(B)* `POST /timetables/{id}/repair`, `GET /diagnoses/{id}`.
- **[M]** *(C)* Diagnosis panel naming the conflicting constraints and the suggested relaxation.
- **[S]** *(C)* Repair preview — show what would move before committing.

### Exit criterion

**A coordinator resolves a faculty absence end to end, and a deliberately infeasible instance
returns a readable diagnosis.** Both are demo-critical; neither can be cut.

---

## Phase 5 — Validation and benchmarking (Weeks 10–11)

This phase produces the numbers in the report. Track C leads; A and B fix what it uncovers.

- **[M]** Hypothesis property test: **no generated timetable ever contains a conflict**, across
  randomised instances. This is the correctness claim.
- **[M]** Edge cases: empty input, single session, no qualified replacement, deliberately
  infeasible set, a division with more sessions than slots.
- **[M]** Benchmark — solver runtime against instance size, across synthetic instances of
  increasing scale. Plot it.
- **[M]** Benchmark — **sessions displaced per repair versus full regeneration**, mean with
  confidence interval over many simulated change events. This is the headline result.
- **[M]** Benchmark — greedy-only versus greedy + backtracking quality comparison.
- **[M]** Validation against reality: reproduce the published lab-utilisation percentages;
  compare the generated timetable to the department's actual one.
- **[M]** API integration tests (httpx); frontend tests (Vitest).
- **[S]** Constraint-coverage table — what FET cannot express that Chronos can.
- **[S]** Load test on the generate endpoint.
- **[C]** Sensitivity analysis on quality weights.

### Exit criterion

**Every benchmark number needed for the report exists as a committed plot or table**, reproducible
by re-running `bench/`.

---

## Phase 6 — Deployment and delivery (Week 12)

- **[M]** Production deploy: API on Render/Railway, frontend static, Supabase managed.
- **[M]** Seeded demo data with a safe reset script.
- **[M]** Report: architecture, design decisions traced to courses, results, honest limitations.
- **[M]** Rehearsed demo arc — generate → student and faculty views → mark a faculty absent →
  coordinator picks a replacement → show both timetables update → feed an impossible constraint →
  show the diagnosis.
- **[M]** README with setup instructions that a stranger can follow.
- **[S]** Screencast fallback in case live demo fails.
- **[S]** `docs/` updated so SRS and UML match what was actually built.

---

## Parallel work protocol

Three agentic tools on one repository **will** collide unless the boundaries are explicit.

### Directory ownership is exclusive

| Directory | Owner | Others may |
|---|---|---|
| `solver/` | Rohan | read, open issues |
| `ingestion/`, `db/`, `backend/` | Nidhi | read, open issues |
| `frontend/`, `bench/`, `tests/e2e/` | Dhruv | read, open issues |
| `contracts/` | **all three jointly** | change only by agreement |
| `CONTEXT.md`, `ROADMAP.md` | all three | edit freely, but commit alone |

If your task needs a change in someone else's directory, do not make it. Open an issue, or agree
the contract change first.

### Branching

- `main` is protected. No direct pushes; CI must pass.
- One long-lived branch per member: `track/solver`, `track/data`, `track/frontend`.
- Feature branches off your track branch: `track/solver/mus-extraction`.
- **Merge to `main` at least twice a week.** Long-lived divergence is what actually kills parallel
  student projects — not merge conflicts, but two people building against different assumptions
  for three weeks.
- Rebase your track branch on `main` before every merge.

### Agent-specific discipline

- Give the agent **one track's directory** as its working scope. Do not let it "fix" a failing
  test in another track's directory — that is where silent contract drift starts.
- Start every session by having the agent read `CONTEXT.md`, `ROADMAP.md` and
  `CURRENT-PROGRESS.md`.
- End every session by having it update `CURRENT-PROGRESS.md`.
- Never let two agents run against the same working tree at once. Separate clones or
  `git worktree` if you must work simultaneously on one machine.

### Weekly cadence

A 30-minute sync, same time each week:
1. What merged to `main` since last week
2. What is blocked, and on whom
3. Any contract change requested
4. Update `CURRENT-PROGRESS.md` together

---

## Risk register

| Risk | Likelihood | Mitigation | Cut line |
|---|---|---|---|
| Parser takes longer than two weeks | **High** | Per-source parsers; ship rooms + faculty first | Hand-curate a CSV for the divisions that will not parse; keep the parser for what works |
| Backtracking too slow on the full instance | Medium | Greedy places most sessions; MRV prunes | Solve per-division, globalise only for shared faculty and rooms |
| Contracts drift between tracks | Medium | Schema validation tests on both sides in CI | Freeze harder: no contract change after Week 7 |
| Three agents conflict in git | **High** | Exclusive directory ownership, twice-weekly merges | Serialise: one member merges for everyone |
| ODD semester never gets ingested | Medium | It is **[S]**, not **[M]** | Demo EVEN only; state the scope honestly |
| Scope is simply too large | **High** | MUST/SHOULD/COULD tagging throughout | Protect Phases 4 and 5 — the novelty features and the evidence are what is being graded |
| Faculty qualification data is guesswork | Medium | Derive from observed teaching, then human-verify | Restrict the absence demo to subjects where qualification is confirmed |

### An honest word on scope

Full CE across both semesters, a real docx parser, both novelty features, multi-department
schema design, and a benchmark suite is a lot for three students in twelve weeks alongside
coursework. The plan is achievable **if Phase 2 does not overrun**. If you are behind at the end
of Week 5, cut the ODD semester and the synthetic generator before you cut anything in Phases 4
or 5 — a working demo of the novelty features with EVEN-only data scores far better than a
complete dataset with half-built features.
