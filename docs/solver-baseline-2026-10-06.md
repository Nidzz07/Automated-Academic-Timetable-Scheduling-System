# Solver baseline — 2026-10-06

An honest first measurement of the current solver on synthetic instances, taken after the
Welsh-Powell fix (Track A, Step 3). Nothing was tuned: the solver ran with its defaults.

- **Code:** `main` @ `30b6aac` plus the uncommitted Step 3 changes (`solver/colouring.py`
  fix, `solver/graph.py` lab blocks, `solver/benchmarks/`).
- **Reproduce:** `python -m solver.benchmarks.baseline --seed 1 --timeout 300` (repo root,
  venv active). Each solve runs in a child process and is killed at the limit.
- **Generator:** `solver/benchmarks/synthetic.py`. The same preset and seed give
  byte-identical `edge_list_v1` JSON (tested across interpreters and hash seeds).
- **Synthetic only.** Every preset is synthetic and sized for scaling tests only; none of them
  is SPIT data. The only parameter taken from a real file is the `large` preset's room
  inventory (`data/real/classrooms.xlsx`). Every other parameter is synthetic.
- **Superseded later.** The real SPIT baseline will be measured on the real instance from the
  ingestion pipeline (DB → `edge_list_v1` export, Phase 2), and this doc will be superseded then.

## Presets and assumptions

| Preset | Divisions × batches | Theory / division | Lab blocks / division | Faculty | Rooms | Pins / division | Unavailable slots / faculty | Combined lectures |
|---|---|---|---|---|---|---|---|---|
| small | 2 × 2 | 2 subjects × 2 h | 1 (double) | 6 | 4 physical, 1 split in 2 | 1 | 2 | 0 |
| medium | 4 × 4 | 4 subjects × 3 h | 2 (double) | 16 | 8 physical, 2 split in 3 | 2 | 3 | 1 |
| large | 10 × 4 | 4 subjects × 3 h | 3 (double) | 41 | 20 physical, from `data/real/classrooms.xlsx` | 2 | 4 | 2 |
| infeasible | as small, plus extra theory for division `d00` | | | | | | | |

Where each parameter comes from:

- **`small`, `medium`, `infeasible`:** every parameter is synthetic, rooms included.
- **`large`, taken from a real file:** the room inventory only, from
  `data/real/classrooms.xlsx` (20 rows; checked row by row against the file on 2026-10-06).
  Capacities and sub-room splits are copied; ids are synthetic. "Used as" maps to `is_lab` as
  under `edge_list_v1`: lab, "as a lab" and "Mtech lab" are labs; class and "unsure" (605,
  609) are not. That gives 11 lab rooms (3 split into 8 sub-rooms) and 9 non-lab rooms.
- **`large`, synthetic:** every other parameter.
  - 10 divisions × 4 batches and 41 faculty. Only the counts were chosen to match
    `docs/CONTEXT.md` §3.1; the divisions, batches, faculty and teaching assignments are
    generated.
  - 72 students per division (18 per batch).
  - 4 theory subjects × 3 h per division.
  - 3 double-period lab blocks per division, each with a different subject and teacher per
    batch.
  - 2 pinned slots per division.
  - 4 random unavailable slots per faculty member.
  - 2 combined-division lectures.
  - No fixed slots.

  Together these give 242 sessions (seed 1) and about 8.8 teaching hours per faculty member on
  average. Neither figure is a SPIT measurement.
- **`infeasible`:** division `d00` gets single-period theory until it must be taught
  **40 periods in its 39 free slots**. Every counted unit shares a batch of `d00`, so they all
  conflict pairwise. That makes it infeasible by pigeonhole, whatever the rooms or faculty.
  This is the ROADMAP Phase 5 edge case "a division with more sessions than slots".
  `solver/tests/test_synthetic.py` checks the certificate; it does not run the solver.

The generator does not guarantee that `small`, `medium` or `large` are feasible. It only checks
that no division is over-subscribed.

## Results — machine-independent

The same for seeds 1, 2 and 3: the instance sizes and every outcome below were identical
across the three seeds.

| Preset | Sessions | Lab blocks | Room entries | Faculty | Conflict pairs | Welsh-Powell | Backtracking | Search nodes | Independent validator |
|---|---|---|---|---|---|---|---|---|---|
| small | 12 | 2 | 6 | 6 | 32 | complete, valid | solved | 11 | valid (0 violations) |
| medium | 81 | 8 | 14 | 16 | 833 | complete, valid | solved | 58 | valid (0 violations) |
| large | 242 | 30 | 28 | 41 | 2814 | complete, valid | solved | 153 | valid (0 violations) |
| infeasible (seed 1 only) | 46 | 2 | 6 | 6 | 831 | 2 unplaced | **timeout (> 300 s)** | — | n/a |

How each column was checked:
- **Welsh-Powell "valid":** `validate_slot_placements` (colouring assigns no rooms).
- **Backtracking "valid":** `validate_solution`, which includes the room checks.
- **Search nodes:** `nodes_explored`, the solver's only counter. `solution_v1` reports it as
  `metadata.backtracks`, but it counts nodes, not backtracks.
- **Conflict pairs:** distinct session pairs with at least one edge.
- **Edges by reason:** no preset produced a `ROOM` edge. The generator's rule (both sessions
  fit exactly one room, and it is the same one) never fires on these room inventories.

## Results — machine-dependent timings

**Machine:** Windows 11 (10.0.26200), AMD64 Family 23 Model 104, Python 3.12.10. Wall clock,
measured with no other work running.

| Preset | Seed | Welsh-Powell | Backtracking |
|---|---|---|---|
| small | 1 / 2 / 3 | 1.2 / 1.2 / 1.2 ms | 16.4 / 13.7 / 14.9 ms |
| medium | 1 / 2 / 3 | 12.1 / 11.6 / 12.4 ms | 0.86 / 0.96 / 0.98 s |
| large | 1 / 2 / 3 | 34.4 / 32.2 / 36.3 ms | **42.5 / 43.4 / 36.7 s** |
| infeasible | 1 | 11.1 ms | timeout at 300 s |

A first seed-1 run made while other tests were running on the same machine measured 2–2.5×
slower (large: 105 s). It is discarded as contaminated, and the seed-1 row above is the idle
rerun.

## Findings

1. **Correctness holds at every scale measured.** Every solved result, up to 242 sessions,
   passes the independent validator, and every complete Welsh-Powell colouring passes the
   room-free validator.
2. **The search never backtracks on these instances.** The node count equals the number of
   placement units + 1 (large: 120 theory + 30 lab blocks + 2 combined = 152 units, 153
   nodes). Search difficulty is not what costs time here.
3. **Time is dominated by lab-block room enumeration.**
   - Profiling `medium` (seed 1, cProfile, 3.8 s under the profiler):
     - ~78% is in `_lab_block_candidates` → `_gen_room_tuples`;
     - ~17% is in `_forward_check`.
   - For each start slot, every combination of distinct rooms for the block's members is
     built eagerly, up to ~16·15·14·13 tuples per start on `large`, even though only the
     first is used.
   - The synthetic `large` instance still solves in ~40 s on this machine.
4. **Infeasibility by pigeonhole is not proven in 300 s.**
   - Chronological backtracking with forward checking can only refute 40 pairwise-conflicting
     units over 39 slots by exhaustive search. This was not measured past the limit.
   - So today the solver returns "infeasible" only for instances that fail fast, for example
     an empty domain. That matters for Phase 4 (`mus.py`), whose trials are infeasibility
     checks.
   - Welsh-Powell, being greedy, simply leaves 2 sessions unplaced; that proves nothing
     either way.
5. **Not measured:** fixed slots (no preset uses them), ODD-semester shapes, real timetable
   data (no parser yet), memory use, and seeds beyond 1–3.

## 2026-10-12 — after S4 (pre-solve, lazy lab rooms, symmetry breaking, time budget)

Same generator, presets and seeds as above; nothing in the instances changed.

- **Code:** `track/solver-presolve` @ `693b8fb` plus the uncommitted S4 changes
  (`solver/presolve.py` new; `solver/backtracking.py`, `solver/benchmarks/baseline.py`).
- **Reproduce:** `python -m solver.benchmarks.baseline --seed N --timeout 300` for N = 1, 2, 3.
  The runner now also passes the limit to the solver as `time_limit_s`.
- **What changed in the solver (ROADMAP D21):**
  - `_lab_block_candidates` / `_gen_room_tuples` are generators that yield in the old sorted
    order, so only the room tuples actually tried are built (finding 3).
  - `solver/presolve.py` runs before search: room suitability, per-faculty and per-cohort
    pigeonhole, per-period forced lab demand vs. parallel lab rooms, and Hall's condition by
    Hopcroft–Karp per faculty and per cohort. A failure returns infeasible with zero search
    nodes and the certificate in the v1 `diagnosis` fields.
  - Interchangeable rooms (same type, capacity, parent and pinned slots, no sub-rooms) are
    tried once per day while unused.
  - `backtrack_solve(time_limit_s=...)` reports `outcome == "timeout"`, never infeasible.

### Results — machine-independent

Seeds 1, 2 and 3 gave identical rows.

| Preset | Sessions | Backtracking | Search nodes | Independent validator |
|---|---|---|---|---|
| small | 12 | solved | 11 | valid (0 violations) |
| medium | 81 | solved | 58 | valid (0 violations) |
| large | 242 | solved | 153 | valid (0 violations) |
| infeasible | 46 | **infeasible, pre-solve `cohort_load` on `d00`** (40 periods, 39 free) | 0 | n/a |

**Same answers as before.** Before the change, the old code's output was recorded for the 400
property instances and for small, medium and large × seeds 1–3. After it, all 409 results
(solved flag, every start slot and every room) were identical. Two tests keep this checked:
`solver/tests/test_search_equivalence.py`.
- The lazy generators are compared against the old eager code (kept verbatim in the test) on
  the property instances and on small and medium.
- Symmetry on vs. off is compared on the property instances and on all three feasible presets.

The eager reference is too slow for CI on `large`, about 40 s per seed, so `large` was compared
against the recorded output only.

**Property generator (400 instances).** 172 solved, 228 infeasible. Of the infeasible ones,
152 are proved by pre-solve with zero search nodes:

| Check | Instances proved |
|---|---|
| `faculty_load` | 72 |
| `hall_faculty` | 45 |
| `lab_capacity` | 18 |
| `cohort_load` | 15 |
| `hall_cohort` | 2 |

The other 76 are refuted by search. Symmetry breaking cut the total search nodes over all 400
instances from 1260 to 1229. The effect is small because these instances have few
interchangeable rooms and short searches.

### Results — machine-dependent timings

**Machine:** Windows 11 (10.0.26300), Intel64 Family 6 Model 183, Python 3.12.10. This is not the
machine used for the 2026-10-06 tables, so for a like-for-like comparison the old code was also
timed here, in-process and without the validator, just before the change.

| Preset | Seed | Welsh-Powell | Backtracking (S4) | Backtracking, old code, same machine |
|---|---|---|---|---|
| small | 1 / 2 / 3 | 1.0 / 1.1 / 1.1 ms | 15.0 / 11.0 / 11.1 ms | ~10 ms |
| medium | 1 / 2 / 3 | 9.0 / 8.9 / 8.5 ms | 0.19 / 0.19 / 0.18 s | 0.60 / 0.72 / 0.61 s |
| large | 1 / 2 / 3 | 29.5 / 29.5 / 25.6 ms | **1.60 / 1.54 / 1.51 s** | 43.1 / 38.8 / 28.9 s |
| infeasible | 1 / 2 / 3 | 9.0 / 8.0 / 8.2 ms | **14.6 / 13.5 / 13.2 ms** | not rerun (timed out at 300 s on 2026-10-06) |

- On `large`, pre-solve itself takes about 60 ms.
- Symmetry breaking makes no measurable difference on the presets: large took 1.53–1.59 s with
  it off and 1.53–1.57 s with it on. These searches never backtrack, so it has nothing to prune.

### Findings

1. **The feasible speed-up is all from lazy lab-room candidates.** `large` went from ~40 s to
   ~1.6 s and `medium` became ~3.5× faster, with identical solutions.
2. **The pigeonhole edge case is now proved, not timed out.** The infeasible preset fails
   `cohort_load` for division `d00` in ~14 ms. The certificate names the 39 sessions that
   conflict pairwise. This is a proof, not a minimal unsatisfiable subset: `solver/mus.py`
   (Phase 4) is still needed for that.
3. **Search-exhausted infeasibility still carries the placeholder diagnosis.** Pre-solve checks
   are necessary conditions only. An odd cycle in two slots, for example, passes every check
   and is refuted only by search (`TestInfeasible.test_odd_cycle_in_two_slots_exhausts_the_search`).
4. **A timeout cannot be expressed in `solution_v1`.** Its `status` enum is
   `solved | infeasible`. `BacktrackResult.outcome` is `"timeout"`, and `to_solution_dict()`
   raises rather than mislabel it, so the timeout stays internal until a contract carries it.
   `solution_v2` has `timeout` only as a relaxation-verification status, not as a top-level
   status.
5. **Not measured:** the same gaps as above (fixed slots in presets, ODD semester, real data,
   memory). Also not measured: the time budget on a real long search, since no preset needs
   one any more.
