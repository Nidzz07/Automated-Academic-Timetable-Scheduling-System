# Evaluation: synthetic presets and the real EVEN 2025-26 instance (S15b)

2026-10-21 · Rohan (with Claude Code) · Track C

Reproduce (repo root, venv active, about 15 minutes):

```powershell
python -m bench.evaluate
```

It writes the five CSVs below and prints them as Markdown tables. Every number in this file
comes from those CSVs. Tests: `bench/tests/test_evaluate.py`.

| CSV (`bench/results/`) | Section |
|---|---|
| `2026-10-21-eval-algorithms.csv` | 1, 2 |
| `2026-10-21-eval-real-vs-printed.csv` | 3 |
| `2026-10-21-eval-rooms.csv` | 4 |
| `2026-10-21-eval-free-rooms.csv` | 4 |
| `2026-10-21-eval-repair.csv` | 5 |
| `2026-10-24-eval-size-sweep.csv` | 6 |
| `2026-10-24-eval-repair-vs-regen.csv`, `2026-10-24-eval-repair-vs-regen-summary.csv` | 7 |

Sections 6 and 7 were added on 2026-10-24 (S15c). Reproduce them with
`python -m bench.size_sweep` (about 7 minutes here) and `python -m bench.repair_vs_regen`
(about 75 minutes here, mostly 300 s timeouts). These also write the charts in `docs/figures/`. Tests:
`bench/tests/test_s15c.py`. The full runs are marked `slow`, so they are deselected by default.

- **Machine:** AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD, Python 3.12.10, Windows.
  Every `ms` figure is wall clock, machine-dependent, and the **median of 3 runs**. Every other
  figure is a pure function of the input. The script checks this: it stops if two runs
  disagree on anything except time.
- **Synthetic presets** (`small`, `medium`, `large`, `infeasible`, seeds 1–5) come from
  `solver.benchmarks.synthetic` (D19). They are not SPIT data. The only real data in them is
  the room list of `large`.
- **Real instance:** `data/instances/even-2025-26/edge_list.json`. The generated timetable is the
  committed `solution.json`. The printed timetable is `real_baseline.assignment.json`
  (`docs/real-baseline-even-2025-26.md`).
- **Algorithms:**
  - Welsh-Powell is `solver.colouring.welsh_powell`.
  - Backtracking is `solver.backtracking.backtrack_solve`, with a 300 s budget. No run reached
    it.
  - Backtracking + improve is backtracking followed by `solver.improve.improve`, with
    200,000 moves and seed 0.
- **Hard violations:**
  - Backtracking is checked with `solver.validate.validate_solution`, which covers time and
    rooms.
  - Welsh-Powell assigns no rooms, so it is checked with `validate_slot_placements`, which
    covers time only. It is checked on the sessions it coloured.
- **Score:** `solver.scoring.score`, rules version 1. Score = 100 − the sum of the four
  penalties. Weights: S-GAP 2, S-B2B 1, S-LOAD16 1, FAC_LOAD_IMBALANCE 0.5.

## 1. Algorithms

### Real instance (156 sessions, 1,568 edges)

| Algorithm | Outcome | Placed | Hard violations | Score | S-GAP | S-B2B | S-LOAD16 | FAC_LOAD_IMBALANCE | Nodes | Moves | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Welsh-Powell | 8 unplaced | 148 | 0 (time only, 148 coloured) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 10.9 |
| Backtracking | solved | 156 | 0 | −162.5 | 158.0 | 42.0 | 6.0 | 56.5 | 92 | n/a | 187.6 |
| Backtracking + improve | solved | 156 | 0 | −18.5 | 30.0 | 32.0 | 6.0 | 50.5 | 92 | 200,000 | 9,176.7 |

Welsh-Powell gives no score here because 8 sessions are uncoloured, and the score needs every
session. The committed `solution.json` used 1,000,000 moves and scores −15.0 (section 3).

### Synthetic presets, seed 1

| Preset | Algorithm | Outcome | Placed | Hard violations | Score | S-GAP | S-B2B | S-LOAD16 | FAC_LOAD_IMBALANCE | Nodes | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small (12) | Welsh-Powell | complete | 12 | 0 (time only) | 90.0 | 0.0 | 2.0 | 0.0 | 8.0 | n/a | 0.7 |
| small | Backtracking | solved | 12 | 0 | 65.5 | 24.0 | 3.0 | 0.0 | 7.5 | 11 | 8.7 |
| small | + improve | solved | 12 | 0 | 95.0 | 0.0 | 0.0 | 0.0 | 5.0 | 11 | 7,197.5 |
| medium (81) | Welsh-Powell | complete | 81 | 0 (time only) | −29.0 | 60.0 | 35.0 | 0.0 | 34.0 | n/a | 6.4 |
| medium | Backtracking | solved | 81 | 0 | −117.5 | 170.0 | 19.0 | 0.0 | 28.5 | 58 | 157.9 |
| medium | + improve | solved | 81 | 0 | 89.0 | 0.0 | 0.0 | 0.0 | 11.0 | 58 | 12,273.9 |
| large (242) | Welsh-Powell | complete | 242 | 0 (time only) | −262.5 | 190.0 | 80.0 | 0.0 | 92.5 | n/a | 18.3 |
| large | Backtracking | solved | 242 | 0 | −489.0 | 466.0 | 48.0 | 0.0 | 75.0 | 153 | 1,529.2 |
| large | + improve | solved | 242 | 0 | 69.0 | 0.0 | 0.0 | 0.0 | 31.0 | 153 | 14,396.5 |
| infeasible (46) | Welsh-Powell | 2 unplaced | 44 | 0 (time only, 44 coloured) | n/a | | | | | n/a | 5.9 |
| infeasible | Backtracking | infeasible (presolve: cohort_load) | 0 | n/a | n/a | | | | | 0 | 7.7 |
| infeasible | + improve | not run (nothing solved) | | | | | | | | | |

### Synthetic presets, score range over seeds 1–5

| Preset | Welsh-Powell | Backtracking | Backtracking + improve |
|---|---|---|---|
| small | 87.0 to 90.0 | 65.5 to 92.5 | 95.0 (all five) |
| medium | −58.0 to −1.5 | −146.5 to −68.0 | 88.5 to 89.5 |
| large | −262.5 to −158.0 | −760.5 to −299.0 | 59.5 to 69.0 |

Hard violations are 0 in all 45 rows of the three solvable presets. On every seed of
`infeasible`, Welsh-Powell leaves 2 sessions unplaced, and pre-solve refutes the instance
(`cohort_load`) before any search.

## 2. Runtime vs size

These are the bench presets, the same sizes as `docs/bench-2026-10-17.md`; bench has no other
size sweep. Each cell gives the minimum and maximum over seeds 1–5 of the per-seed median of 3
runs.

| Instance | Sessions | Edges | Backtracking nodes | Welsh-Powell ms | Backtracking ms | Backtracking + improve ms |
|---|---|---|---|---|---|---|
| small | 12 | 36 | 11 | 0.7 | 8.0–8.7 | 6,773.3–7,198.4 |
| medium | 81 | 883 | 58 | 6.2–6.4 | 154.0–160.6 | 12,273.9–12,690.5 |
| large | 242 | 2,936 | 153 | 17.5–23.8 | 1,509.4–1,785.2 | 14,378.4–15,823.4 |
| infeasible | 46 | 947 | 0 | 5.8–6.0 | 7.7–8.0 | n/a |
| real even-2025-26 | 156 | 1,568 | 92 | 10.9 | 187.6 | 9,176.7 |

The node count is the same on every seed of a preset. `improve()` always runs its full
200,000 moves, so most of the third column is local search.

## 3. Real generated vs printed timetable

| | Generated (`solution.json`) | Printed |
|---|---|---|
| Score | **−15.0** | **21.5** |
| S-GAP (weight 2) | 13 raw, 26.0 | 2 raw, 4.0 |
| S-B2B (weight 1) | 30 raw, 30.0 | 23 raw, 23.0 |
| S-LOAD16 (weight 1) | 6 raw, 6.0 | 5 raw, 5.0 |
| FAC_LOAD_IMBALANCE (weight 0.5) | 106 raw, 53.0 | 93 raw, 46.5 |
| Hard violations, time only (`validate_slot_placements`) | **0** | **36**: FACULTY_CLASH 26, PINNED_BLOCK 10 |
| Hard violations, time and rooms (`validate_solution`) | **0** | not checkable (below) |
| Sessions with no room in the edge list | 0 | 58 |

The printed timetable cannot get the room check. 58 of its sessions are in rooms outside the
edge list's room set: 002 (24), 508 (27), 203 (2), lab 505 (4) and 403-A (1). These rooms are
excluded by D10, D28 and D29; the breakdown is in `docs/real-baseline-even-2025-26.md`. The 26
FACULTY_CLASH rows are combined lectures, which D40 schedules one per division. The 10
PINNED_BLOCK rows are TE practicals in slots held by frozen items (D24).

## 4. Room use, generated vs printed

### Used periods per room

The week has 45 teaching periods per room: 5 days × 9 periods (P0, P1, P3–P9). Rooms are shared
by SE and TE, and P4 and P5 are each one year's lunch (D6), so a room can be used in both.

A room counts as used in a period if a session or a pin holds the room, or holds one of its
sub-rooms. *Pinned* counts the periods held by pins: frozen items (D24, D35, D37). These are the
same in both timetables and are included in both *used* columns.

| Room | Kind | Sub-rooms | Pinned | Generated used | Printed used | Generated % | Printed % |
|---|---|---|---|---|---|---|---|
| 507 | lab | 0 | 1 | 27 | 1 | 60.0 | 2.2 |
| 509 | lab | 2 | 17 | 35 | 27 | 77.8 | 60.0 |
| 603 | lab | 3 | 16 | 34 | 31 | 75.6 | 68.9 |
| 604 | lab | 0 | 3 | 23 | 15 | 51.1 | 33.3 |
| 606 | lab | 2 | 6 | 24 | 28 | 53.3 | 62.2 |
| 607B | lab | 0 | 10 | 30 | 24 | 66.7 | 53.3 |
| 608 | lab | 0 | 10 | 28 | 20 | 62.2 | 44.4 |
| 702 | lab | 3 | 8 | 25 | 24 | 55.6 | 53.3 |
| 703 | lab | 2 | 14 | 26 | 24 | 57.8 | 53.3 |
| 601 | classroom | 0 | 3 | 21 | 5 | 46.7 | 11.1 |
| 605 | classroom | 0 | 8 | 21 | 11 | 46.7 | 24.4 |
| 609 | classroom | 0 | 12 | 21 | 14 | 46.7 | 31.1 |
| 701 | classroom | 0 | 0 | 20 | 0 | 44.4 | 0.0 |
| **9 labs** | | | 85 | **252 of 405 (62.2%)** | **194 of 405 (47.9%)** | | |
| **4 classrooms** | | | 23 | **83 of 180 (46.1%)** | **30 of 180 (16.7%)** | | |

The printed columns count only the 98 printed sessions whose room is in the edge list. The 58
sessions in rooms 002, 508, 203, 505 and 403-A appear in no row.

### Free rooms per slot

Each cell gives free classrooms / free labs. The rule is the one the free-room view uses
(`freeRoomsAt` in `frontend/src/adapters/rooms.ts`):

- A room used whole is not free.
- A lab with sub-rooms counts as free while at least one sub-room is free.
- A room without sub-rooms is free only when nothing uses it.

There are 4 classrooms and 9 labs.

Generated:

| | P0 | P1 | P3 | P4 | P5 | P6 | P7 | P8 | P9 |
|---|---|---|---|---|---|---|---|---|---|
| Mon | 3/8 | 3/7 | 0/2 | 2/2 | 3/0 | 1/0 | 1/4 | 4/1 | 0/6 |
| Tue | 3/0 | 2/0 | 1/4 | 3/4 | 2/1 | 2/1 | 4/7 | 4/7 | 0/9 |
| Wed | 1/2 | 1/2 | 0/4 | 2/5 | 2/1 | 2/2 | 4/9 | 3/1 | 1/2 |
| Thu | 3/6 | 0/4 | 1/3 | 2/6 | 3/0 | 2/1 | 4/8 | 4/8 | 2/9 |
| Fri | 0/2 | 4/1 | 0/2 | 1/3 | 4/8 | 2/2 | 3/2 | 4/9 | 4/9 |

Printed (rooms in the edge list only):

| | P0 | P1 | P3 | P4 | P5 | P6 | P7 | P8 | P9 |
|---|---|---|---|---|---|---|---|---|---|
| Mon | 3/8 | 3/7 | 2/5 | 4/5 | 4/9 | 2/2 | 4/1 | 4/8 | 4/9 |
| Tue | 4/5 | 3/5 | 1/1 | 3/1 | 4/5 | 3/5 | 4/7 | 4/7 | 4/9 |
| Wed | 2/1 | 2/1 | 2/4 | 4/5 | 4/8 | 2/9 | 4/9 | 4/9 | 4/9 |
| Thu | 3/6 | 3/6 | 3/3 | 4/4 | 4/1 | 4/2 | 4/7 | 4/7 | 4/9 |
| Fri | 2/6 | 4/6 | 1/4 | 3/4 | 4/8 | 4/1 | 3/1 | 4/9 | 4/9 |

| Over the 45 slots | Generated | Printed |
|---|---|---|
| Free classrooms: min / median / max | 0 / 2 / 4 | 1 / 4 / 4 |
| Slots with no free classroom | 7 | 0 |
| Free labs: min / median / max | 0 / 3 / 9 | 1 / 6 / 9 |
| Slots with no free lab | 5 | 0 |

## 5. Repair

These are the scenarios of `solver.benchmarks.real_repair`, run on the committed
`solution.json`. Each uses `solver.repair.repair` with seed 0 and the default budgets.
Runtimes are single runs, not medians. Moved, room-only and score are the same on every run.
`docs/repair-even-2025-26.md` explains each scenario.

| Scenario | Result | Moved (slot) | Room-only | Score before → after | Change | Rings (freed, outcome) | Runtime ms |
|---|---|---|---|---|---|---|---|
| Swapnali Kurhade unavailable all Tuesday | infeasible (presolve) | n/a | n/a | −15.0 → n/a | n/a | 0: 7 infeasible; 1: 85 infeasible; all: 156 infeasible | 183 |
| Lab 603 unavailable all Monday | repaired | 5 | 2 | −15.0 → −41.0 | −26.0 | 0: 7 infeasible; 1: 81 solved | 589 |
| CE207 lecture dragged to a free slot (Wed 09.00, 601) | repaired | 1 | 0 | −15.0 → −36.5 | −21.5 | 0: 1 solved | 229 |
| CE207 lecture dragged onto SE-Comp A's frozen MDM-I lab (Mon 09.00, 605) | infeasible (presolve) | n/a | n/a | −15.0 → n/a | n/a | 0: 1; 1: 38; 2: 146; all: 156, all infeasible | 220 |
| Swapnali Kurhade unavailable Tuesday afternoon (P5–P9) | repaired | 6 | 1 | −15.0 → −17.5 | −2.5 | 0: 1 infeasible; 1: 39 timeout (node budget); 2: 130 solved | 1,501 |
| CE207 lecture dragged onto an occupied slot (Mon 17.15, 605) | repaired | 4 | 1 | −15.0 → −27.0 | −12.0 | 0: 4 infeasible; 1: 80 solved | 599 |

Moved, room-only, rings and scores are identical to `docs/repair-even-2025-26.md`. The runtimes
are lower than the ones recorded there, which came from a different machine.

## 6. Runtime and score vs size (S15c)

Source: `bench/results/2026-10-24-eval-size-sweep.csv`, written by `python -m bench.size_sweep`.

- **Instances.** These are synthetic (D19), not SPIT data. Each one is the `large` preset with
  only two parameters changed:
  - `divisions` is 2–9, which falls between the `small` (12 sessions) and `large` (242)
    presets; 10, which *is* `large`; and 12, which is above it.
  - `faculty` scales with divisions: 41 per 10 divisions, rounded, so 8, 12, 16, 21, 25, 29, 33,
    37, 41 and 49.

  Everything else is unchanged: 4 batches, 4 theory subjects × 3 hours, 3 lab blocks per
  division, 2 combined lectures, 2 pins per division, 4 unavailable slots per faculty member,
  and the 20 real rooms. All instances use seed 1.
- **Algorithms and runs.** The algorithms and checks are those of section 1. Every `ms` figure
  is the median of 3 runs on the machine above. The script stops if two runs disagree on
  anything except time.
- **Check.** The 10-division row matches section 1's `large` seed 1 on everything except time:
  153 nodes, backtracking −489.0, + improve 69.0.

| Divisions | Sessions | Edges | Backtracking nodes | Welsh-Powell ms | Backtracking ms | Backtracking + improve ms | Backtracking score | + improve score | + improve FAC_LOAD_IMBALANCE |
|---|---|---|---|---|---|---|---|---|---|
| 2 | 50 | 673 | 33 | 3.9 | 157.9 | 13,379.0 | −37.5 | 96.0 | 4.0 |
| 3 | 74 | 961 | 48 | 5.8 | 276.9 | 13,871.6 | −175.5 | 87.0 | 13.0 |
| 4 | 98 | 1,236 | 63 | 8.4 | 426.5 | 14,091.2 | −187.0 | 90.0 | 10.0 |
| 5 | 122 | 1,506 | 78 | 9.9 | 552.8 | 13,358.9 | −266.0 | 84.5 | 15.5 |
| 6 | 146 | 1,807 | 93 | 11.5 | 718.8 | 13,342.3 | −266.0 | 80.5 | 19.5 |
| 7 | 170 | 2,088 | 108 | 13.3 | 943.6 | 13,944.8 | −574.5 | 78.0 | 22.0 |
| 8 | 194 | 2,373 | 123 | 15.2 | 1,307.1 | 14,871.2 | −388.0 | 75.0 | 25.0 |
| 9 | 218 | 2,665 | 138 | 18.6 | 1,634.2 | 14,900.9 | −385.5 | 66.0 | 34.0 |
| 10 (`large`) | 242 | 2,936 | 153 | 19.1 | 1,677.8 | 14,579.3 | −489.0 | 69.0 | 31.0 |
| 12 | 290 | 3,507 | 183 | 23.9 | 2,921.2 | 16,956.8 | −561.5 | 59.0 | 41.0 |

The other outcomes were the same in every row:

- All 30 rows (10 sizes × 3 algorithms) have 0 hard violations.
- Welsh-Powell coloured every session.
- Backtracking solved every instance.
- After `improve()`, S-GAP, S-B2B and S-LOAD16 were 0 at every size, so the + improve score is
  100 − FAC_LOAD_IMBALANCE.

![Runtime vs sessions](figures/runtime-vs-sessions.svg)

![Score vs sessions](figures/score-vs-sessions.svg)

## 7. Repair vs regeneration on the real instance (S15c)

Source: `bench/results/2026-10-24-eval-repair-vs-regen.csv` (per change) and
`2026-10-24-eval-repair-vs-regen-summary.csv`, written by `python -m bench.repair_vs_regen`.

- **Changes.** 30 seeded random changes (seed 0) to the committed `solution.json`. They
  alternate between two kinds, and the draw is with replacement:
  - Odd numbers: a faculty member who teaches is unavailable at 1–3 of the periods they teach
    in `solution.json`.
  - Even numbers: a top-level room is unavailable for a half-day in which `solution.json`
    uses it or one of its sub-rooms. Morning is P0, P1, P3 and P4 (09:00–13:15); afternoon is
    P5–P9 (13:15–18:15), from ROADMAP §5.

  So every change displaces at least one session. Two room changes were drawn twice: 14 and 28,
  and 18 and 30. Each pair gave the same results except for runtime.
- **Two ways.** Each change is handled two ways, both starting from `solution.json`:
  - **Repair** is `solver.repair.repair`, with seed 0 and the default budgets, plus two settings
    for this benchmark. `time_limit_s=300` matches regeneration's budget: without it, the last
    ring (every session free) has no limit. One change ran for over 2 minutes with no answer
    while this was being set up. `mus_nodes=0` keeps the pre-solve or search diagnosis of an
    unsolvable change and skips the minimal-conflicting-set search; that search ran for over
    20 minutes on change 9 without finishing.
  - **Regeneration** is `solver.backtracking.backtrack_solve` on the changed edge list, with a
    300 s budget, followed by `solver.improve.improve` with 200,000 moves and seed 0. (The
    committed `solution.json` used 1,000,000 moves.)
- **Measures.**
  - *Moved* counts sessions whose start slot differs from `solution.json`.
  - *Room-only* counts sessions with the same slot but a different room.
  - *Score* is scored against the changed edge list.
  - Every solved result passed `validate_solution` against the changed edge list; the script
    stops otherwise.
  - Runtimes come from one run each, on the machine above.
  - No solved repair reached its 300 s cap (the longest took 55.4 s), so its moves and score do
    not depend on the machine.
- **Unsolved changes are kept.** A `timeout` means no answer within 300 s. It is not a proof of
  infeasibility (D33).

| # | Change | Repair | Moved | Room-only | Score | ms | Regeneration | Moved | Room-only | Score | ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fac-kailas-devadkar unavailable Mon P4, Wed P0 | solved | 11 | 0 | −27.5 | 451.2 | solved | 70 | 40 | −19.5 | 8,831.8 |
| 2 | room-608 unavailable Fri morning | solved | 0 | 3 | −15.0 | 125.2 | timeout | n/a | n/a | n/a | 300,034.7 |
| 3 | fac-reeta-koshy unavailable Tue P5, Tue P6 | solved | 2 | 0 | −34.5 | 421.9 | solved | 86 | 26 | −27.0 | 9,133.7 |
| 4 | room-606 unavailable Mon afternoon | solved | 5 | 2 | −41.0 | 501.2 | solved | 86 | 30 | −14.5 | 9,255.4 |
| 5 | fac-sudhir-dhage unavailable Wed P3 | solved | 5 | 3 | −15.0 | 914.1 | timeout | n/a | n/a | n/a | 300,034.9 |
| 6 | room-604 unavailable Thu morning | solved | 0 | 2 | −15.0 | 112.2 | solved | 89 | 29 | −18.5 | 9,450.5 |
| 7 | fac-anant-nimkar unavailable Thu P4 | solved | 1 | 0 | −36.5 | 230.3 | solved | 63 | 44 | −9.5 | 8,983.9 |
| 8 | room-604 unavailable Mon morning | solved | 0 | 3 | −15.0 | 115.4 | solved | 93 | 30 | −4.0 | 9,226.1 |
| 9 | fac-sudeep-mali unavailable Mon P6, Mon P7, Thu P5 | infeasible (presolve) | n/a | n/a | n/a | 7,952.3 | infeasible (presolve: faculty_load) | n/a | n/a | n/a | 27.8 |
| 10 | room-509 unavailable Wed morning | solved | 0 | 1 | −15.0 | 131.0 | solved | 89 | 28 | −18.5 | 9,279.7 |
| 11 | fac-yogita-patil unavailable Fri P1 | solved | 16 | 7 | −50.0 | 5,423.1 | solved | 89 | 41 | −27.5 | 9,288.5 |
| 12 | room-605 unavailable Thu afternoon | solved | 0 | 2 | −15.0 | 111.9 | solved | 74 | 29 | −10.5 | 9,289.4 |
| 13 | fac-reeta-koshy unavailable Mon P8, Mon P9, Tue P5 | solved | 8 | 0 | −34.0 | 702.5 | solved | 85 | 35 | −28.5 | 9,047.8 |
| 14 | room-605 unavailable Tue afternoon | solved | 3 | 2 | −17.0 | 1,360.0 | solved | 74 | 33 | −11.0 | 9,134.0 |
| 15 | fac-sunil-ghane unavailable Wed P5, Thu P6, Thu P9 | timeout | n/a | n/a | n/a | 300,054.8 | timeout | n/a | n/a | n/a | 300,069.3 |
| 16 | room-607b unavailable Thu afternoon | solved | 0 | 4 | −15.0 | 121.3 | solved | 89 | 33 | −18.5 | 9,344.7 |
| 17 | fac-sanjyuktarani-jena unavailable Mon P5, Thu P5 | timeout | n/a | n/a | n/a | 300,287.1 | solved | 102 | 45 | −12.0 | 9,322.6 |
| 18 | room-609 unavailable Wed morning | solved | 0 | 1 | −15.0 | 107.0 | solved | 89 | 29 | −18.5 | 9,399.9 |
| 19 | fac-abhijeet-salunke unavailable Fri P3 | timeout | n/a | n/a | n/a | 300,031.3 | timeout | n/a | n/a | n/a | 300,035.9 |
| 20 | room-606 unavailable Fri morning | solved | 0 | 1 | −15.0 | 120.8 | timeout | n/a | n/a | n/a | 300,030.7 |
| 21 | fac-vaishnavee-rathod unavailable Mon P5, Thu P9, Fri P0 | timeout | n/a | n/a | n/a | 300,032.2 | timeout | n/a | n/a | n/a | 300,032.4 |
| 22 | room-608 unavailable Thu morning | solved | 3 | 0 | −23.0 | 326.8 | solved | 89 | 29 | −18.5 | 9,363.7 |
| 23 | fac-jostna-bhagat unavailable Mon P8 | solved | 5 | 0 | −15.5 | 330.7 | solved | 109 | 25 | −51.5 | 16,090.7 |
| 24 | room-702 unavailable Fri afternoon | solved | 0 | 2 | −15.0 | 115.0 | solved | 89 | 29 | −18.5 | 9,505.5 |
| 25 | fac-amey-ganesh-nile unavailable Tue P6 | solved | 29 | 11 | −23.0 | 55,414.7 | solved | 102 | 27 | −32.0 | 16,618.3 |
| 26 | room-603 unavailable Fri morning | solved | 0 | 4 | −15.0 | 196.0 | timeout | n/a | n/a | n/a | 300,050.9 |
| 27 | fac-anant-nimkar unavailable Mon P4, Wed P9, Fri P6 | timeout | n/a | n/a | n/a | 300,035.9 | timeout | n/a | n/a | n/a | 300,029.1 |
| 28 | room-605 unavailable Tue afternoon | solved | 3 | 2 | −17.0 | 1,310.1 | solved | 74 | 33 | −11.0 | 9,019.0 |
| 29 | fac-sanjyuktarani-jena unavailable Mon P6, Tue P5 | timeout | n/a | n/a | n/a | 305,751.5 | solved | 96 | 37 | −27.5 | 8,371.7 |
| 30 | room-609 unavailable Wed morning | solved | 0 | 1 | −15.0 | 106.8 | solved | 89 | 29 | −18.5 | 8,628.1 |

| | Repair | Regeneration |
|---|---|---|
| Solved (of 30) | 23 | 21 |
| Infeasible, proved by pre-solve | 1 (change 9) | 1 (change 9) |
| Timeout at 300 s | 6 (15, 17, 19, 21, 27, 29) | 8 (2, 5, 15, 19, 20, 21, 26, 27) |
| Unsolved both ways | 5 (9, 15, 19, 21, 27) | |
| Moved, mean [95% CI], over the 19 changes solved both ways | 4.53 [0.98, 8.07] | 85.68 [80.45, 90.92] |
| Score, mean [95% CI], same 19 | −23.11 [−28.37, −17.84] | −19.79 [−24.84, −14.74] |
| Runtime ms, mean [95% CI], all 30 changes | 62,763.14 [17,360.58, 108,165.71] | 86,897.69 [38,074.30, 135,721.08] |

The intervals are 95% Student-t intervals of the mean (Statistical Methods). The script
computes the critical value itself: Simpson's rule on the t density, then bisection. These
values match the printed t tables for 1, 4 and 29 degrees of freedom (tested).

The next figures were computed from the per-change CSV over the same 19 changes; the summary
CSV does not contain them:

- **Moved.** Regeneration moved 81.16 more sessions than repair on average (95% CI 75.68 to
  86.64). The smallest gap was 59.
- **Score.** Repair scored higher on 8 changes and lower on 11. Repair minus regeneration is
  −3.32 on average (95% CI −10.10 to 3.47).
- **Runtime.** Repair's median was 326.8 ms (range 106.8 to 55,414.7). Regeneration's median was
  9,279.7 ms (range 8,628.1 to 16,618.3).
- **Runtime over all 30 changes.** These means are dominated by the 300 s timeouts. Computed
  the same way over the 19 changes, repair's interval would be −2,535.07 to 9,629.08 ms. It
  reaches below 0 because one 55.4 s change skews it, so the medians above describe that set
  better.

![Sessions moved per change](figures/repair-vs-regen-moved.svg)

Unsolved changes have no point in the chart: repair at 15, 17, 19, 21, 27, 29 and 9;
regeneration at 2, 5, 9, 15, 19, 20, 21, 26, 27.

## Findings

1. **Hard constraints.**
   - Every timetable from backtracking, with or without `improve()`, passed `validate_solution`
     with 0 violations: 15 synthetic instances and the real one.
   - Every complete Welsh-Powell colouring passed the time-only check.
2. **Completeness.**
   - Welsh-Powell coloured every session of the three solvable presets.
   - On the real instance it left 8 of 156 sessions uncoloured; backtracking solved it in 92
     nodes.
   - On `infeasible`, Welsh-Powell left 2 sessions unplaced, and pre-solve refuted the instance
     with 0 search nodes.
3. **Score, synthetic.**
   - Welsh-Powell scored higher than backtracking on 12 of 15 solvable instances: all medium
     and large seeds, and small seeds 1 and 4.
   - Backtracking + improve scored higher than both on all 15.
   - After `improve()`, S-GAP was 0 on all 15. FAC_LOAD_IMBALANCE was 5.0–38.5 and S-B2B
     0–2.0.
4. **Score, real.**
   - `improve()` raised the backtracking timetable from −162.5 to −18.5 with 200,000 moves.
     The committed 1,000,000-move timetable scores −15.0.
   - The printed timetable scores 21.5, and is ahead on every rule: S-GAP by 22.0 points, S-B2B
     by 7.0, FAC_LOAD_IMBALANCE by 6.5 and S-LOAD16 by 1.0.
   - The printed timetable breaks 36 hard constraints, time only. The generated one breaks 0,
     time and rooms.
5. **Runtime.**
   - Backtracking took 8.0–8.7 ms at 12 sessions, 154.0–160.6 ms at 81 and 1,509.4–1,785.2 ms
     at 242. On the real instance (156 sessions) it took 187.6 ms.
   - Backtracking + improve took 6.8–15.8 s across the presets, and 9.2 s on the real
     instance.
6. **Rooms.**
   - The generated timetable puts all 156 sessions in edge-list rooms. The printed one puts 98
     there.
   - So the generated timetable uses the 4 classrooms in 83 of 180 periods (printed: 30), and
     the 9 labs in 252 of 405 (printed: 194).
   - It leaves no classroom free in 7 slots and no lab free in 5. The printed timetable always
     leaves at least one of each, counted over these rooms only.
7. **Repair.**
   - 4 of the 6 scenarios were repaired, moving 1 to 6 sessions' slots, plus 0 to 2 room-only
     changes. Each took under 1.6 s here.
   - The other 2 were proved infeasible by pre-solve.
   - The score fell in every repaired scenario, by 2.5 to 26.0 points.
8. **Size (S15c, synthetic, seed 1).**
   - From 50 to 290 sessions, backtracking's median time rose from 157.9 ms to 2,921.2 ms,
     and its nodes from 33 to 183, 15 more per added division.
   - Backtracking + improve took 13.3–17.0 s at every size; most of that is the fixed
     200,000-move local search.
   - Its score fell from 96.0 to 59.0. All of its penalty at every size was
     FAC_LOAD_IMBALANCE.
   - Every timetable had 0 hard violations.
9. **Repair vs regeneration (S15c, real instance, 30 changes).**
   - Over the 19 changes both solved, repair moved 4.53 sessions on average (95% CI 0.98 to
     8.07) and regeneration 85.68 (80.45 to 90.92).
   - Mean scores were −23.11 (repair) and −19.79 (regeneration). The intervals overlap, and
     repair scored higher on 8 of the 19.
   - Repair solved 23 changes and regeneration 21. 5 were unsolved both ways: 1 proved
     infeasible by pre-solve, 4 timeouts.
   - Repair timed out on 2 changes that regeneration solved, and regeneration on 4 that repair
     solved.

## Limits

- **Runtimes are medians of 3 runs on one machine**, with no confidence intervals (sections
  1, 2, 6). Section 7's runtimes are single runs; their interval is over changes, not repeated
  runs.
- **Size sweep (section 6).** It uses one seed and one instance shape, the `large` preset
  with divisions and faculty scaled. Other shapes and seeds were not swept.
- **Repair vs regeneration (section 7).**
  - It covers 30 changes of two kinds on one instance, drawn with replacement, so two are
    repeats. Drags and substitutions are not included.
  - Repair ran with `mus_nodes=0` and a 300 s cap, not its defaults, so unsolvable changes
    carry no minimal conflicting set here.
  - Repair's runtime is affected by these settings; regeneration's comes from a 200,000-move
    `improve()`.
  - Timeouts are unknowns: 4 changes were neither solved nor refuted by either method within
    300 s.
- **The comparison is not like for like:**
  - The printed timetable is checked on time only, and its room use counts only the 98
    sessions in edge-list rooms.
  - The printed timetable uses rooms outside the edge list (002, 508, 203, 505, 403-A). The
    generated one may not use them (D10, D28, D29).
- **Plots** are hand-written SVG (`bench/charts.py`); no plotting library is installed.
