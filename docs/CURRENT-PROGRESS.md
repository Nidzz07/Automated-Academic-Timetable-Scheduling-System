# CURRENT-PROGRESS.md — Chronos

> **Living document. Update it at the end of every work session.**
> Read `docs/CONTEXT.md` for what the system is, `ROADMAP.md` (repo root) for what to build
> next, and this file for what is already done.

**Last updated:** 2026-10-12 · **by:** Nidhi — S6 with Claude Code (branch `track/data-class-tt`, not yet committed): `ingestion/scheme.py`, `ingestion/class_tt.py`, `ingestion/class_tt_report.txt` · **Current phase:** 0–2 in progress; no phase exit criterion met yet

---

## Update protocol
| A — Solver                | Dhruv | `track/solver-scoring`                                      | S4 (PR #23) and S8 (PR #27) merged: pre-solve, payload grid, `solution.v2` output. S10 in review (not merged, branch `track/solver-scoring`): `solver/scoring.py` scores the four D34 rules from `solver/rules/quality_rules.yaml` (version "1"); `to_solution_v2_dict()` carries the real score. Open: a pre-solve certificate still has no `solution.v2` `diagnosis.method` (row 9 not in the schema); S-GAP cannot tell label-only frozen pins from lunch (edge-list pins carry no kind). Next: S12 integration | 🟡    |
| B — Data & Backend        | Nidhi | `track/data-seed-export` (S9, not committed) | Merged: reference seed + division-scoped faculty initials (41 faculty, migration 0004), S6 `class_tt.py` (PR #21), S3b row 8 in `ingestion.v2` (PR #25). S7 (`lab_tt`, `faculty`, `anomalies`, `emit_v2`) in review. S9 in the working tree: D35–D38, D42, D44, D45 applied in `emit_v2`; migration 0005; `ingestion/seed_even.py`; `db/export_edge_list.py`; committed snapshot `data/instances/even-2025-26/edge_list.json` + `display.json` (D41). Open: 61 anomalies need a human; migration 0005 applied locally only (Supabase is a team decision). Next: S12 integration (solve the real instance) | 🟡    |
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
| C — Frontend & Validation | Rohan | `track/frontend-v2-rooms` | Phase 1 grid and Phase 2 drag-and-drop / role views / mock API merged (PR#6, #14), all running against contract fixtures and a mock client — not yet wired to a real API. S11 in review (not merged, branch `track/frontend-v2-rooms`): `solution.v2` adopted, grid read from the edge list (D6 per-year lunch), room timetable, free rooms, quality flags with not-evaluated rules; S11b removes invented UI content (persona names, hard-coded load status, stand-in score) | 🟡 |
---

## Phase 0 checklist — Foundation and contract freeze

- [X] Repo reconciled against `CONTEXT.md` §7 layout
- [ ] Branch protection on `main`; three track branches created
- [X] CI running `pytest`, `ruff`, `tsc --noEmit`, `vitest` on push _(`.github/workflows/ci.yml`; frontend job added in PR #16 — `tsc` runs via `npm run build`)_
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

- [X] Vite + React + TS + Tailwind + shadcn/ui scaffold _(PR #6)_
- [X] Grid renders an 8×5 week from a static `solution_v1` fixture _(PR #6; `TimetableGrid.test.tsx`)_
- [X] Renders: double-period lab, four parallel batches, combined lecture, pinned block _(PR #6)_
- [ ] TypeScript types mirror the contracts _(S5, not merged: generated from `contracts/*_v1.schema.json` by `npm run gen:types`, rerun on every `npm run build`)_
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
- [X] Fix: `fixed_slot` intersected with availability, never substituted for it (proposal §5.1 obs. 1) _(PR #15; `TestRegressionFixedSlotVsAvailability`)_ — in `backtracking.py` (PR #15); `colouring.py` fixed in PR #18
- [X] Fix: every period of a multi-period placement checked, in a LabBlock or not (proposal §5.1 obs. 2) _(PR #15; `TestRegressionMultiPeriodOccupancy`)_ — in `backtracking.py` (PR #15); `colouring.py` fixed in PR #18
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

- [X] Drag-and-drop with provisional drop and revert-on-reject _(PR #14; `DragAndDrop.test.tsx`)_
- [X] Four role-differentiated views _(PR #14; `RoleViews.test.tsx`)_
- [X] Mock API layer _(PR #14; `MockChronosApiClient`, `chronosApi.test.ts`)_
- [X] *(S)* Vitest coverage of grid and drag _(PR #6, #14)_
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

- [ ] Real API wired via TanStack Query _(S5, not merged: TanStack Query wraps `ChronosApiClient` with loading / error / empty states; still `MockChronosApiClient` until S13)_
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

- [ ] Hypothesis property test: no timetable ever contains a conflict _(a seeded-random property test now exists: `solver/tests/test_property_solved_is_valid.py`, 400 instances, seed 20261003 — backtracking and, since PR #18, Welsh-Powell too)_
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

- `2026-10-18` · Nidhi (with Claude Code) · **S9: real EVEN SE+TE instance finished, seeded and exported as `edge_list_v1`.** Part A (`emit_v2`): D38 resolves AGN, PBB, NR, IS, SM (TE), AT, RS, SB per year, checked against the year's legends and Faculty___Subjects.xlsx (`lab_tt.d38_member`): 0 sessions without a teacher (12 in S7). D44: all 20 AS201 PCS lines (4 tutorials, 16 practicals; teachers DN, SD, SM (SE), AY are legend-only) are frozen, a batch practical holding its batch only. D42: 605 and 609 (capacity 80) are classrooms. New `ingestion/out_of_scope.py`: D35 blocks from the BE/M.Tech class grids, the lab timetable and the faculty timetable (FE PSOOP is printed only there), merged per teacher and slot; faculty-page MDM theory/labs (D24); the DAA lab exam (D37, sub-room 603-2). D36: Swapnali Kurhade unavailable Monday. D45: Faculty___Subjects.xlsx spelling is the name, 9 legend spellings plus D25's name are aliases. The D39 side file now carries `frozen`, `blocks`, `unavailability` and `faculty`. Generated `docs/faculty-mapping-even-2025-26.md` (staleness test). Instance vs S7: lectures 56 (=), tutorials 8→4, practicals 112→96, frozen sessions 54→74 (D24 39, D26 15, D44 20), unresolved 12→0, classrooms 2→4, classroom demand 64→60 periods with 23 frozen classroom periods (0 before), lab demand 224→192 batch-place periods with 147 frozen (84 before), 64 side blocks (D35 58, D24 5, D37 1); anomalies 385→475, needs human 86→61. Part B: migration 0005 (pinned block teacher/room/timetable/source ref and kind `out_of_scope`; session `frozen_by` and `source_ref`; `source_ref` on cohort and lab block; term-wide timetable; tables `faculty_unavailability`, `timetable_room`), lossy downgrade refused, applied to the local DB only. `ingestion/seed_even.py`: one transaction, idempotent (snapshot test), stale rows deleted, local DB only (`db/local_guard.py`), Room rows never rewritten. Part C: `db/export_edge_list.py` (DB only + `time_grid.yaml`): 156 sessions, 1568 edges (FACULTY, COHORT; no session has a single candidate room, so no ROOM edge), 25 rooms, 31 lab blocks, 339 pins (per-year lunch listing every cohort of the year; frozen items with teacher, room and every overlapping cohort), schema-valid, byte-identical on re-export and equal to the committed snapshot (`db/tests/test_even_instance.py`). Solver not run. `pytest -q -rs`: 827 passed, 0 skipped. · _no PR yet (branch `track/data-seed-export`)_

- `2026-10-18` · Nidhi (with Claude Code) · **Contract row 9: `diagnosis.method = "presolve"` in `solution.v2`.** Signed by all three on 2026-10-18 (ROADMAP D43, proposal §11 row 9). `contracts/solution_v2.schema.json`: `presolve` joins the method enum; when `method = presolve`, `minimal_conflicting_set` needs at least one entry, `suggested_relaxation` is required and `partial_placement` must be empty, so every session is unplaced. The method, conflicting-set, relaxation and partial-placement descriptions say so, and call the set not minimal. New `contracts/examples/solution_v2.presolve.example.json` is the solver's own output on the synthetic `infeasible` preset (seed 1, synthetic ids, run read-only): `Certificate.to_v2_fields()` (`presolve.cohort_load.d00`, `COHORT_CLASH`, 39 slots, MANUAL with `not_attempted`), an empty partial placement, all 46 sessions unplaced. `tests/contracts/test_schemas_v2.py`: the example validates; presolve with an empty set, without a relaxation or with a placed session is rejected; the partition, relaxation-in-set and permitted-action checks run on it too; none of its descriptions says "minimal". Not adopted yet: `to_solution_v2_dict()` still refuses a certificate (Track A) and the frontend has no `presolve` label (Track C). · _no PR yet (branch `contracts/row9-presolve`)_

- `2026-10-17` · Dhruv (with Claude Code) · **S10: quality scoring.** New `solver/rules/quality_rules.yaml` (version "1"): exactly the four D34 rules with description, weight and parameters, each weight justified in one line (S-GAP 2.0, the largest per D13; S-B2B 1.0; S-LOAD16 1.0 with `threshold_hours: 16` per D11; FAC_LOAD_IMBALANCE 0.5). The loader fails loudly on an unknown, missing or repeated rule id, an unknown key or parameter, a bad weight or version. New `solver/scoring.py` (PyYAML here only, as the S10 exception allows) scores a solved timetable from the edge list and start slots. S-GAP: idle teaching periods between a cohort's first and last class, per cohort and day; cohorts sharing students via COHORT edges, pins busy, only pins booking a teacher or room open or close a day, so lunch never does. S-B2B: adjacency pairs on the payload grid taught in two different sessions (one lab alone is not back-to-back; pin–pin pairs never count). S-LOAD16: teachers above 16 h (sessions by their periods, frozen slots once each). FAC_LOAD_IMBALANCE: heaviest minus lightest day over every weekday, summed over faculty. Score = 100 − Σ penalties, the contract examples' arithmetic. `to_solution_v2_dict()` now carries the real score; the S8 stand-ins are gone; v1 keeps its placeholder. Pre-solve certificates stay refused in v2: the schema still has no `presolve` method. Score distributions (seeds 1–10): small 75 to 88, medium −63 to 24.5, large −238.5 to −150.5 (the search does not optimise quality; weights not tuned). `pytest solver/tests`: 325 passed, 0 skipped. · _no PR yet (branch `track/solver-scoring`)_

- `2026-10-17` · Rohan (with Claude Code) · **S11b: invented and misleading UI content removed.** Persona selectors list only what the payload holds (faculty initials placed in the solution, cohorts named in the edge list); the made-up "Dr. Abha N." and the "Prof." prefixes are gone. `FacultyWorkloadCard` no longer says "Normal Load (Within 5–18h)": its status is the solver's S-LOAD16 entry ("not evaluated" when not evaluated; D11, D34). `toQualityView` returns `score: null` when no rule was evaluated (S8's stand-in 100.0 until S10), and the card then shows "Score not available until rules are evaluated"; the score shows, with the Partial badge, once at least one rule is evaluated. `diagnosis.method` labels live in one table, `DIAGNOSIS_METHOD_LABELS` in `src/adapters/solution.ts`, so a new method is one line. Also removed: the "(100%)" placement label and the mock's invented +1.2 ms added to `runtime_ms` on every move. 83 Vitest tests. · _no PR yet (branch `track/frontend-v2-rooms`)_

- `2026-10-17` · Rohan (with Claude Code) · **S11: frontend adopts `solution.v2`; grid from data; room timetable and free rooms.** `contractValidation.ts` validates `solution.v2` with ajv against `contracts/solution_v2.schema.json`; `parseSolution` routes by `schema_version` and still accepts v1. `gen:types` now covers `contracts/*.schema.json` with `--unreachableDefinitions` (adds `Kind`, `SlotRef`, `Placement`); json2ts collapses v2's `diagnosis` and breakdown entries, so their shapes are written out in `src/adapters/solution.ts`, which maps both versions to `QualityView` (per-rule `evaluated` / `not_evaluated`, `rules_version`) and `DiagnosisView` (`method`, closed kinds, `slots`, typed action + verification, partial placement). Every hard-coded period, time, break, lunch, pinned block ("MDM - I THEORY", "HSS II") and lab-block label is gone: rows are the edge list's wall-clock periods (P0..P9, no clock times: no contract carries them), non-teaching periods are break rows, and a pin holding cohorts only (no teacher, no room: D24) is shown as that year's lunch, so the D6 example shows SE lunch at P5 and TE at P4. New `src/adapters/rooms.ts` + `RoomViews.tsx`: weekly room timetable and free rooms at a day/period, labs listing the sub-rooms (batch places) still free; rooms from the edge list, occupancy from the solution + `pinned_occupancy`. Quality card shows the four D34 rules as the solver sent them; a `not_evaluated` rule shows "not evaluated" and its reason, never a number. The mock serves the v2 examples and both edge-list examples (header "Instance" switch for the D6 grid, which has no solution) and checks drops against `pinned_occupancy` by cohort, teacher and room instead of hard-coded slots. 78 Vitest tests (40 before); `npm run build` clean. · _no PR yet (branch `track/frontend-v2-rooms`)_

- `2026-10-17` · Dhruv (with Claude Code) · **S8: the solver reads the payload's grid and emits `solution.v2`.** New `solver.slots.SlotGrid` reads `slot_grid` (days, teaching periods, adjacency); any well-formed grid is accepted and a malformed one, or a slot off it, raises. The graph, search chains, Welsh-Powell, pre-solve and `validate._check_grid` all read it; the canonical constants stay only as test helpers (a test checks no solver module imports them). `SlotId` no longer caps the period at 9 and prints no break label, since under D6 lunch depends on the year. On the D6 example (`solver/tests/test_d6_grid.py`): an SE lab block over P4–P5 is rejected, a TE block over P5–P6 and a block over P1–P3 are accepted, a D24 frozen pin is never covered, and each year has its own 40 periods for search and pre-solve alike. On the canonical grid the 400 property instances and every synthetic preset (seeds 1–3) give the pre-S8 answers (search, certificates, Welsh-Powell), checked by digest in `test_search_equivalence.py`. `BacktrackResult.to_solution_v2_dict()` sits beside the v1 output, which is unchanged. Solved: every D34 rule `not_evaluated`, with stand-ins until S10 (score 100.0, weight 0.0, `rules_version` "none"). Infeasible after search: `method = search_exhaustion`, empty set, no relaxation, the deepest consistent partial placement (first reached) and the unplaced ids. A timeout raises (D33). A pre-solve certificate raises too: it is neither a MUS nor search exhaustion, so there is no honest `method` (proposed contract row 9). `Certificate.to_v2_fields()` already gives its closed-kind entry with slots and a MANUAL relaxation (`not_attempted`); the solver never suggests RELAX_PINNED_BLOCK, because edge-list pins carry no kind and lunch cannot be told apart. The `test_validate` skip is fixed: it reads `contracts/examples` only. `pytest solver/tests`: 303 passed, 0 skipped. · _no PR yet (branch `track/solver-v2-grid`)_

- `2026-10-16` · Nidhi (with Claude Code) · **S7: lab and faculty timetables parsed, D23–D30 applied, real EVEN SE+TE instance emitted as `ingestion.v2`.** `data/reference/time_grid.yaml` is ROADMAP §5 as data (test checks it against §5); `class_tt.py` reads it (its report is unchanged). `ingestion/lab_tt.py` parses the 15 room tables (157 cells), normalises rooms per D27/D30, builds the D8 + D10 room inventory (16 batch places), reproduces 11 of 15 printed utilisations exactly (603-2, 603-3, 603-7, 702-A differ and are reported) and cross-checks every in-scope practical against the class timetable (1 day/period mismatch, 5 missing from the lab timetable, 1 room mismatch). `ingestion/faculty.py` reads the 32 pages and their load lines and compares them with loads computed from the class and lab timetables (D11, D23, D25 for SRD); 22 mismatches, mostly FE/BE/M.Tech teaching outside these grids or unresolved initials. `ingestion/anomalies.py` writes one combined report (`ingestion/anomaly_report.txt`, freshness test; 385 anomalies, 86 need a human). `ingestion/emit_v2.py` writes `data/generated/ingestion_v2_even.json` (8 divisions, 32 batches, 56 lectures, 8 division tutorials, 112 practicals in 31 lab blocks, 54 frozen sessions, 64 frozen pinned blocks, 45 breaks, 41 faculty, 13 rooms), validated against `contracts/ingestion_v2.schema.json` plus reference checks and the own-year-lunch rule. ingestion.v2 has no "frozen" flag and `pinned_blocks` carry no teacher or room, so frozen session ids go to `ingestion_v2_even.frozen.json` (contract gap, for S9). `PyYAML==6.0.3` added to requirements. No DB writes. · _no PR yet (branch `track/data-lab-faculty`)_
- `2026-10-16` · Nidhi (with Claude Code) · **S3b: contract v2 proposal row 8 folded into `ingestion.v2`.** Row 8 signed by all three on 2026-10-15 (ROADMAP D31). `observed_sessions[].period`, `lab_blocks[].start_period` and `pinned_blocks[].period` use `$defs/period`, the wall-clock axis 0..9 of ROADMAP §5 (the 0..7 `teaching_period` is removed). Coffee break = `kind: break`, period 2, `cohort_id: null`; each year's lunch = `kind: break` per division cohort of that year (P5 SE, P4 TE). New `contracts/examples/edge_list_v1.d6_grid.example.json` shows the D6 grid in the frozen `edge_list_v1`, with lunch as `pinned_occupancy`. An SE session in its lunch is not a schema error; it becomes a validator rule in S7. The Row 8 assessment section of `docs/contract-change-proposal-v2.md`, lost in the PR #24 merge, is restored word for word. v1 files unchanged. · _no PR yet (branch `contracts/row8-ingestion-v2`)_
- `2026-10-12` · Rohan · **S5: frontend consumes the real v1 contracts.** `frontend/src/fixtures/` deleted; fixtures, schemas and examples are imported from `contracts/` through the `@contracts` Vite/TS alias. `src/api/contractValidation.ts` validates every payload with ajv (draft 2020-12) against `contracts/*_v1.schema.json` and throws a typed `ContractValidationError` that the UI shows. Types are generated by json-schema-to-typescript into `src/types/generated/` (`npm run gen:types`, also run by `prebuild`); the hand-written `types/solution.ts` and `types/edge_list.ts` and every `as unknown as` cast are gone. Contract → view-model mapping lives in `src/adapters/` only. TanStack Query (`src/api/queries.ts`) wraps `ChronosApiClient`; the mock stays the implementation. 40 Vitest tests (25 before). No v2 field used. · _no PR yet (branch `track/frontend-contracts`)_
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
  · PR #18
- `2026-10-06` · Nidhi, Rohan, Dhruv · **Contract v2 proposal signed off by all three tracks.**
  `docs/contract-change-proposal-v2.md` §11 rows 1–7 all marked Agree with no changes (row 7, the
  `FAC_LOAD_IMBALANCE` ROADMAP clarification, needed only the Track A owner's Agree — Dhruv per ROADMAP D1; see D17). **No schema files have
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
- `2026-09-26` · Dhruv · Phase 1 & 2 Track A (Solver) landed: `solver/graph.py` (conflict graph with cohort containment), `solver/colouring.py` (Welsh-Powell greedy with availability & pinned awareness), and `solver/backtracking.py` (backtracking search with forward checking, trail-based exact undo, MRV ordering, LabBlock joint placement, sub-room awareness, capacity checks, and `solution_v1` serialisation). 159 tests green across full suite. · PR #5, #13
- `2026-09-25` · NRD · Reference seed landed — 20 rooms + 8 sub-rooms, 33 faculty, 25 subjects, 64 qualifications, and the partial 8-of-33 initials map, from the three spreadsheets in `data/real/`. Two schema corrections came with it (migrations 0002, 0003 — see Decision log). 210 tests passing. · PR #3 (`track/data-seed`)
- `2026-09-25` · NRD · `db/models.py` + Alembic migration 0001 landed; 148 tests passing; `Cohort` polymorphism, institute-level `Room`, and a remote-DB safety guard in `migrations/env.py`. · PR #1, #2 (`track/data`)
- `2026-09-24` · NRD · Phase 0 contracts + `solver/slots.py` + CI workflow landed — three frozen JSON Schemas with example payloads, 41 schema-validation tests, the wall-clock slot module with 48 tests, GitHub Actions running `ruff check` + `pytest`, and a root `pyproject.toml`. 89 tests green. · _no PR (direct to `main`, pre-branch-protection)_

---

## Blockers

| Since      | Blocker                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Blocks whom                                                                                                   | Needs                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 2026-10-03 | ✅**Resolved 2026-10-06** (PR #18, branch `track/solver-baseline`; see `docs/solver-baseline-2026-10-06.md`). Was: `solver/colouring.py` (Welsh-Powell) produces invalid timetables: it checks only a multi-period session's start slot, colours lab-block members independently, and places `fixed_slot` sessions with no availability, pinned or neighbour check. On the 400-instance property generator, 338 of 394 complete colourings violate a hard constraint. Recorded as a strict `xfail`; the validator was not loosened. Single-period, block-free, fixed-free instances are clean (400/400). | Anyone using greedy output as a timetable or as a backtracking seed; Phase 5 greedy-vs-backtracking benchmark | Nothing — resolved (was: Dhruv — fix or scope Welsh-Powell to the single-period subclass)    |
| 2026-10-03 | `edge_list_v1` rooms carry `is_lab: boolean`, not the three-valued `room_type`; `unknown` cannot reach the solver                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Exact`RECLASSIFY_ROOM` semantics for rooms 605/609                                                          | All three — decide whether a future edge-list revision carries`room_type` (contract change) |

---

## Decision log

Record any choice a future session might otherwise re-litigate.

Decisions D1–D22 are recorded in `ROADMAP.md` §3 and are binding; this log keeps the earlier entries and adds detail.

| Date       | Decision                                                                                                                                                                                                                                                                                                                                                                                         | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Decided by                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| 2026-10-12 | S4 (uncommitted, `track/solver-presolve`): a search timeout stays internal (`BacktrackResult.outcome == "timeout"`); `to_solution_dict()` raises on it instead of emitting `infeasible`. | `solution_v1.status` is `solved \| infeasible` only, and v2 has no top-level timeout either. D21 forbids reporting a timeout as infeasible. A contract change is needed before the API can return it. | Dhruv (S4, with Claude Code) |
| 2026-10-12 | S4: a pre-solve failure is reported in the v1 `diagnosis` fields. It has one `minimal_conflicting_set` entry, `constraint_id = presolve.<check>.<resource>`, and its `kind` set to the v2 closed kind the check maps to (`FACULTY_CLASH`, `COHORT_CLASH`, `ROOM_OCCUPANCY`, `ROOM_TYPE`, `ROOM_CAPACITY`). Cohort groups are cliques grown from COHORT edges, because `edge_list_v1` has no division→batch hierarchy. | v1 `kind` is a free string, so the v2 values are legal now and need no mapping later. The certificate is a proof, not a MUS, and v1 cannot say so; v2's `diagnosis.method` will. Using edges only means pre-solve never claims a conflict that the search would not enforce. | Dhruv (S4, with Claude Code) |
| 2026-10-12 | S6 `class_tt.py`: timetable subjects match scheme codes only through the hand-reviewed `SUBJECT_ALIASES` table (OS, DAA, CCN, PCS, SMCS, SPCC, ML are acronyms of the scheme names, checked by a test; `Devop`/`Devops`/`Deop` → CE308 by hand). `FOM - II` (12 SE lines, parallel to SMCS) matches nothing and is reported as unmatched. | The acronym of "DevOps Lab" would be `DL`, which the TE grids use for the Deep Learning elective, so acronyms cannot be derived automatically. | Nidhi (S6, with Claude Code) |
| 2026-10-12 | S6: faculty initials resolve only through the division's own legend (`seed_legends` logic, no DB read). An initial missing from that legend (`SRD` in all four TE divisions; `AGN`, `PBB`, `NR`, `IS`, `SM`, `AT` in single divisions) is flagged with hints from other legends, never resolved and never excluded: absence from a legend does not prove the teacher is not CE faculty (D3). | Borrowing another division's mapping is the silent guess D20 forbids. `if_ce_faculty` courses (PCS) are the exception: they stay in scope only when every candidate is in the 41-member list. | Nidhi (S6, with Claude Code) |
| 2026-10-12 | S6: a subject is an elective when it carries a `PE-…` group marker anywhere in the same division grid, so `DL / SJ / 508` lecture lines are excluded as electives too. A division-wide tutorial (PCS in SE, DevOps in TE) counts towards every batch's T hours and is flagged against D9. Document times are read as a 12-hour clock (`1.15` = 13:15). | All three follow from the document as printed; each is visible in `ingestion/class_tt_report.txt`. | Nidhi (S6, with Claude Code) |
| 2026-10-03 | `ingestion/seed_legends.py` writes reference data (initials legends, legend-only faculty, aliases) straight to the database, **bypassing the ingestion contract**. Reference data only: timetable observations must go through the contract (`ingestion/class_tt.py` emits `ingestion.v2` payloads that the seeder consumes). | Proposal §10 records it as deliberate and limited to reference data; copied here as proposal §7 step 3 asks. | Nidhi (proposed in `docs/contract-change-proposal-v2.md` §10; not one of the signed §11 rows) |
| 2026-10-03 | **D20:** faculty initials are stored in the DB table `faculty_initials` (migration 0004), division-scoped, with ambiguous initials flagged — instead of the `data/reference/faculty_initials.yaml` file the old ROADMAP named. | Initials are division-scoped and can be ambiguous (ODD BE `SK`); a DB table holds the scope and the ambiguity flag, and nothing is picked silently. See ROADMAP §3 D20. | Nidhi |
| 2026-10-03 | A`fixed_slot` restricts where a session may **start**; it is intersected with availability (faculty, cohort, pinned) and every other constraint, never substituted for it. Empty intersection ⇒ infeasible.                                                                                                                                                                             | A frozen session in a slot its teacher cannot attend is not a timetable. Substituting meant`FIXED_SLOT` vs `FACULTY_UNAVAILABLE` could never surface in a MUS.                                                                                                                                                                                                                                                                                                                                                                 | Dhruv (Track A fix) |
| 2026-10-03 | Solver`Room` carries `room_type` (class \| lab \| unknown); only `lab` hosts a `requires_lab` session. Under `edge_list_v1` it is derived from `is_lab` (true→lab, false→class). Rooms 605/609 (`unsure` → `unknown`) stay unusable for labs until reclassified — exactly the `RECLASSIFY_ROOM` relaxation.                                                                | `unknown` must never be silently treated as a lab. The edge list is frozen, so the three-valued type lives inside the solver only.                                                                                                                                                                                                                                                                                                                                                                                               | Dhruv              |
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
| 2026-10-12 | `ingestion_v2.schema.json`, `solution_v2.schema.json`, `relaxation_actions_v2.json` (new) | v2 files written from `docs/contract-change-proposal-v2.md` rows 1–6 (S3). `ingestion.v2` (row 1): `faculty[].initials` removed; top-level `faculty_initials[]` (division-scoped, `is_ambiguous`, `legend_ref`); every observed session carries `faculty_initials_raw` and exactly one resolution state (resolved / ambiguous with ≥ 2 `faculty_candidates` / unresolved); anomaly code `AMBIGUOUS_FACULTY_INITIALS`. `solution.v2` (rows 2–6): `diagnosis.partial_placement` + `unplaced_session_ids`; infeasible forbids `assignment`, `quality`, `displaced`; closed `kind` enum (10 members; `UNSATISFIABLE_DOMAIN` / `INFEASIBLE_INSTANCE` retired); `diagnosis.method` (`mus` \| `search_exhaustion`); `minimal_conflicting_set[].slots`; typed `suggested_relaxation.action` + `verification`; quality `rules_version`, per-rule `status`, `not_evaluated_rule_ids`. Kind → action map in `relaxation_actions_v2.json`. v1 files unchanged; examples and `tests/contracts/test_schemas_v2.py` added. **Breaking (new versions).** No producer or consumer uses v2 yet: solver, seeder and frontend migrate in their own steps. | Nidhi, Rohan, Dhruv (proposal §11 rows 1–6, 2026-10-06) |
| 2026-10-15 | `ingestion_v2.schema.json` (amended in place), `examples/edge_list_v1.d6_grid.example.json` (new) | Proposal row 8 (ROADMAP D6, D31) folded into `ingestion.v2`: the three period fields move to the wall-clock axis 0..9 (`$defs/period`); the coffee break and each year's lunch are `pinned_blocks` of kind `break` (per-year lunch as pinned breaks); D6 edge-list example added. **Breaking for `ingestion.v2`** (no producer emits it yet, so amended rather than versioned to v3). `edge_list_v1` and `solution_v2` unchanged: per-year lunch is data there. | Nidhi, Rohan, Dhruv (proposal §11 row 8, 2026-10-15) |
| 2026-10-18 | `solution_v2.schema.json` (amended in place), `examples/solution_v2.presolve.example.json` (new) | Proposal row 9 (ROADMAP D43): `diagnosis.method` gains `presolve`. A pre-solve certificate proves the instance jointly unsatisfiable before any search; it is not minimal. When `method = presolve`: `minimal_conflicting_set` has `minItems: 1`, `suggested_relaxation` is required, `partial_placement` has `maxItems: 0` (every session unplaced). Widens an enum, so every existing payload stays valid; amended in place, not versioned. Consumers that switch on `method` need a `presolve` case. No producer emits it yet. | Nidhi, Rohan, Dhruv (proposal §11 row 9, 2026-10-18) |

---

## Cut list

Anything dropped from `ROADMAP.md`, with the reason. Keeps the report honest about scope.

| Phase | Item | Why cut | Date |
| ----- | ---- | ------- | ---- |
| —    | —   | —      | —   |
