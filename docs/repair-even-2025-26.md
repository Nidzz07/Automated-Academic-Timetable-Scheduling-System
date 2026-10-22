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
6. **No repair at all**: if even the run with every session free fails, that run's diagnosis
   (`presolve` or `search_exhaustion`) is explained by `solver/mus.py` (S14b, below). If that
   run runs out of time, `repair` raises `TimeoutError` and never reports the change as
   infeasible (D21, D33). A drag onto a frozen item is explained before any search (S14b).

The objective is lexicographic: first the number of sessions whose slot changed, then the number
only moved to another room, then the score. The result is a heuristic minimum, not a proven one.

**What "moved" means.** `displaced` in `solution.v2` lists the sessions whose slot changed, which
is what the contract defines. A session that kept its slot but changed room is not in it;
`stats["room_changed"]` lists those, and the table below shows them separately. Whether room-only
changes belong in `displaced` is a contract question for all three members (see Open questions).

## Results

| Scenario | Result | Moved (slot) | Re-roomed only | Rings: freed sessions, outcome | Score before → after | Runtime |
|---|---|---|---|---|---|---|
| 1. Swapnali Kurhade unavailable all Tuesday | **cannot be repaired** (presolve; S14b: explained, see below) | n/a | n/a | 0: 7 infeasible; 1: 85 infeasible; all: 156 infeasible | −15.0 → n/a | 0.54 s (S14b: 56.16 s) |
| 2. Lab 603 unavailable all Monday | repaired | 5 | 2 | 0: 7 infeasible; 1: 81 solved | −15.0 → −41.0 | 1.91 s |
| 3. One CE207 lecture dragged to a free slot | repaired | 1 | 0 | 0: 1 solved | −15.0 → −36.5 | 0.70 s |
| 4. The same lecture dragged onto SE-Comp A's frozen MDM-I lab | **cannot be repaired** (S14b: pre-check, `mus`) | n/a | n/a | S14a: 0: 1; 1: 38; 2: 146; all: 156, all infeasible. S14b: none (answered before any search) | −15.0 → n/a | 0.71 s (S14b: 2.40 s) |
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
run with everything free are refuted by pre-solve, so no search ran (0 search nodes). Since S14b
this certificate is explained further; see "S14b, scenario 1" below.

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
pre-solve and is listed under Open questions; it was not changed here. **S14b fixes the aim:**
the pre-check names the pin; see "S14b, scenario 4" below.

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

## S14b: explaining an infeasible change

2026-10-21 · Dhruv (with Claude Code) · branch `track/solver-diagnosis`. `solver/mus.py` explains a
change that cannot be repaired, and `repair()` answers a drag onto a frozen item before any search.
The numbers below come from `python -m solver.benchmarks.real_repair` (same seed and machine as
above). The solver's output names ids only; the names in this section come from `display.json`.

### How it works

- **Constraint groups.** Each member of the set is one thing in the edge list that can be switched
  off as data. One `pinned_occupancy` entry is `pin.<i>`, PINNED_BLOCK. The edge list gives pins no
  id, so the index is the id, and `display.json` `pins[i]` names it (D41). Other members: one
  teacher's unavailable slots on one day (FACULTY_UNAVAILABLE), one `fixed_slot`, one lab block
  (LAB_CONTIGUITY), the FACULTY or COHORT edges between one pair of teachers or cohorts, one room's
  capacity, one non-lab room's type, and the change itself (`change`). Sessions, the grid and "one
  session per room per period" always hold. The real instance has 493 groups.
- **Checks.** Each check runs pre-solve first, then backtracking within 300 search nodes
  (`MUS_NODES`). A check that runs out of nodes is *unknown*, never feasible or infeasible (D33).
  Before searching from scratch, a check tries to reuse a known timetable (the one being repaired,
  or a witness found earlier). It first tries one as-is, then repairs it locally with only the
  sessions in the way free. Every timetable used as proof passes `validate_solution`.
- **Deletion** (deletion filter, Chinneck and Dravnieks 1991; chunks as in QuickXplain, Junker
  2004). The start set is the groups touching the sessions the proof names; for a load or Hall
  certificate, only pins outside the slots it counts as free. Chunks are dropped while pre-solve
  still proves the rest infeasible, then every member is tried alone with a full check. A member
  whose removal is shown feasible stays necessary, so with no unknown check the set is a minimal
  unsatisfiable subset (`method = "mus"`). With an unknown check the set is only proven
  infeasible: it goes out as `presolve` (proven, not minimal, D43) if pre-solve proved it, and
  otherwise the original diagnosis comes back unchanged.
- **Relaxations.** For each member, the timetable that broke only that member (its witness) says
  which pin entity to free and which unavailable slots the teacher needs. Candidate actions from
  `relaxation_actions_v2.json` are tried smallest first (slots freed, then the contract's action
  order) on the whole instance, and the first whose re-solve passes `validate_solution` is the
  `suggested_relaxation` (`verification: restored`). The change itself is never relaxed. If none
  restores, the relaxation is MANUAL (`not_attempted`).

### Scenario 4: drag onto SE-Comp A's frozen MDM-I lab

`obs-t0-r1-c3-l0` (CE207, SE-Comp A, Anant Nimkar) is dragged to Monday P0 in 605. The pre-check finds
`pinned_occupancy[238]` holding `coh-se-a` at Monday P0. That entry is `display.json`
`pins[238]` = "MDM - I LABs, Mon P0–P1", source `pin-t0-r1-c1-l0`, the frozen item S14a's
diagnosis missed. No ring search runs.

| Member | Kind | What it is |
|---|---|---|
| `pin.238` | PINNED_BLOCK | SE-Comp A's MDM-I lab at Mon P0; the witness puts `coh-se-a` there |
| `change` | FIXED_SLOT | the drag: `obs-t0-r1-c3-l0` to Mon P0 in `room-605` |

`method = "mus"`, proven minimal: 5 checks in all, including the verification. Relaxation:
RELAX_PINNED_BLOCK, slot Mon P0, cohort `coh-se-a`, **verification `restored`** (re-solve 0.47 s).
A separate test re-runs `repair` with that pin entity removed and gets a solved timetable. Total
runtime 2.40 s.

### Scenario 1: Swapnali Kurhade unavailable all Tuesday

The pre-solve certificate (`faculty_load`, 16 periods in 13) is explained, starting from 124 of
the 493 groups.

| Members | Kind | What they are (`display.json`) |
|---|---|---|
| `change` | FACULTY_UNAVAILABLE | the absence: Tue P0–P9 |
| `unavailable.fac-swapnali-kurhade.0` | FACULTY_UNAVAILABLE | "PHD Day OFF", all Monday (D36) |
| `faculty_clash.fac-swapnali-kurhade` | FACULTY_CLASH | she cannot teach two sessions at once |
| `pin.5`, `pin.7`, `pin.9` | PINNED_BLOCK | SE lunch, Wed/Thu/Fri P5 |
| `pin.21`, `pin.29`, `pin.31` | PINNED_BLOCK | frozen FOM - II (Asma Tambe, D44), Fri P1, Wed P6, Thu P6 |
| `pin.293`, `pin.307`, `pin.322`, `pin.308`, `pin.323` | PINNED_BLOCK | HSS, Wed P7 (SE-Comp B, C, D) and Thu P7 (C, D) |
| `pin.295`, `pin.298`, `pin.312`, `pin.313`, `pin.327` | PINNED_BLOCK | LLC, Thu P8–P9 (SE-Comp B, C, D) |
| `pin.296`, `pin.310`, `pin.311`, `pin.325`, `pin.326` | PINNED_BLOCK | STUDENT ACTIVITY, Fri P7–P9 (SE-Comp B, C, D) |

That is 24 members. 23 were shown necessary. One, `pin.293` (HSS, Wed P7, SE-Comp B; it holds her
SE-Comp B batch C lab cohort), was **unknown**: without it neither the local repair nor 300 search
nodes found a timetable, and pre-solve did not refute it. So the set is proven infeasible but **not
proven minimal**, and it goes out as `method = "presolve"`. It is far more specific than S14a's
single certificate: the pins say *which* frozen and recurring blocks use up her Wednesday to Friday.

Relaxations: 22 candidates were tried. Each of the 20 single-pin candidates (free one SE-Comp B,
C or D cohort at one cell) is `still_infeasible`, which is a proof, since one cell cannot cover a
3-period gap. The witness's Monday slot alone (Mon P0) is also `still_infeasible`. Freeing all of
Monday is `timeout`: unknown, not fixed. Separately, `repair` with her whole Monday freed did not
finish in 120 s. So the suggestion is **MANUAL**, verification `not_attempted`. The absence itself
is never offered as a relaxation. Total runtime 56.16 s, against 0.54 s without the explanation.
It is the same work every run (node budgets, no clock), but the wall clock varies a lot on this
machine: 40 s to 90 s in single runs, and 249 s inside a pytest run.

### An infeasible case pre-solve cannot explain: none found in reasonable time

I looked for a real change that is infeasible but that pre-solve does not refute, so that only the
search can prove it:

- each of the 9 top-level lab rooms closed for a whole day (45 cases): all solve within 3,000 nodes;
- each lab room closed all week: 4 of 9 (507, 604, 702, 703) are unknown at 3,000 nodes;
- two lab rooms closed on the same day (180 cases): 20 are unknown at 3,000 nodes;
- none of these is refuted by pre-solve. One of them, 507 and 702 both closed on Monday, was still
  unknown after 150,000 nodes (387 s), and I stopped there.

So no real search-proven infeasible case was found, and MUS's search-proven path is shown only on a
synthetic instance (`solver/tests/test_mus.py::triangle`). Three sessions there are joined by a
FACULTY, a COHORT and a ROOM edge with two periods to use: pre-solve sees no group to count, the
search refutes it, and the MUS is all three edges.

## S14e: protected pins, substitutes, a pinned room

2026-10-23 · Dhruv (with Claude Code) · branch `track/solver-substitution`. The numbers below come
from the tests in `solver/tests/test_repair.py` and `solver/tests/test_mus.py` (same seed and
budgets as above); runtimes are single runs on this machine. Names come from `display.json`.

### Protected pins are never suggested

`explain()` and `repair()` take `protected`: indices into `pinned_occupancy` that may never be
relaxed or suggested. The backend will pass the lunch, coffee and other break pins from
`display.json` (D41); the solver still cannot tell lunch from any other pin. A protected pin stays
in the conflicting set when it is part of the conflict, but no action on it is tried, so the next
candidate is. If only protected pins could fix it, the suggestion is MANUAL (`not_attempted`),
naming the first member that is not protected, and its description lists the protected members.
An index that is not a pin is a `ValueError`.

- **Real: the CE207 lecture dragged onto SE lunch** (Wed P5 in 605, `pins[5]` = "SE lunch, Wed
  P5"). Without protection: `mus` {`pin.5`, `change`}, RELAX_PINNED_BLOCK `coh-se-a` at Wed P5,
  `restored` (0.65 s). That frees SE-Comp A's lunch. With the 10 lunch pins of `display.json`
  protected: the same set, MANUAL on `change`, nothing tried (0.50 s).
- **Synthetic: the next candidate** (`lunch_or_lab` in `test_mus.py`). Two practicals, one lab,
  two periods, lunch in the second. Unprotected, the lunch is tried first and restores. Protected,
  the set is still {`pin.0`, `room_type.class`} and RECLASSIFY_ROOM is verified instead. Without
  the classroom only the lunch could help, so it is MANUAL.

### A drag onto a pinned room

So far only a drag onto a pinned cohort was tested. The CE207 lecture is now dragged to Thu P3 in
609. SE-Comp A and Anant Nimkar are free then, but 609 is held by `pinned_occupancy[226]`, a frozen
out-of-scope session (D35; `display.json` kind `out_of_scope`, source `oos-t19-r4-c4-l0`). The
pre-check names it through the room: `mus` {`pin.226`, `change`}, proven minimal,
RELAX_PINNED_BLOCK room `room-609` at Thu P3, `restored`, 0.77 s. Re-running `repair` with that
room freed gives a solved timetable.

### Substitutes (D53)

- **`substitute_faculty` change** (`apply_change`, `repair`): `{"kind": "substitute_faculty",
  "session_id", "faculty_id"}`. The session's `faculty_id` becomes the new teacher, and its FACULTY
  edges are redrawn to exactly the new teacher's other sessions. FACULTY edges join the sessions of
  one teacher; that holds for all 548 FACULTY edges of the real instance and for the synthetic
  generators. The session keeps its slot and room. If the new teacher clashes there (their own
  session, an unavailable slot, a pin), that session is hit and the repair runs as usual: rings,
  restore, improve, and an explanation if nothing fits. In an explanation the substitution is
  background, not a group: a coordinator chose it, so it is never relaxed. The set says why the new
  teacher cannot take the session. An unknown session or faculty member, or the session's own
  teacher, is a `ValueError`.
- **Output stays `solution.v2`.** `solution.v2` has no teacher field, for any result. The new
  teacher lives in the changed edge list (`sessions[].faculty_id`, an `edge_list_v1` field), just
  as an absence lives in `unavailable_slots`, and the result is valid against
  `apply_change(edge_list, change)`. No contract change. The backend keeps the change with the job
  and accumulates accepted substitutions (D52).
- **`substitute_candidates(payload, solution, session_id, qualified)`**: the caller passes who is
  qualified; the solver never decides that. For everyone in `qualified` except the session's own
  teacher, the substitution is written in, and `validate_solution` must accept the unchanged
  timetable. Returns `{"faculty_id", "score_change"}`, best `score_change` first, ties by faculty
  id. A qualified id with no `faculty_availability` entry in the payload is a `ValueError`: the
  solver cannot check someone whose availability it does not know.

Real instance, as a **mechanism check, not SPIT data**. The qualified list here is the instance's
own CE207 teachers. The real lists come from Track B in S14f (Faculty___Subjects.xlsx,
Subject-wise_faculty.xlsx).

| Substitute for `obs-t0-r1-c3-l0` (CE207, SE-Comp A, Anant Nimkar, Thu P4, 605) | Fits at Thu P4? | Score change | Repair |
|---|---|---|---|
| Prasenjit Bhavathankar | yes | 0.0 | nothing moves, score −15.0 |
| Nataasha Raul | yes | −2.0 (S-B2B +1, S-LOAD16 +1) | not run |
| Sudhir Dhage | no (FACULTY_CLASH: he teaches at Thu P4) | n/a | only the lecture moves, to Wed P1 in 601 (ring 0); −15.0 → −27.0 (S-GAP 13 → 18, S-B2B 30 → 31, FAC_LOAD_IMBALANCE 106 → 108); 0.34 s |

`substitute_candidates` takes 0.09 s for these four, and 0.9 s with all 37 faculty ids of the edge
list as the list (30 fit). On 30 seeded property instances, with everyone as "qualified", the
result is exactly the set the validator accepts (24 fit, 8 do not). On 40 instances, one random
session each, `repair` with every other teacher as the substitute gives 28 that fit (nothing
moves), 7 repaired and 5 infeasible. The infeasible ones are explained without the substitution in
the set.

### Test time

`pytest solver/tests` on this machine: **before 102.0 s** (363 passed, 1 slow deselected), of which
the Kurhade explanation fixture took 22.5 s. **After 79.3 s** (375 passed, 2 slow deselected). The
full Kurhade explanation is now `slow` (`pytest -m slow`). The default run explains the same
change with `repair(..., mus_nodes=0)`: pre-solve checks only, the same 24-member set, proven
infeasible but not minimal (`presolve`), MANUAL, 7.2 s. The search-equivalence tests (15.2, 8.9 and
4.8 s) are the other large items; they are not explanations and were not changed. Part of the drop
is machine load: the unchanged symmetry-breaking test took 18.6 s in the first run and 15.2 s in the
second.

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
- **Pre-solve diagnosis wording** (scenario 4): it blamed the faculty Hall check instead of the
  cohort pin. S14b's pre-check now names the pin. Descriptions still name ids rather than people,
  because the S14b task says "ids only; names are the UI's job"; the contract's `description`
  asks for institutional terms. That conflict needs all three members.
- **No `method` for "proven by search, not minimal"** (S14b). A set with an unknown member goes
  out as `presolve` only if pre-solve proved it; otherwise the original diagnosis is returned and
  the set is lost. Showing it would need a contract change.
- **Pins have no id in `edge_list_v1`** (S14b). Members name a pin by its index, `pin.<i>`. That
  is stable only for one exported edge list, the one `display.json` was written with.
- **Lunch can be suggested** (S14b). The solver cannot tell lunch from any other pin, so a
  RELAX_PINNED_BLOCK on a lunch slot may be suggested. The backend must refuse it (Row 8
  assessment). The same holds for absence-derived slots outside the change itself. S14e: the
  backend can pass the break pins as `protected`, and they are then never suggested. Absence-derived
  slots have no such option yet.
- **Qualified people missing from the edge list** (S14e). `substitute_candidates` refuses an id
  with no `faculty_availability` entry. The real edge list has 37 such entries (24 teach, 13 only
  hold pins), so Track B must pass only those ids, or the export must list everyone who may
  substitute.
- **The backend tests still run the full Kurhade explanation** (S14e).
  `backend/tests/test_repair.py::test_each_change_type[infeasible]` runs it through the API and
  again directly. Track B can pass `mus_nodes=0` there, or mark the test slow.
- **Explanation is slow and not covered by the time limit** (S14b). The Kurhade explanation takes
  about a minute here. Each of its searches has a node budget, but none uses `repair`'s
  `time_limit_s`, so the answer is the same on every machine. The cost is that `repair` can run
  past `time_limit_s` when it explains. A first version did share the clock: under the backend
  test's 60 s it cut the last verification short, and two runs differed in
  `metadata.backtracks`.
- **Only repair explains.** A fresh solve (`backtrack_solve`, the backend's solve job) still
  returns the bare `presolve` / `search_exhaustion` diagnosis; `solver.mus.explain` can be called
  on it.
- **Where the dragged room lives.** `edge_list_v1` has `fixed_slot` but no fixed room. `repair`
  keeps the dragged room internally, so `apply_change(payload, change)` alone does not record it.
