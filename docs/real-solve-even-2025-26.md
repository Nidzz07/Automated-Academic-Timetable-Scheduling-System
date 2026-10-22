# Solving the real EVEN 2025-26 SE+TE instance (S12a, S12d, S12g)

Track A · reproduce with `python -m solver.benchmarks.real_solve`
(`solver/tests/test_real_solve.py` re-runs it on every `pytest` run, capped at 60 s, and
compares with the committed file).

**Outcome (S12g, 2026-10-21): solved, then improved from −162.5 to +2.0.** Backtracking
(S12d) finds a valid timetable in 0.24 s; the new local search (`solver/improve.py`) then
walks through valid timetables only for 300,000 proposals (17.3 s) and keeps the best. The
result passes `solver.validate.validate_solution` with no violation and is committed as
`data/instances/even-2025-26/solution.json` (`solution.v2`, `metadata.algorithm` =
`backtracking(forward-checking, mrv) + local-search(simulated-annealing, seed=0,
moves=300000)`; identical on every run except `metadata.runtime_ms`).

**It does not beat the printed timetable's 21.5: it is 19.5 points short.** S-GAP is the rule
that blocks it (7 idle periods, 14 points, against 2 and 4 printed). D40 costs about 8 points
and D24 (with D35 and the 80-seat classroom count) holds the remaining gaps in place; see
[Why it stops short of 21.5](#s12g-why-it-stops-short-of-215).

S12d (2026-10-19) and S12a (2026-10-18, a timeout) are kept below the S12g sections.

## S12g: side by side with the printed timetable

| | Printed (S12b) | S12d (backtracking) | **S12g (+ local search)** |
|---|---|---|---|
| Hard violations | **36** (time-only check: 26 FACULTY_CLASH, 10 PINNED_BLOCK) | 0 | **0** |
| S-GAP (weight 2): raw / penalty | 2 / 4 | 79 / 158 | **7 / 14** |
| S-B2B (weight 1) | 23 / 23 | 42 / 42 | **27 / 27** |
| S-LOAD16 (weight 1) | 5 / 5 | 6 / 6 | **6 / 6** |
| FAC_LOAD_IMBALANCE (weight 0.5) | 93 / 46.5 | 113 / 56.5 | **102 / 51** |
| **Score** | **21.5** | **−162.5** | **2.0** |

Rules version 1, weights untouched. The printed timetable is not like for like: it breaks 36
hard constraints of this edge list (`docs/real-baseline-even-2025-26.md`); both generated
timetables break none.

## S12g, part 1: where the −162.5 came from

−162.5 = 100 − 262.5 of penalty (S12d timetable, names from `display.json`, D41):

| Rule | Raw | Penalty | Share | Worst |
|---|---|---|---|---|
| S-GAP | 79 | 158 | 60% | By division (division + its 4 batches): TE Comp - C 20, TE Comp- B 16, TE Comp - D 15, TE-Comp A 8, each SE division 5 (one idle hour of the whole division, counted once per cohort) |
| FAC_LOAD_IMBALANCE | 113 | 56.5 | 22% | Vaishnavee Rathod 8 (8, 5, 1, 0, 2 h Mon–Fri); 5 each: Prasenjit Bhavathankar, Sanjyuktarani Jena, Sudhir Dhage, Surekha Dholay, Swapnali Kurhade, Yogita Patil, Rupali Sawant |
| S-B2B | 42 | 42 | 16% | 4 each: Abhijeet Salunke, Anand Godbole, Sudhir Dhage, Swapnali Kurhade; 3 each: Anant Nimkar, Kailas Devadkar, Prasenjit Bhavathankar, Sunil Ghane, Vaishnavee Rathod |
| S-LOAD16 | 6 | 6 | 2% | 18 h: Amey Ganesh Nile, Azman Qureshi, Isha Sawalkar, Jyoti Ramteke, Sudeep Mali; 17 h: Jignesh Sisodia |

Fixed parts, which no timetable of this edge list can change:

- **S-LOAD16** counts who teaches what: 6 points in every timetable.
- **FAC_LOAD_IMBALANCE**: 14 teachers appear only in frozen pins (D24, D35, D44: e.g. Rupali
  Sawant, Pramod Bide, Vandana Wekhande); their spread is 29 h, 14.5 points, in every
  timetable. Taking every teacher alone, with their pins, unavailability (D36) and 2-hour
  practicals, the spread summed over teachers cannot go below **70 h (35 points)**.

**D40 (combined lectures split per division).** The printed timetable has 26 combined
lectures (its 26 FACULTY_CLASH rows); under D40 each is two lectures, 26 extra teaching hours
for 9 teachers (3 each for Kailas Devadkar, Anant Nimkar, Jignesh Sisodia, Sunil Ghane, Anand
Godbole, Swapnali Kurhade, Abhijeet Salunke, Prasenjit Bhavathankar; 2 for Reeta Koshy).
Directly, that is **1 point of S-LOAD16**: Jignesh Sisodia goes from 14 h printed to 17 h
(Kailas Devadkar, Sunil Ghane, Swapnali Kurhade and Abhijeet Salunke reach exactly 16 h, not
flagged). The extra hours also make back-to-back and uneven days harder to avoid. To measure
that, a scratch copy of the edge list (not committed) drops the 26 FACULTY edges between the
halves of each combined lecture, so the halves may share a slot and count once for their
teacher; the same pipeline on it gives −153.0 after backtracking (−162.5 with D40; a
different search path, so indicative only) and, after the S12g local search over seeds 0–19,
a mean of **+1.85** (best +15.5) against **−6.0** (best +2.0) with D40: **D40 costs about 8
points**, mostly S-B2B (14–29 back-to-back pairs without it, 21–33 with it) plus the one
S-LOAD16 flag.

## S12g, part 2: the local search

`solver/improve.py`, hand-written: local search and simulated annealing from Artificial
Intelligence and Soft Computing (CE303); the Kempe-chain interchange from graph colouring
(DSGT, CE201); incremental scoring over hash maps (Data Structures). Public entry point, for
Track B to call after `backtrack_solve`:

```python
improve(payload, solution, *, max_moves=300_000, seed=0, time_limit_s=None, stats=None) -> dict
```

It returns `solution.v2` (status solved) and raises `ValueError` on an unsolved or invalid
input. Neither argument is modified.

- **Only valid timetables.** Every proposal re-places sessions through the backtracker's own
  checks (initial domains: grid, unavailability, pinned faculty, cohort and room slots, lunch,
  room type and capacity, fixed slots; `_clashes_with_assigned` and `_room_is_available` over
  every occupied period, sub-rooms included), and is undone at once if any session fails.
  Pins are not sessions and never move; a session with a `fixed_slot` (or a lab block with
  one) is never proposed. A lab block moves whole, so it never splits and, since each year's
  lunch is a pin on its cohorts, never covers lunch. The returned timetable is checked again
  with `validate_solution`.
- **Moves:** one session to another free (start, room); a swap of two sessions that share a
  cohort or teacher; a whole lab block to a new start; a Kempe-chain interchange of two
  starts; and, 60% of the time, a move aimed at a current student gap: a unit holding that
  cohort's students goes onto the idle period (or anywhere), either ejecting the one or two
  sessions in its way into the slots it leaves (80%) or along a Kempe chain.
- **Objective:** `scoring.py`'s score, computed incrementally: a move recomputes only the
  (cohort, day) gap counts of the cohorts sharing students with the moved sessions, the
  (teacher, day) back-to-back counts and the teachers' daily spreads it touches. Raw counts
  are integers; at the start and the end they are checked against `scoring.score`.
- **Search:** simulated annealing, geometric cooling from 15 to 0.05 penalty points over 100
  stages of the budget (the last stages are hill climbing); best timetable kept; it replaces
  the input only when strictly better, so the score never drops.
- **Reproducible:** stops after `max_moves` proposals; `random.Random(seed)` over sorted
  lists; `exp` and the temperatures use + − × ÷ only, which IEEE 754 rounds the same on every
  machine. `time_limit_s` is a safety cap only (the real solve passes 120 s); a run it cuts
  short is not reproducible and `stats["timed_out"]` says so. Checked: the committed file is
  reproduced in fresh processes under `PYTHONHASHSEED` 1 and 12345 and in process-pool
  workers; not yet checked on a second machine.

### What the committed run did

Machine: Intel64 Family 6 Model 183 Stepping 1 (GenuineIntel), Windows, Python 3.12.10; one
run, machine otherwise idle. Wall-clock times are machine-dependent; the timetable is not.

| | |
|---|---|
| Backtracking | 241.5 ms, 92 nodes (unchanged from S12d) |
| Local search | 17,301.6 ms, 300,000 proposals, seed 0 |
| `metadata.runtime_ms` | 17,543.1 (both steps, validation included) |
| Best found at | proposal 222,993 (60 improvements) |
| Penalty | 262.5 → 98.0 (score −162.5 → 2.0) |

| Move | Proposed | Valid | Accepted |
|---|---|---|---|
| aimed at a gap (eject or Kempe) | 180,008 | 19,246 | 13,928 |
| Kempe interchange | 36,109 | 10,003 | 6,595 |
| one session | 39,459 | 3,386 | 872 |
| swap | 24,029 | 6,279 | 5,484 |
| whole lab block | 20,395 | 421 | 105 |

Most proposals are invalid: the week is that full (S12d: SE cohorts keep 4–5 free periods
once pins and lunch are placed).

Per rule, S12d → S12g: S-GAP 79 → 7 (TE Comp - C 4, TE-Comp A 2, SE-Comp D 1); S-B2B 42 → 27
(Abhijeet Salunke 3; 2 each: Anand Godbole, Jignesh Sisodia, Kailas Devadkar, Reeta Koshy,
Sudhir Dhage); S-LOAD16 6 → 6; FAC_LOAD_IMBALANCE 113 → 102 (Vaishnavee Rathod 6, Swapnali
Kurhade 6, then Sudhir Dhage, Yogita Patil, Rupali Sawant 5).

### How the settings were chosen

All on the real instance, same machine; "mean" is over seeds. Each row kept or dropped what
it tested; only the last row is committed.

| Search | Proposals | Seeds | Mean | Best | Worst |
|---|---|---|---|---|---|
| Move, swap, lab block only; linear cooling from 3 | 200k | 0–2 | −32.2 | −31.5 | −33.0 |
| + Kempe interchange, linear from 8 | 200k | 0–2 | −27.3 | −15.5 | −40.0 |
| same, 5× the budget | 1M | 1 | | −17.5 | |
| Geometric cooling from 15 | 200k | 0–5 | −22.9 | 0.0 | −49.0 |
| + 4 / 10 restarts from the best (dropped) | 200k | 0–5 | −25.0 / −23.8 | −8.0 / −12.5 | |
| + moves aimed at gaps (60%) | 200k | 0–5 | −11.8 | −1.5 | −32.5 |
| + ejection, 60% / 80% / 100% of gap moves | 300k | 10–19 | −7.2 / −4.9 / −9.8 | −0.5 / −1.0 / −6.5 | −16.0 / −10.0 / −17.5 |
| + tabu, tenure 50 / 500 proposals (dropped) | 300k | 10–19 | −11.3 / −9.6 | 3.0 / 1.0 | −29.0 / −23.0 |
| **Committed settings** | **300k** | **0–19** | **−6.0** | **2.0 (seed 0)** | **−20.0** |

Tabu (a session may not return to a start it left within the tenure, unless that beats the
best) did measurably worse, so it is not in the code. Seed 0 is the default and also the best
of seeds 0–19 at this budget; the spread across seeds (−20 to +2) is the honest measure of
what the search gives. 300k proposals keep the real solve under 20 s here, inside the 60 s
CI cap.

## S12g: why it stops short of 21.5

A score above 21.5 needs a penalty below 78.5. With S-LOAD16 fixed at 6 and the imbalance at
least 70 h (35 points), that leaves **2·S-GAP + S-B2B + 0.5·(imbalance − 70) < 37.5**. The
printed timetable's own soft profile gives 2·2 + 23 + 0.5·23 = 38.5: matched on every rule,
D40's sixth S-LOAD16 flag alone would leave it at 20.5. S12g reaches 14 + 27 + 16 = 57.

Points behind the printed timetable, by rule: **S-GAP +10** (14 vs 4), S-B2B +4, FAC_LOAD_IMBALANCE
+4.5, S-LOAD16 +1 (D40). Optimising one rule alone (weights changed in a scratch run only,
200k proposals, seeds 0–2, before the gap-aimed moves existed) reaches S-B2B 14–19 and
imbalance 87–98, both better than printed; S-GAP alone stays at 11–16. **S-GAP is the
blocker.**

Not a property of each division alone: with only the division's own constraints (its cohorts,
pins, lunch, each session's domain; teachers' other classes and rooms dropped), an exact
search finds 0 gaps for every division. The 7 gaps left come from what couples divisions:

| Gaps | Where | What holds them |
|---|---|---|
| 4 | TE Comp - C batches A and C, Tue P5–P6 | The batch-B+D lab block sits there. It is one of the three blocks the printed timetable runs on top of a frozen elective or MDM lab (the 10 PINNED_BLOCK rows), which **D24** forbids. Its partner block (batches A, C) cannot join it: its batch-A teacher, Sudeep Mali, has a frozen out-of-scope session then (`PSOOP / G2 /003`, Tue P6–P7, **D35**). |
| 2 | TE-Comp A batch A, Wed P5–P6 | The B+C+D lab block sits there. Every other TE-Comp A block shares a batch with it (the A+D block, displaced by **D24**, shares D), so nothing can fill batch A's hour; the block would have to sit at an edge of batch A's day, and the search found no legal start that does (the A+D block at that slot would also clash with Anand Godbole and Sunil Ghane's classes). |
| 1 | SE-Comp D batch B, Thu P1 | Moving the lab block to P3–P4 (next to batch B's frozen PCS lab, D44) is legal, but then the division needs a lecture at P1, and all three classrooms open then (601, 605, 701; D10, D42: 80 seats) hold other SE divisions' lectures. |

So: **D40 costs about 8 points; it is not what blocks 21.5** (without it the best of 20 seeds
is 15.5). The gaps that block it are held by D24 (and D35) freezing items the printed timetable
breaks, and by the four 80-seat classrooms. The parked proposals D46 (electives block only the
batches that take them) and D47 (combined lectures kept combined) are where the remaining
points are; deciding them is a team decision, not made here.

## S12d: why the old search got stuck

Re-run of the S12a search (commit 75a3f31) for 300 s on the same machine: timeout, 563,081
nodes, deepest partial 101 of 156 — all 31 lab blocks (96 practicals) and 5 lectures, as in S12a.

In that deepest partial one lecture has no start left: **SE-Comp B, CE206 Operating Systems,
Kailas Devadkar**. The lectures still to place, by cohort and teacher (*need* = periods,
*free* = distinct slots their remaining starts can still use):

| Division | Need | Free | | Faculty | Need | Free |
|---|---|---|---|---|---|---|
| SE-Comp D | 9 | 7 | | Jignesh Sisodia | 3 | 3 |
| SE-Comp A | 9 | 8 | | Kailas Devadkar | 4 | 4 |
| SE-Comp B | 4 | 3 | | Swapnali Kurhade | 6 | 6 |
| SE-Comp C | 9 | 11 | | Sunil Ghane | 6 | 7 |

The 5 lectures are not the cause. With only the 31 lab blocks of that partial placed, SE-Comp D
already has 7 slots for its 9 lectures, SE-Comp A and B 8 for 9: the lab placement itself
cannot be completed. Forward checking looks at one session's domain at a time, so it does not
see that nine lectures share seven slots; the search only finds out after the labs, and has to
undo lab blocks placed at the bottom of its stack. 300 s is nowhere near enough for that.

Why the labs landed there: the old order placed **every lab block first** (counted in
(start, room) values, a lab block always looked smaller than a lecture with four classrooms)
and tried starts **in ascending slot order**. Each block took the earliest slots its members
shared, with no regard for which slots the division's lectures and their teachers could still
use. The labs did not take more time: each SE division's batches have 8 lab periods both in
that partial and in the S12d timetable. They took the wrong periods. After the S12d timetable's
labs alone, the SE divisions keep 12–13 usable slots for 9 lectures (TE: 9–11 for 6), and
Swapnali Kurhade 8 for 6.

## S12d: what changed, and what each step measured

Hand-written in `solver/backtracking.py`; the heuristics are from Artificial Intelligence and
Soft Computing (CE303), the backtracking from Design and Analysis of Algorithms (CE207).

**(a) One dynamic ordering and least-constraining values — kept.**
`_select_variable`: lab blocks and lectures compete in one ordering. Minimum remaining values,
counted in **start slots** so a block (the starts all its members share) and a lecture
(whatever its room) compare fairly; ties to the most unassigned conflict neighbours (degree),
then the smaller id. A block whose members conflict with each other has no start at all, so it
is picked, and refuted, first. `_start_order`: starts are tried least constraining first — the
start that removes the fewest (neighbour, start) values from unassigned neighbours — then in
slot order; rooms by id within a start (so room symmetry breaking still holds).

| Real instance, 120 s budget (300 s for the old order) | Outcome | Time | Nodes | Deepest |
|---|---|---|---|---|
| Old: labs first, ascending starts | timeout | 300 s | 563,081 | 101 |
| Dynamic MRV + degree, ascending starts | timeout | 120 s | 45,624 | 52 |
| Labs first, least-constraining starts | solved | 0.3 s | 92 | 156 |
| **Dynamic MRV + degree, least-constraining starts (committed)** | **solved** | **0.26 s** | **92** | 156 |

Least-constraining values do the work; dynamic ordering alone is worse than the old order, and
with LCV it is neutral on this instance (same 92 nodes, a different timetable). It is kept
because it is what (a) asked for and replaces two selection functions with one; the synthetic
sets below show the cost.

Synthetic presets (3 seeds each) and the property instances, total search nodes:

| Set | Old | Committed | Dynamic, no LCV | Labs first + LCV |
|---|---|---|---|---|
| 400 property instances | 1,229 | 1,552 | 1,555 | 1,251 |
| 400 property sub-class | 1,774 | 1,774 | 1,774 | 1,774 |
| small / medium / large | 33 / 174 / 459 | 33 / 174 / 459 | same | same |
| infeasible (pre-solve) | 0 | 0 | 0 | 0 |

Every instance keeps its verdict (172 solved / 228 infeasible property instances, all 400
sub-class instances and all presets solved, the `infeasible` preset refuted by pre-solve);
`solver/tests/test_search_equivalence.py` now checks that against digests of the pre-S12d
verdicts. Assignments changed in every set except `infeasible`, so the full-answer digests were
re-recorded; pre-solve certificates and Welsh-Powell colourings are unchanged. Cost: computing
start counts and LCV at every node made `large` slower per node (7.1 s against 4.4 s for the
same 459 nodes on one seed set, single run, same machine).

**(b) Randomised restarts (Luby cutoffs, fixed seed) — not built.** With (a) the real instance
needs 92 nodes and no backtracking to speak of; a restart cutoff would never fire, so (b) could
not measurably help.

**(c) Min-conflicts local search — not built.** Only called for if (a) and (b) timed out.

## S12d result

Kept as recorded on 2026-10-19; since S12g the committed `solution.json` is the improved
timetable (score 2.0), and backtracking alone still gives this one.

| | |
|---|---|
| Machine | Intel64 Family 6 Model 183 (GenuineIntel), Windows, Python 3.12.10 |
| Pre-solve (D21) | passed |
| Backtracking | **solved**, 256 ms wall clock (pre-solve included; the committed `metadata.runtime_ms`), 92 nodes |
| Validator | `validate_solution`: no violations |
| Slots used | 34 |
| Welsh-Powell | unchanged: 32 colours, 8 sessions uncoloured, time-only check clean |

Quality (`solver/scoring.py`, rules version 1, weights untouched), with the printed timetable
from `docs/real-baseline-even-2025-26.md`:

| Rule | Weight | Generated raw | Generated penalty | Printed raw | Printed penalty |
|---|---|---|---|---|---|
| S-GAP | 2 | 79 | 158 | 2 | 4 |
| S-B2B | 1 | 42 | 42 | 23 | 23 |
| S-LOAD16 | 1 | 6 | 6 | 5 | 5 |
| FAC_LOAD_IMBALANCE | 0.5 | 113 | 56.5 | 93 | 46.5 |
| **Score** | | | **−162.5** | | **21.5** |

The search satisfies the hard constraints and optimises nothing soft, so it leaves 79 idle
student periods where SPIT's printed week has 2. The comparison is not like for like in one
respect: the printed timetable is not hard-feasible against this edge list (36 time-only
violations: 26 FACULTY_CLASH, all combined lectures under D40, and 10 PINNED_BLOCK), while the
generated one is. Closing the soft-score gap is Phase 3 work
(repair / local search on S-GAP and S-B2B), not part of S12d.

## Instance

`data/instances/even-2025-26/edge_list.json` (S9 export of the observed CE EVEN timetable):

| | |
|---|---|
| Sessions | 156: 60 theory (1 period), 96 practical (2 periods, one per batch) |
| Lab blocks | 31 |
| Conflict pairs | 1430 (1568 edges: 1020 COHORT, 548 FACULTY) |
| Rooms | 25 (rooms and sub-rooms) |
| Pinned occupancy | 339 entries |
| Cohorts / faculty with sessions | 40 / 24 |
| Faculty unavailability | 9 slots, all Swapnali Kurhade's Monday (D36, "PHD Day OFF") |
| Grid | D6: P0–P9, P2 coffee for all; lunch pinned per year (P5 SE, P4 TE) |

## S12a result (2026-10-18): timeout

| | |
|---|---|
| Machine | Intel64 Family 6 Model 183 (GenuineIntel), Windows, Python 3.12.10 |
| Pre-solve (D21) | passed: no counting, Hall, room-suitability or lab-capacity certificate |
| Backtracking | **timeout** after 300.06 s, 581,150 search nodes (an earlier run on the same machine: 533,625; node counts depend on load) |
| Deepest partial | 101 of 156 sessions: all 31 lab blocks (96 practicals) and 5 of the 60 theory sessions |
| Welsh-Powell | 32 colours (start slots); 8 sessions uncoloured; the time-only check (`validate_slot_placements`) on the 148 it coloured is clean |
| Score | none: no timetable (D33). Weights untouched |

The search places every lab block first (MRV picks the blocks, which have the smallest
domains) and then cannot fit the remaining theory around them, so it backtracks through
block placements without exhausting them in 300 s. Pre-solve passing proves nothing either way:
its checks are necessary conditions, and the blocks' joint placement is what binds here.

## Why it is tight

Each SE division has 45 grid slots (9 teaching periods a day). Pinned teaching slots naming the
division, by kind, with the decision behind each:

| Division | Pinned slots | Pin entries by kind (decision) |
|---|---|---|
| SE-Comp A, B | 31 | lunch 5 (D6); frozen items with a teacher 21: AS201 PCS labs (D44), SMCS / FOM - II (D26), MDM labs (D24); MDM 8, HSS 2, LLC 2, student activity 2 (D24) |
| SE-Comp C, D | 32 | as above, student activity 3 (D24) |
| TE-Comp A, TE Comp- B, TE Comp - C, TE Comp - D | 28 | lunch 5 (D6); frozen items with a teacher: electives BDA, IV, NLP, DL and MDM labs (D24); MDM 8, activity 2, major project 1 (D24) |

A batch shares its division's lectures and adds its own practicals. The tightest groups are
below, from the same cliques pre-solve builds (sessions pairwise joined by COHORT or FACULTY
edges): *need* is the periods they must occupy, *free* the distinct slots any of them can still
use after pins, unavailability and room fit, *slack* = free − need. Ties are broken by id.

### 10 most constrained cohorts

| Cohort | Need | Free | Slack |
|---|---|---|---|
| SE-Comp C | 15 | 19 | 4 |
| SE-Comp C, batch A | 15 | 19 | 4 |
| SE-Comp C, batch B | 15 | 19 | 4 |
| SE-Comp C, batch C | 15 | 19 | 4 |
| SE-Comp C, batch D | 15 | 19 | 4 |
| SE-Comp D | 15 | 19 | 4 |
| SE-Comp D, batch A | 15 | 19 | 4 |
| SE-Comp D, batch B | 15 | 19 | 4 |
| SE-Comp D, batch C | 15 | 19 | 4 |
| SE-Comp D, batch D | 15 | 19 | 4 |

SE-Comp A and B and their batches follow with slack 5 (free 20).

### 10 most constrained faculty

| Faculty | Need | Free | Slack | Note |
|---|---|---|---|---|
| Swapnali Kurhade | 16 | 18 | 2 | Monday unavailable (D36) |
| Anand Godbole | 14 | 18 | 4 | |
| Sudeep Mali | 6 | 10 | 4 | |
| Sunil Ghane | 12 | 16 | 4 | |
| Azman Qureshi | 6 | 11 | 5 | |
| Jyoti Ramteke | 6 | 11 | 5 | |
| Abhijeet Salunke | 14 | 20 | 6 | |
| Jignesh Sisodia | 16 | 22 | 6 | |
| Kailas Devadkar | 16 | 22 | 6 | |
| Sanjyuktarani Jena | 8 | 14 | 6 | |

### What Welsh-Powell could not colour

| Session | Cohort | Subject | Faculty |
|---|---|---|---|
| lecture | SE-Comp D | CE207 Design and Analysis of Algorithms | Prasenjit Bhavathankar |
| lecture | SE-Comp B | CE207 Design and Analysis of Algorithms | Anant Nimkar |
| practicals, one lab block | TE Comp - C, batches D and B | CE306 SPCC / CE307 Machine Learning | Anuj Tawari / Vaishnavee Rathod |
| practicals, one lab block | TE Comp- B, batches C, B and D | CE306 SPCC / CE307 Machine Learning / CE308 DevOps Lab | Anuj Tawari / Jyoti Ramteke / Azman Qureshi |
| practical, one lab block | TE Comp- B, batch A | CE306 SPCC | Aishwarya Nalawade |

Greedy colouring fixes each unit's slot at once and never revisits it, so these show where the
week runs out first, not that the instance is infeasible.

## What the S12a run did and did not say

- It did **not** say the instance is infeasible (S12d has since solved it).
- It did say the observed EVEN week is very tight once the frozen items (D24, D26, D44) and each
  year's lunch (D6) are pinned: SE cohorts keep 4–5 periods of slack in the week, and Swapnali
  Kurhade 2.
- Names in this report come from `data/instances/even-2025-26/display.json` (D41); the solver
  itself sees only ids.
