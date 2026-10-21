# Solving the real EVEN 2025-26 SE+TE instance (S12a, S12d, S12g)

Track A · reproduce with `python -m solver.benchmarks.real_solve`
(`solver/tests/test_real_solve.py` re-runs it under `pytest -m slow` and compares with the
committed file; CI checks the committed file and a 5,000-move local search, nothing timed).

**Outcome (S12g, 2026-10-21): solved, then improved by local search from −162.5 to −15.0.**
Backtracking solves the instance in 0.45 s (92 nodes, as in S12d); `solver.improve.improve`
(simulated annealing, 1,000,000 moves, seed 0) then raises the score to **−15.0**. The result
passes `solver.validate.validate_solution` with no violation and is committed as
`data/instances/even-2025-26/solution.json` (`solution.v2`, algorithm
`backtracking(forward-checking, mrv) + local-search(simulated-annealing, moves=1000000, seed=0)`;
identical across runs apart from `metadata.runtime_ms`). **It does not beat the printed
timetable's 21.5**: it is 36.5 points short, 22 of them in S-GAP (below).

## S12g: where the −162.5 came from

The S12d timetable (backtracking only), by rule (`quality_rules.yaml` version 1, weights untouched):

| Rule | Weight | Raw | Penalty | Where |
|---|---|---|---|---|
| S-GAP | 2 | 79 | 158 | TE Comp - C 20, TE Comp- B 16, TE Comp - D 15, TE-Comp A 8, each SE division 5 (division and its batches together) |
| S-B2B | 1 | 42 | 42 | Anand Godbole, Swapnali Kurhade, Sudhir Dhage, Abhijeet Salunke 4 pairs each; Kailas Devadkar, Anant Nimkar 3 |
| S-LOAD16 | 1 | 6 | 6 | Amey Ganesh Nile, Azman Qureshi, Isha Sawalkar, Jyoti Ramteke, Sudeep Mali 18 h; Jignesh Sisodia 17 h |
| FAC_LOAD_IMBALANCE | 0.5 | 113 | 56.5 | Vaishnavee Rathod 8 h; Yogita Patil, Sudhir Dhage, Prasenjit Bhavathankar, Swapnali Kurhade, Surekha Dholay, Sanjyuktarani Jena, Rupali Sawant 5 h |
| **Score** | | | **−162.5** | |

S-GAP counts a cohort's idle periods, and a batch sits in its division's lectures, so one idle
period of a whole division counts five times (the division and its four batches): 10 points.
The search satisfied the hard rules and optimised nothing soft; S-GAP alone was 154 of the
184 points between it and the printed timetable.

**What D40 costs** (combined lectures scheduled as one lecture per division). In the printed
timetable 26 slots are combined lectures of 9 teachers (Kailas Devadkar, Anant Nimkar, Jignesh
Sisodia, Sunil Ghane, Anand Godbole, Swapnali Kurhade, Abhijeet Salunke, Prasenjit Bhavathankar
3 each, Reeta Koshy 2), so D40 gives those teachers 26 more teaching hours. Measured:

- S-LOAD16: exactly **+1 point**. Jignesh Sisodia teaches 17 h under D40 and would teach 14 h
  with his 3 combined lectures counted once; the other five flags do not change.
- FAC_LOAD_IMBALANCE: **no effect on its floor**. A lower bound per teacher (pins fixed,
  sessions placed as whole 1 h / 2 h pieces, D36's unavailable Monday respected, every other
  constraint ignored) sums to 68 with D40 and 68 without.
- S-B2B: the 9 D40 teachers hold 26 of the 42 pairs (17 of 30 after S12g). More hours make
  adjacent hours likelier, but no single number separates D40's share.
- S-GAP: none. D40 changes teachers' hours, not students'.

**What D24 costs** (frozen items pinned). 13 teachers teach only frozen items; their
FAC_LOAD_IMBALANCE is fixed at 29 h, **14.5 points** in every timetable of this instance,
the printed one included. 10 of the 42 S-B2B pairs (6 of 30 after S12g) pair a session with a
frozen slot. Four of the six S-LOAD16 flags (Azman Qureshi, Isha Sawalkar, Jyoti Ramteke, Sudeep
Mali) include pinned hours.

## S12g: the local search

`solver/improve.py`, hand-written; simulated annealing and hill climbing from Artificial
Intelligence and Soft Computing (CE303). Public API, for the backend after `backtrack_solve`:

```python
improve(payload, solution, *, max_moves=200_000, seed=0, time_limit_s=None, stats=None) -> dict
```

- **Moves.** Relocate one session outside a lab block to another start and room; swap the
  starts of two such sessions that share a cohort or a teacher; move a whole lab block to
  another start. A block move trades places with what is in its way: 1-period sessions take the
  block's old periods period for period, and a lab block starting exactly there takes the old
  start whole.
- **Hard rules on every move.** A placement must be in the session's static domain (the
  backtracker's `_build_initial_domains`: grid, contiguity, availability, pinned faculty, cohort
  and room slots, so a block never covers a year's lunch; room type, capacity, `fixed_slot`) and
  pass the backtracker's `_placement_ok` (conflict edges, room occupancy with sub-room lockout,
  every occupied period). Pins are not sessions and never move; sessions with a `fixed_slot`, and
  blocks holding one, are never moved. `improve` validates its input and its result with
  `validate_solution`, which shares no code with the search.
- **Objective.** `scoring.py`'s penalty with the YAML weights, kept per (cohort, day), (teacher,
  day) and teacher, so a move recomputes only what it touches. S-LOAD16 cannot change (who
  teaches what is fixed) and is a constant. The start and the result are re-scored with
  `scoring.score` and must agree with the incremental figures.
- **Annealing.** A move that does not raise the penalty is kept; one that does is kept with
  probability exp(−Δ/T), T cooling geometrically from 10 to 0.3 penalty points over the budget
  (a one-gap loss is kept 80% of the time at the start, 0.1% at the end). The best timetable
  seen is returned, so the score never drops. One `random.Random(seed)`, every choice drawn from a
  sorted list: a seed and a budget fix the result. `time_limit_s` is only a safety cap
  (`stopped_by_time` in `stats`); the real-solve runner passes 600 s. The default budget stays
  200,000 moves (about 23 s here); the backend passes its own. The committed run uses
  1,000,000 (`solver.benchmarks.real_solve.MOVES`).
- **Tabu search: not built.** Nothing measured that it would do better.

### Before and after

| Rule | Weight | Backtracking raw | Penalty | **After local search raw** | **Penalty** |
|---|---|---|---|---|---|
| S-GAP | 2 | 79 | 158 | **13** | **26** |
| S-B2B | 1 | 42 | 42 | **30** | **30** |
| S-LOAD16 | 1 | 6 | 6 | 6 | 6 |
| FAC_LOAD_IMBALANCE | 0.5 | 113 | 56.5 | **106** | **53** |
| **Score** | | | **−162.5** | | **−15.0** |

After: S-GAP is SE-Comp B 5 (one whole-division idle period, Friday 11.15), TE Comp - C 5 (one,
Thursday 13.15), TE-Comp A batch A 2 (Wednesday 13.15–15.15), SE-Comp C batch B 1. S-B2B: Anand
Godbole, Swapnali Kurhade, Vaishnavee Rathod 3 pairs each. FAC_LOAD_IMBALANCE: Sudeep Mali 6 h;
Rupali Sawant, Sanjyuktarani Jena, Sudhir Dhage, Swapnali Kurhade (Monday off under D36), Yogita
Patil, Vaishnavee Rathod 5 h. Against 200,000 moves (−18.5: S-GAP 15, S-B2B 32,
FAC_LOAD_IMBALANCE 101) the gain is S-GAP −2 and S-B2B −2 raw (−6 points), against
FAC_LOAD_IMBALANCE +5 raw (+2.5).

### Moves used and runtime

| | |
|---|---|
| Machine | AMD64 Family 23 Model 104 Stepping 1 (AuthenticAMD), Windows, Python 3.12.10 |
| Backtracking | solved, 452.0 ms, 92 nodes |
| Local search | 136,120.1 ms; committed `metadata.runtime_ms` 136,572 (both steps); whole runner 2 min 17 s |
| `test_real_solve`, default (CI) | 3 tests, about 2.7 s (5,000 moves twice); safety cap 600 s |
| `test_real_solve`, `-m slow` | 120.3 s (full reproduction, compared with `solution.json`) |
| Moves proposed | 1,000,000 (the budget; not stopped by time) |
| Infeasible | 880,038 (88%: the week is tight, most random targets clash) |
| Accepted | 86,214: relocate 9,396, swap 74,719, block 2,099 |
| New best | 47: relocate 27, swap 14, block 6 |

The committed budget is chosen by score, no longer by CI time: 1,000,000 moves, seed 0 (the
default, not picked by score; no other seed was run at this budget), −15.0 against −18.5 at
200,000. The schedule (T 10 → 0.3) was chosen on this instance earlier. At 200,000 moves other
seeds gave 1 −17.5, 2 −5.5, 3 −17.5, 4 −22.0, 5 −20.0; at 250,000 moves seeds 0–3 gave −10.0,
−18.0, 8.5, −20.0. The best seen in any run (8.5) is still below 21.5. A first schedule (T 2 → 0.05) gave −38.5 at 100,000 moves.
Before a block move could trade places with what is in its way, 113 of 100,000 moves were
accepted block moves; 1-period sessions and other blocks almost always stand in the way.

## S12g: side by side with the printed timetable

| | Generated (S12g) | Printed (`docs/real-baseline-even-2025-26.md`) |
|---|---|---|
| Score | **−15.0** | **21.5** |
| S-GAP | 13 raw, 26 | 2 raw, 4 |
| S-B2B | 30 raw, 30 | 23 raw, 23 |
| S-LOAD16 | 6 raw, 6 | 5 raw, 5 |
| FAC_LOAD_IMBALANCE | 106 raw, 53 | 93 raw, 46.5 |
| Hard violations (time only) | **0** | **36** (26 FACULTY_CLASH: combined lectures under D40; 10 PINNED_BLOCK) |

**Why it cannot reach 21.5, and what blocks it.** The generated timetable is 36.5 points short:
S-GAP +22, S-B2B +7, FAC_LOAD_IMBALANCE +6.5, S-LOAD16 +1. Annealing each rule alone with
the same moves (100,000–500,000 moves, the other weights set to 0, in scratch runs only) bottoms
out at S-GAP 7, S-B2B 19 and FAC_LOAD_IMBALANCE 93. Even those three floors together, which no
single timetable reached, give 14 + 19 + 6 + 46.5 = 85.5, a score of 14.5: still 7 short.
So:

- **S-GAP blocks it**, by 5 raw (10 points) at its best, 11 raw (22 points) in the committed
  timetable. Idle periods survive on batch-days holding only frozen items, e.g. TE-Comp A
  batch A on Wednesday (no session that day), idle at 13.15–15.15 between frozen slots. No
  period is unfillable in principle (some session's domain covers each one), so this is the floor this search reaches, not a proof. These frozen items
  (D24) block some batches of a division and not others. The printed timetable reaches 2 partly
  by putting practicals into slots frozen items hold (its 10 PINNED_BLOCK violations, all TE
  batches). **This is D24**, together with the parked D46 (electives that block only some batches).
- **S-LOAD16 +1 is D40**, exactly (Jignesh Sisodia).
- **S-B2B and FAC_LOAD_IMBALANCE are not the blocker**: their floors (19, 93) match or beat the
  printed values (23, 93). D24 fixes 14.5 points of FAC_LOAD_IMBALANCE in both timetables; D40
  adds teaching hours, not a measurable floor.

Revisiting D46/D47 (parked on 2026-10-20 until S12g) is a team decision; nothing here changes
the edge list.

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

## S12d result (before local search)

| | |
|---|---|
| Machine | Intel64 Family 6 Model 183 (GenuineIntel), Windows, Python 3.12.10 |
| Pre-solve (D21) | passed |
| Backtracking | **solved**, 256 ms wall clock (pre-solve included; the `metadata.runtime_ms` committed in S12d), 92 nodes |
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
