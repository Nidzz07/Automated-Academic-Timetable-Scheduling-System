# CURRENT-PROGRESS.md — Chronos

> **Living document. Update it at the end of every work session.**
> Read `CONTEXT.md` for what the system is, `ROADMAP.md` for what to build next, and this file
> for what is already done.

**Last updated:** 2026-09-25 · **by:** NRD · **Current phase:** 0 — Foundation and contract freeze

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

| Phase | Weeks | Status | Exit criterion met? |
|---|---|---|---|
| 0 — Foundation and contracts | 1 | 🟡 In progress | ⬜ |
| 1 — Schema, graph builder, UI shell | 2–3 | ⬜ Not started | ⬜ |
| 2 — Real data, core solver | 4–5 | ⬜ Not started | ⬜ |
| 3 — API, scoring, role views | 6–7 | ⬜ Not started | ⬜ |
| 4 — Novelty features | 8–9 | ⬜ Not started | ⬜ |
| 5 — Validation and benchmarking | 10–11 | ⬜ Not started | ⬜ |
| 6 — Deployment and delivery | 12 | ⬜ Not started | ⬜ |

Legend: ⬜ not started · 🟡 in progress · ✅ complete · ⚠️ blocked · ✂️ cut (note why)

---

## Track status

| Track | Owner | Branch | Current task | State |
|---|---|---|---|---|
| A — Solver | Rohan | `track/solver` | — | ⬜ |
| B — Data & Backend | Nidhi | `track/data` (now merged) | faculty/room seed data — pending faculty name-mapping input | 🟡 |
| C — Frontend & Validation | Dhruv | `track/frontend` | — | ⬜ |

---

## Phase 0 checklist — Foundation and contract freeze

- [x] Repo reconciled against `CONTEXT.md` §7 layout
- [ ] Branch protection on `main`; three track branches created
- [ ] CI running `pytest`, `ruff`, `tsc --noEmit`, `vitest` on push
- [x] `contracts/ingestion_v1.schema.json` written
- [x] `contracts/edge_list_v1.schema.json` written
- [x] `contracts/solution_v1.schema.json` written
- [x] Example payload committed for each contract
- [x] Schema-validation test passing on both sides of each contract
- [x] `SlotId` convention agreed; `is_adjacent()` handles the short break
- [ ] `solver/rules/quality_rules.yaml` seeded with four rules
- [x] `docker-compose.yml` for local Postgres

**Exit:** contract tests green in CI, and all three members can state the three contracts from
memory.

---

## Phase 1 checklist — Schema, graph builder, UI shell

### Track B — Data
- [x] SQLAlchemy models for the full entity model
- [x] `department_id` scoping present; `Room` is institute-level
- [ ] Alembic migration 0001 applied to Supabase
- [x] `Cohort` polymorphic resolution implemented
- [ ] 32 faculty seeded with T/P workloads
- [ ] 20 rooms seeded, sub-rooms expanded from the separation column
- [ ] Faculty initials → name mapping derived and **human-verified**
- [ ] *(S)* Synthetic instance generator
- [ ] *(S)* Constraint-derivation SQL

### Track A — Solver
- [ ] `graph.py` builds a conflict graph from an edge-list payload
- [ ] Cohort overlap handles containment (batch ⊂ division, combined divisions)
- [ ] Combined-division lecture becomes a single vertex
- [ ] `colouring.py` — Welsh-Powell honouring faculty availability
- [ ] Unit tests on hand-built instances
- [ ] `networkx` cross-check in tests only
- [ ] *(S)* O(1) adjacency lookups

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
- [ ] `backtracking.py` — forward checking with exact undo, MRV ordering
- [ ] `LabBlock` — N parallel batch sessions allocated jointly
- [ ] Double-slot contiguity on teaching-sequence adjacency
- [ ] Sub-room awareness (same room, different sub-room is legal)
- [ ] Pinned blocks as fixed occupancy
- [ ] Capacity check against cohort size
- [ ] *(S)* Iterative backtracking if depth becomes a problem

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
- [ ] `mus.py` — deletion-based extraction; timeout counts as infeasible
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

- [ ] Hypothesis property test: no timetable ever contains a conflict
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

- `2026-09-25` · NRD · `db/models.py` + Alembic migration 0001 landed; 148 tests passing; `Cohort` polymorphism, institute-level `Room`, and a remote-DB safety guard in `migrations/env.py`. · _no PR (direct to `track/data`)_
- `2026-09-24` · NRD · Phase 0 contracts + `solver/slots.py` + CI workflow landed — three frozen JSON Schemas with example payloads, 41 schema-validation tests, the wall-clock slot module with 48 tests, GitHub Actions running `ruff check` + `pytest`, and a root `pyproject.toml`. 89 tests green. · _no PR (direct to `main`, pre-branch-protection)_

---

## Blockers

| Since | Blocker | Blocks whom | Needs |
|---|---|---|---|
| — | — | — | — |

---

## Decision log

Record any choice a future session might otherwise re-litigate.

| Date | Decision | Rationale | Decided by |
|---|---|---|---|
| — | Scope: CE only, ODD + EVEN, schema designed for CSE/EXTC | Real data is CE; multi-dept later must not need a migration | All three |
| — | Ingestion parser is a real phase, not hand-curated data | Demonstrable feature: ingests the department's actual files | All three |
| 2026-09-25 | `migrations/env.py` refuses to run against any non-local database host unless `CHRONOS_ALLOW_REMOTE_DB=1` is explicitly set | Prevents an accidental migration against shared Supabase staging. `backend/.env` pointed at Supabase at the time, so a plain `alembic upgrade head` would have hit it. | Nidhi |
| 2026-09-25 | `Session.room_id` and `Session.sub_room_id` are mutually exclusive but **both-nullable** — not "exactly one required" | `contracts/ingestion_v1.schema.json` allows `room_id: null` for sessions whose room reference is missing or unresolved (CONTEXT.md §3.5 known data defects). The anomaly reporter must be able to **store** those sessions rather than discard them. | Nidhi |
| 2026-09-24 | Edge-list contract indexes periods on the **wall clock, 0–9**, with `teaching_periods` marking the 8 schedulable slots (2 = short break, 5 = lunch) | Lets `is_adjacent()` distinguish clock-adjacency from teaching-sequence adjacency, so a double lab can span the short break (periods 1→3) and lunch (4→6) — which the real data does (`ET Lab /DDA /509 (10.00 -12.00)`). Ingestion keeps its own teaching-order `period: 0..7`; translating between the two axes is the data layer's job and the axis must never leak into `solver/`. | NRD |

---

## Contract change log

Changing a contract requires all three members to agree. Log every change here.

| Date | Contract | Change | Agreed by |
|---|---|---|---|
| 2026-09-24 | `edge_list_v1.schema.json` | Added `default` annotations to the four `slot_grid` fields (`days`, `periods_per_day`, `teaching_periods`, `adjacency`) recording the canonical SPIT grid. **Non-breaking — `default` is annotation-only in JSON Schema, so validation behaviour is unchanged** (the 41 pre-existing contract tests pass untouched). Done so `solver/slots.py` can be drift-checked against the schema file itself rather than against a duplicated literal. | NRD — pending Rohan's and Dhruv's sign-off once onboarded |

---

## Cut list

Anything dropped from `ROADMAP.md`, with the reason. Keeps the report honest about scope.

| Phase | Item | Why cut | Date |
|---|---|---|---|
| — | — | — | — |
