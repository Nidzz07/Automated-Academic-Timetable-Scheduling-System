# Repair of the real EVEN 2025-26 timetable (S14a)

2026-10-21 · Dhruv (with Claude Code) · branch `track/solver-repair`

`solver/repair.py` repairs a solved timetable after one change and tries to move as few sessions
as possible. These are its results on the committed real timetable
(`data/instances/even-2025-26/solution.json`, score −15.0, 156 sessions). Reproduce with:

```powershell
python -m solver.benchmarks.real_repair
```

Every scenario uses seed 0 and the default budgets (`RING_NODES = 5000` search nodes per ring,
`MAX_MOVES = 20000` local-search moves). Two runs give identical results apart from runtime.
Runtime is wall clock on an AMD64 Family 23 machine with Python 3.12.10, and it varies with load:
an earlier run on the same machine took 0.33 / 1.10 / 0.41 / 0.43 / 3.16 / 1.25 s.

## How it works

1. **The change goes into the edge list** (`apply_change`), using fields that `edge_list_v1`
   already has:
   - an absence becomes `faculty_availability[].unavailable_slots`;
   - a closed room becomes a room-only `pinned_occupancy` entry per slot (a closed parent room
     also closes its sub-rooms);
   - a drag sets the session's `fixed_slot`. The edge list has no field for the dragged room,
     so the repair keeps it as that session's only allowed room.
2. **Hit sessions**: any session whose placement the change now forbids, plus, for a drag, the
   sessions in the dragged session's way. A lab block is always hit as a whole.
3. **Freeze and expand** (backtracking, CE207; BFS, DSGT): every other session is frozen at its
   slot and room, and the backtracker re-places only the hit sessions. If that fails, the free
   set grows by one BFS ring: conflict-graph neighbours (same cohort, same teacher) and sessions
   in the same room on the same day. This repeats until every session is free. The backtracker
   tries each session's old placement first (new `prefer` option), so the first solution it finds
   stays close to the old timetable. Each ring has a node budget rather than a clock, so the
   result is the same on every machine.
4. **Restore**: each moved session (a lab block as one unit) goes back to its old place if it now
   fits, or else to its old start in another room. This repeats until nothing changes.
5. **Improve**: `improve()` runs on a copy of the edge list in which every session still at its
   old start is fixed there. Only sessions that already moved can move again, so the moved count
   can never grow.
6. **No repair at all**: if even the run with every session free fails, the result is that
   run's own diagnosis (`presolve` or `search_exhaustion`). If that run runs out of time,
   `repair` raises `TimeoutError` and never reports the change as infeasible (D21, D33).

The objective is lexicographic: first the number of sessions whose slot changed, then the number
only moved to another room, then the score. The result is a heuristic minimum, not a proven one.

**What "moved" means.** `displaced` in `solution.v2` lists the sessions whose slot changed, which
is what the contract defines. A session that kept its slot but changed room is not in it;
`stats["room_changed"]` lists those, and the table below shows them separately. Whether room-only
changes belong in `displaced` is a contract question for all three members (see Open questions).

## Results

| Scenario | Result | Moved (slot) | Re-roomed only | Rings: freed sessions, outcome | Score before → after | Runtime |
|---|---|---|---|---|---|---|
| 1. Swapnali Kurhade unavailable all Tuesday | **cannot be repaired** (presolve) | n/a | n/a | 0: 7 infeasible; 1: 85 infeasible; all: 156 infeasible | −15.0 → n/a | 0.54 s |
| 2. Lab 603 unavailable all Monday | repaired | 5 | 2 | 0: 7 infeasible; 1: 81 solved | −15.0 → −41.0 | 1.91 s |
| 3. One CE207 lecture dragged to a free slot | repaired | 1 | 0 | 0: 1 solved | −15.0 → −36.5 | 0.70 s |
| 4. The same lecture dragged onto SE-Comp A's frozen MDM-I lab | **cannot be repaired** (presolve) | n/a | n/a | 0: 1; 1: 38; 2: 146; all: 156, all infeasible | −15.0 → n/a | 0.71 s |
| 5. (extra) Swapnali Kurhade unavailable Tuesday P5–P9 | repaired | 6 | 1 | 0: 1 infeasible; 1: 39 node budget out; 2: 130 solved | −15.0 → −17.5 | 3.75 s |
| 6. (extra) The same lecture dragged onto an occupied slot | repaired | 4 | 1 | 0: 4 infeasible; 1: 80 solved | −15.0 → −27.0 | 1.48 s |

"Score before" is `solution.json` scored against the original edge list. "After" is scored against
the changed edge list, using the same four rules (D34). Scenarios 5 and 6 are my own additions:
scenario 1, which the task asked for, turned out to be unrepairable, so scenario 5 shows a faculty
absence that does repair, and scenario 6 shows a drag that pushes other sessions aside.

### 1. Swapnali Kurhade unavailable all Tuesday: cannot be repaired

Swapnali Kurhade is already unavailable all Monday ("PHD Day OFF", D36). With Tuesday off as well,
the pre-solve proves it impossible: she teaches 11 sessions, 16 periods in all, but only 13
periods are left in which she is free (Wed P0, P1, P3, P4, P8, P9; Thu P1, P3, P4; Fri P0, P3, P4,
P6). Diagnosis: `method = "presolve"`, kind `FACULTY_CLASH`, constraint
`presolve.faculty_load.fac-swapnali-kurhade`, relaxation `MANUAL`. All three ring searches and the
run with everything free are refuted by pre-solve, so no search ran (0 search nodes).

### 2. Lab 603 unavailable all Monday

Hit: the SE-Comp A Monday P3–P4 lab block, whose batch B used 603-1, and the TE-Comp D Monday
P5–P6 lab block, whose batch B used 603. That is 7 sessions in two blocks. Re-placing only those
failed, and ring 1 (81 free sessions) solved in 172 search nodes in total.

| Session | Subject | Cohort | Teacher | Before | After |
|---|---|---|---|---|---|
| obs-t14-r7-c1-l0 | CE307 lab | TE Comp - D batch B | Sanjyuktarani Jena | Mon P5 603 | Fri P0 703 |
| obs-t14-r7-c1-l1 | CE308 lab | TE Comp - D batch C | Sudeep Mali | Mon P5 702-A | Fri P0 702-A |
| obs-t14-r7-c1-l2 | CE308 lab | TE Comp - D batch D | Amey Ganesh Nile | Mon P5 702-B | Fri P0 702-B |
| obs-t14-r7-c1-l3 | CE306 lab | TE Comp - D batch A | Aishwarya Nalawade | Mon P5 702-C | Fri P0 702-C |
| obs-t10-r7-c5-l0 | CE306 lab | TE Comp- B batch A | Aishwarya Nalawade | Fri P1 702 | Mon P5 702 |
| obs-t0-r4-c1-l1 | CE207 lab | SE-Comp A batch B | Nataasha Raul | Mon P3 603-1 | Mon P3 606-1 (room only) |
| obs-t0-r4-c1-l2 | CE208 lab | SE-Comp A batch C | Jignesh Sisodia | Mon P3 606 | Mon P3 606-2 (room only) |

The SE-Comp A block keeps its slot: its two batches only change rooms. The TE-Comp D block moves to
Friday P0–P1, and Aishwarya Nalawade's TE-Comp B batch A lab moves into the Monday slot her
TE-Comp D batch left free. The score falls from −15.0 to −41.0 (S-GAP 13 → 28, S-B2B 30 → 28,
FAC_LOAD_IMBALANCE 106 → 102, S-LOAD16 unchanged at 6). This is the cost of moving few sessions,
because the score only counts second.

### 3. One CE207 lecture dragged to a free slot

The first CE207 lecture by id, `obs-t0-r1-c3-l0` (Design and Analysis of Algorithms, SE-Comp A,
Anant Nimkar, Thu P4 in 605), is dragged to Wednesday P0 in 601. That is the first start, in slot
order, where SE-Comp A, Anant Nimkar and a classroom are all free. Only the lecture moves; no other
session changes slot or room, and ring 0 solves. The score falls from −15.0 to −36.5. S-GAP
rises from 13 to 23: SE-Comp A and each of its four batches gain an idle Wednesday P1 and an idle
Thursday P4, which is 2 periods × 5 cohorts. The dragged session is fixed where the user put it,
so `improve()` has nothing it may move.

### 4. The same lecture dragged onto a frozen slot: cannot be repaired

The same lecture is dragged to Monday P0 in 605. SE-Comp A holds "MDM - I LABs, Mon P0–P1" there,
a frozen D24 item (pin `pin-t0-r1-c1-l0`), so no timetable can honour the drag. Diagnosis:
`method = "presolve"`, kind `FACULTY_CLASH`, constraint `presolve.hall_faculty.fac-anant-nimkar`
("sessions obs-t0-r1-c3-l0 need 1 periods … can only use 0 slots"), relaxation `MANUAL`.

The diagnosis is correct (no timetable exists) but poorly aimed. It blames Anant Nimkar because
the faculty Hall check is the first pre-solve check to fire, not SE-Comp A's pin. It also names
ids rather than people, which the contract's `description` forbids. This comes from the existing
pre-solve and is listed under Open questions; it was not changed here.

### 5. (extra) Swapnali Kurhade unavailable Tuesday afternoon (P5–P9)

Hit: her SE-Comp D CE206 lecture on Tuesday P9. Ring 0 failed. Ring 1 (39 free sessions) used up
its 5,000-node budget, which counts as a timeout, not a proof. Ring 2 (130 free) solved.

| Session | Subject | Cohort | Teacher | Before | After |
|---|---|---|---|---|---|
| obs-t6-r1-c2-l0 | CE206 | SE-Comp D | Swapnali Kurhade | Tue P9 609 | Fri P6 609 |
| obs-t6-r1-c5-l0 | CE208 | SE-Comp D | Abhijeet Salunke | Fri P6 609 | Tue P9 605 |
| obs-t4-r2-c4-l0 | CE206 | SE-Comp C | Swapnali Kurhade | Fri P6 701 | Wed P9 601 |
| obs-t4-r5-c3-l0 | CE207 | SE-Comp C | Prasenjit Bhavathankar | Wed P9 601 | Tue P1 601 |
| obs-t6-r2-c2-l0 | CE207 | SE-Comp D | Prasenjit Bhavathankar | Wed P3 601 | Thu P1 601 |
| obs-t6-r5-c3-l0 | CE207 | SE-Comp D | Prasenjit Bhavathankar | Thu P1 601 | Wed P3 601 |
| obs-t2-r4-c5-l0 | CE208 | SE-Comp B | Jignesh Sisodia | Tue P9 605 | Tue P9 609 (room only) |

Score: −15.0 → −17.5 (S-B2B 30 → 32, FAC_LOAD_IMBALANCE 106 → 107). Before `improve()` (run with
`max_moves=0`), 7 sessions had moved and the score was −27.5. The local search put one of them,
`obs-t4-r7-c5-l0`, back in its old slot and raised the score by 10. The last two CE207 rows (the
two SE-Comp D lectures trading Wed P3 and Thu P1) were already a swap in the ring-2 solution, and
neither the restore pass nor the local search undid it.

### 6. (extra) The same lecture dragged onto an occupied slot

Dragged to Monday P9 in 605. Three sessions are in the way: SE-Comp A's CE208 lecture (same
cohort), Anant Nimkar's SE-Comp B CE207 lecture (same teacher), and SE-Comp D's CE207 lecture
(same room). Ring 1 (80 free) solved: four sessions changed slot (the dragged lecture; SE-Comp A
CE208 to Wed P1; Anant Nimkar's SE-Comp B lecture swapped with Jignesh Sisodia's SE-Comp B CE208
on Thu P3), and SE-Comp D's lecture only changed room (605 → 601). Score −15.0 → −27.0.

## Limits

- **Not a proven minimum.** The rings, the old-place-first ordering and the greedy restore keep
  moves low, but no search proves that fewer moves are impossible. An exact minimum would need
  branch and bound over the number of moves; that was not built.
- **The score is secondary.** Every repaired scenario scores lower than before. A repair that
  moved more sessions might score better; this one never trades a move for score.
- **Swaps can survive.** The restore pass moves one unit at a time, so two moved sessions that
  could only go home together, by trading places, stay swapped (scenario 5). `improve()` never
  adds a moved session, but it does not target moves either; it only optimises the score.
- **The node budget decides when a ring gives up.** A ring that runs out of nodes (scenario 5,
  ring 1) is expanded, not reported infeasible. A larger budget might succeed with fewer moves.

## Open questions

- **Room-only changes and `displaced`.** The contract describes `displaced` as sessions whose slot
  changed, so a pure room change (students go to another room at the same time) is not listed.
  `repair` reports such changes in `stats["room_changed"]`. Either the contract's description is
  widened, or the API carries room changes some other way. That needs all three members.
- **Pre-solve diagnosis wording** (scenario 4): it blames the faculty Hall check instead of the
  cohort pin, and names ids rather than people. This is existing pre-solve behaviour (Track A
  follow-up). No `mus.py` exists yet, so pre-solve and `search_exhaustion` are the only diagnoses.
- **Where the dragged room lives.** `edge_list_v1` has `fixed_slot` but no fixed room. `repair`
  keeps the dragged room internally, so `apply_change(payload, change)` alone does not record it.
