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

## Limits

- **Runtimes are medians of 3 runs on one machine**, with no confidence intervals. The Phase 5
  item "displaced sessions, repair vs regeneration (mean + CI)" is not covered here.
- **The comparison is not like for like:**
  - The printed timetable is checked on time only, and its room use counts only the 98
    sessions in edge-list rooms.
  - The printed timetable uses rooms outside the edge list (002, 508, 203, 505, 403-A). The
    generated one may not use them (D10, D28, D29).
- **No plot.** Runtime vs size is a table only.
