# Solving the real EVEN 2025-26 SE+TE instance (S12a, S12d, S12g)

Track A · reproduce with `python -m solver.benchmarks.real_solve`
(`solver/tests/test_real_solve.py` re-runs it under `pytest -m slow` and compares with the
committed file; CI checks the committed file and a 5,000-move local search, nothing timed).

**Committed result since S14u (2026-10-31): 26.5, 0 hard violations**, above the printed
timetable's 21.5. Both D58 options are now the default; the same command and parameters
(1,000,000 moves, seed 0) regenerated `solution.json`. See § S14u below. The S12g outcome
that follows was the committed result until then and is kept as history.

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

## S12h: Kempe chains and gap-aimed moves, off by default

2026-10-23 · Dhruv (with Claude Code) · branch `track/solver-extended-moves`.

```python
improve(payload, solution, *, max_moves=200_000, seed=0, time_limit_s=None,
        extended_moves=False, stats=None) -> dict
```

**What it adds.** With `extended_moves=True`, two more move kinds, ported by hand from the
unmerged S12g branch (`track/solver-quality-dhruv`, commit 5d85c09, which predates S13d–S15):

- a **Kempe-chain interchange** (Discrete Structures and Graph Theory). A unit (a session, or a
  lab block whole) and another start it allows. The chain is grown breadth-first through conflict
  neighbours that start at either start, and every chain session swaps between the two;
- a move **aimed at a student gap** (CE303). An idle period S-GAP counts is drawn, then a unit
  holding that cohort's students, sent onto the idle period half the time (else anywhere). It
  goes along a Kempe chain, or (80%) by ejecting the one or two sessions in its way into the
  periods it leaves.

The proportions are the branch's: 60% gap-aimed, 12% Kempe, the remaining 28% today's relocate,
swap and block moves. Chains are capped at 24 sessions. Every move goes through the same domain
and `_placement_ok` checks; pins, fixed sessions and blocks holding one never move; the result is
checked with `validate_solution`. Only the moves were ported. The annealing stays today's
(T 10 → 0.3 over the budget), not the branch's (15 → 0.05 in 100 stages, 300,000 proposals).
So the branch's +2.0 was a different search and is not expected here. Nothing was retuned for
this comparison.

**Off is unchanged.** With the option off no extra random number is drawn. Results and move
counts match digests recorded from `improve.py` before S12h (commit 748993e) on the real instance
(seeds 0–2 at 5,000 moves, seed 0 at 20,000) and on 31 property instances
(`test_option_off_reproduces_the_pre_s12h_results`). The slow test still re-derives the committed
`solution.json` (−15.0). The backend, `repair()` and bench do not pass the option, so their
results are unchanged.

### Comparison

Machine: Intel64 Family 6 Model 183 Stepping 1 (GenuineIntel), Windows 11, Python 3.12.10.
Every run starts from the backtracking timetable (−162.5): seeds 0–9, both settings, the same
budget, no time cap. The runs were sequential in one process, off and on alternating per seed,
with no other heavy work on the machine. All 40 results pass `validate_solution`. Seeds 0–9
were fixed before any run; no other seed was run. Penalties are mean (min–max) over the 10
seeds.

| Budget | Setting | Score mean | Score min | Score max | S-GAP | S-B2B | S-LOAD16 | FAC_LOAD_IMBALANCE | Runtime per run, s |
|---|---|---|---|---|---|---|---|---|---|
| 200,000 | off (default) | −15.50 | −29.0 | −4.0 | 28.4 (18–42) | 29.2 (27–33) | 6 (6–6) | 51.9 (50–55) | 16.7 (13.9–18.8) |
| 200,000 | extended | −13.65 | −23.5 | −4.5 | 22.6 (14–34) | 30.2 (26–35) | 6 (6–6) | 54.85 (52.5–57.5) | 16.1 (12.8–18.2) |
| 1,000,000 | off (default) | −8.30 | −22.5 | −0.5 | 21.6 (14–44) | 28.8 (23–33) | 6 (6–6) | 51.9 (48.5–55) | 70.9 (66.8–84.2) |
| 1,000,000 | extended | −6.85 | −14.0 | −3.0 | 17.2 (14–26) | 30.3 (26–33) | 6 (6–6) | 53.35 (50–57) | 68.7 (64.0–80.6) |

| Seed | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| 200k off | −18.5 | −17.5 | −5.5 | −17.5 | −22.0 | −20.0 | −11.0 | −29.0 | −10.0 | −4.0 |
| 200k extended | −15.5 | −4.5 | −11.0 | −23.5 | −14.5 | −15.0 | −5.5 | −10.0 | −15.0 | −22.0 |
| 1M off | −15.0 | −1.5 | −13.5 | −6.5 | −1.0 | −0.5 | −5.0 | −16.5 | −1.0 | −22.5 |
| 1M extended | −4.0 | −4.0 | −3.0 | −4.5 | −7.0 | −14.0 | −12.0 | −3.5 | −13.0 | −3.5 |

The off rows reproduce the S12g numbers above (200k: seed 0 −18.5, seeds 1–5 as listed there;
1M seed 0: −15.0, the committed file).

Paired by seed, extended minus off, as mean and 95% interval (Student t, 9 degrees of freedom;
Statistical Methods, CE205):

| Budget | Score | S-GAP penalty | S-B2B penalty | FAC_LOAD_IMBALANCE penalty | Seeds where extended scores higher |
|---|---|---|---|---|---|
| 200,000 | +1.85 [−5.81, +9.51] | −5.80 [−13.56, +1.96] | +1.00 [−1.70, +3.70] | +2.95 [+1.76, +4.14] | 6 of 10 |
| 1,000,000 | +1.45 [−6.68, +9.58] | −4.40 [−12.82, +4.02] | +1.50 [−0.38, +3.38] | +1.45 [−0.41, +3.31] | 5 of 10 |

**What it shows.**

- **No measurable score gain.** The mean is 1.5–1.9 points higher with the extended moves, but
  the intervals are wide and include zero: over 10 seeds the two settings are not
  distinguishable.
- **The extended moves trade S-GAP for imbalance.** They lower S-GAP by 4–6 points on average
  and pay back about two thirds of it in FAC_LOAD_IMBALANCE (+1.5 to +3.0; at 200k the only
  interval clear of zero) and S-B2B (+1.0 to +1.5).
- **They make the seeds agree more.** The standard deviation of the score is 6.19 against 7.78
  at 200k, and 4.40 against 7.95 at 1M. The worst seed is −23.5 against −29.0, and −14.0
  against −22.5. The best seed is not better: −3.0 against −0.5 at 1M.
- **Runtime is the same per move**, within run-to-run noise.
- They are used. Per 1M run, on average 22,948 Kempe and 56,286 gap-aimed moves are accepted.
  In the seed-0 run, 50 of its 59 new bests came from them (Kempe 13, gap 37).

**Honest caveats.**

- **Neither setting beats the printed timetable's 21.5.** The best single run is −0.5 (off,
  1M, seed 5); the best extended run is −3.0. Both are more than 21 points short.
- **S-GAP is still the blocker.** At 1M the lowest S-GAP in either setting is 7 raw (14
  points), the printed timetable's is 2. That is the floor S12g's single-rule runs reached. The
  extended moves lower the average, not that floor: the gaps held by frozen items (D24, D35)
  stay.
- **The default is unchanged.** `extended_moves` is off unless a caller passes it. The
  committed `solution.json`, `repair()`, the backend's solve job and bench all still run the
  three moves, and every committed number stays as it was. Turning it on anywhere is a separate
  decision; these results do not argue for it, beyond the narrower spread across seeds.
- One instance, one machine, 10 seeds per cell.

**The documented extended run**, for a second machine: from the backtracking timetable, seed 0
(the default, fixed before the runs), 1,000,000 moves, `extended_moves=True`. Score **−4.0**
(S-GAP 7, S-B2B 30, S-LOAD16 6, FAC_LOAD_IMBALANCE 108 raw); sha256 of `json.dumps(assignment,
sort_keys=True)` `35f9bcd0e2c024797e57ee300b601b87e54b6c90e783e327bb8ddf9487d6d75d`; 64.0 s
here. `pytest -m slow solver/tests/test_real_solve.py` re-runs it
(`test_extended_run_reproduces_the_documented_result`); since S14u it does so with the D58
defaults and pins 26.0 instead (§ S14u).

Reproduce one cell of the table (repo root, venv active):

```python
import json
from solver.backtracking import backtrack_solve
from solver.benchmarks.real_solve import INSTANCE
from solver.graph import build_conflict_graph
from solver.improve import improve

edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
start = backtrack_solve(build_conflict_graph(edge_list), edge_list).to_solution_v2_dict()
for seed in range(10):
    for extended in (False, True):
        result = improve(edge_list, start, max_moves=200_000, seed=seed, extended_moves=extended)
        print(seed, extended, result["quality"]["score"])
```

## S12i: lower bounds on the periods a week needs

2026-10-25 · Dhruv (with Claude Code) · branch `track/solver-bounds`. `solver/bounds.py`
(`lower_bounds(edge_list)`) is hand-written and stdlib only. It reads the edge list and solves
nothing, so no solve, improve or repair result changes.

- **Clique bound** (DSGT: clique number ≤ chromatic number). Sessions joined by a conflict
  edge need different periods, so the total length of a clique is a lower bound on the periods
  the week needs; a 2-period practical counts 2. The maximum-weight clique comes from a branch
  and bound (DAA) within 200,000 nodes. Past that budget it falls back to the best greedy
  clique, and `method` says which one was used. Tests check it against networkx's
  maximum-weight clique (in tests only) on 60 random graphs.
- **Load bounds.** For one teacher: session periods plus the teaching slots that pins hold or
  that they are unavailable at. For one cohort: session periods plus the teaching slots that
  pins hold. These count against the grid's 45 teaching slots. The year's lunch is one of the
  pins (the solver cannot tell lunch from another pin, D41), and ROADMAP §5's 40 periods per
  year are those 45 minus lunch.

Real instance (0.008 s):

| Bound | Value | What it is | Against |
|---|---|---|---|
| Clique (exact) | **18 periods** | Amey Ganesh Nile's 9 practicals, 2 periods each | 40 teaching periods per year: 22 spare |
| Heaviest teacher load | **25** | Swapnali Kurhade: 16 session periods + 9 unavailable slots (her Monday, D36) | 45 teaching slots: 20 spare |
| Heaviest cohort load | **41** | SE-Comp C: 9 session periods + 32 pinned slots (5 of them its lunch) | 45 teaching slots: 4 spare; 36 of the year's 40 without lunch |

So no single teacher, cohort or clique comes close to the week's limit on its own, except
SE-Comp C (and SE-Comp D, also 41), whose week is mostly pins. These are necessary conditions
only. The instance is tight because of how many cohorts and teachers overlap at once, which is
what the search and pre-solve deal with (see "Why it is tight" below), not because any one of
them is full.

## D58: what preferring sub-rooms would change (measured, not adopted)

2026-10-26 · Dhruv (with Claude Code) · branch `track/solver-repair-timeout`.

**What was measured.** The committed `solution.json` puts batch practicals in a whole split lab:
all 9 of 509's and all 9 of 606's sessions, 35 in all (S15d). The cause is the room order. The
backtracker's `_room_order` and `improve()`'s `_room_choices` try rooms in id order, and
`room-603` sorts before `sub-603-1`.

A scratch copy, not committed, patched both to try sub-rooms before a whole split lab, all else
equal. It ran the committed pipeline both ways in one run on this machine: backtracking, then
`improve()` with 1,000,000 moves, seed 0. The default run reproduced `solution.json` exactly.
Both results pass `validate_solution`.

Lab places are D8's 16 batch places: a split lab counts its sub-rooms (509: 2, 603: 3, 606: 2,
702: 3, 703: 2) and every other lab counts 1. Over the 45 teaching periods that is 720
place-periods. A session or pin in a sub-room holds that place; in the whole lab it holds all
of the lab's places.

| | Default (= `solution.json`) | Sub-rooms first |
|---|---|---|
| Score | −15.0 | **11.0** |
| S-GAP raw (penalty) | 13 (26.0) | **3 (6.0)** |
| S-B2B | 30 (30.0) | 26 (26.0) |
| S-LOAD16 | 6 (6.0) | 6 (6.0) |
| FAC_LOAD_IMBALANCE | 106 (53.0) | 102 (51.0) |
| Sessions in a whole split lab / in a sub-room: 509 | 9 / 0 | 0 / 10 |
| 603 | 8 / 3 | 0 / 15 |
| 606 | 9 / 0 | 0 / 14 |
| 702 | 5 / 10 | 0 / 23 |
| 703 | 4 / 6 | 0 / 11 |
| Rooms and sub-rooms used | 19 | 20 |
| Free lab place-periods (of 720) | 293 | **389** |
| Fewest free lab places in one period | 0 | 3 |
| Periods with no free lab place | 5 | 0 |
| Backtracking: nodes, score, time | 92, −162.5, 562.1 ms | 92, −107.0, 559.7 ms |
| `improve()` time (1,000,000 moves) | 163.9 s | 156.8 s |

The times come from this one run, with the machine loaded: S12h measured 64.0–84.2 s for the
same budget.

**Across seeds** (200,000 moves, seeds 0–4, the same starting point for each setting):

| Seed | 0 | 1 | 2 | 3 | 4 | Mean |
|---|---|---|---|---|---|---|
| Default | −18.5 | −17.5 | −5.5 | −17.5 | −22.0 | −16.2 |
| Sub-rooms first | 21.5 | 8.0 | 6.5 | 17.0 | **22.0** | 15.0 |
| S-GAP raw, default / sub-rooms first | 15 / 1 | 13 / 3 | 10 / 6 | 16 / 3 | 17 / 1 | |

The default row reproduces the S12g figures above.

**What this says.**

- **The score gain is consistent.** Sub-rooms first is better on all five seeds, by 12 to 44
  points, and at 1,000,000 moves seed 0.
- **Most of the S-GAP left comes from the room choice.** It falls to 1–6 raw. A whole-lab
  placement blocks the lab's other batch places, so another batch's practical cannot sit
  beside it and leaves a gap elsewhere.
- **The earlier analysis needs revising.** The S12g and S12h sections credit the remaining
  gaps to D24 frozen items; this shows the room choice holds most of them.
- **It can reach the printed timetable.** One run (seed 4, 22.0) beats the printed 21.5, and
  seed 0 equals it, so "neither beats 21.5" holds for the default only.
- **Lab capacity frees up.** No period is left without a free lab place.

**Caveats.**

- One instance and five seeds; 1,000,000 moves on seed 0 scored lower (11.0) than 200,000
  moves did (21.5), so the annealing is noisy.
- Repair changes too. Rebuilt with sub-rooms first, the S14l sequence's first repair (Swapnali
  Kurhade, Tue P5–P9) times out at 60 s, where today it solves in 2.61 s
  (`docs/repair-even-2025-26.md`, S14l). So the order changes which repairs are hard; it does
  not only help.
- **The default is unchanged** (D58). Adopting it is an all-track decision:
  - regenerate `solution.json`;
  - re-run the S15b, S15c and S15d evaluation numbers and the repair scenarios;
  - re-record the digests that pin today's results.

### S14s: `prefer_sub_rooms`, now an option (off by default)

2026-10-31 · Dhruv (with Claude Code) · branch `track/solver-subrooms-option`. Machine: Intel64
Family 6 Model 183, Python 3.12.10.

`backtrack_solve(..., prefer_sub_rooms=)`, `improve(..., prefer_sub_rooms=)` and
`repair(..., prefer_sub_rooms=)` (`solver/backtracking.py`, `_room_rank`) try a split lab's
sub-rooms just before that whole lab; every other room keeps its id order. This differs from the
S14l scratch copy above, which put every sub-room before every whole room, so the numbers
differ. Off is the default, and then every result is today's: `solution.json` is reproduced
exactly (test `solver/tests/test_d58_options.py`).

Fresh solve of the committed edge list (backtracking, then `improve()`), same starting point per
setting, seeds fixed before the runs. Penalties are the four rules' contributions, mean over the
seeds at 200,000 moves.

| | 1,000,000 moves, seed 0 (committed parameters): off | on | 200,000 moves, seeds 0–4: off | on |
|---|---|---|---|---|
| Score | −15.0 (= `solution.json`) | **26.5** | −18.5, −17.5, −5.5, −17.5, −22.0 (mean −16.2) | 9.0, 11.5, 18.5, 13.0, 12.5 (mean 12.9) |
| S-GAP penalty | 26.0 | 2.0 | 28.4 | 6.4 |
| S-B2B penalty | 30.0 | 20.0 | 29.6 | 25.2 |
| S-LOAD16 penalty | 6.0 | 6.0 | 6.0 | 6.0 |
| FAC_LOAD_IMBALANCE penalty | 53.0 | 45.5 | 52.2 | 49.5 |
| Hard violations | 0 | 0 | 0 on every seed | 0 on every seed |
| Batch practicals in a whole split lab | 35 | 0 | 36, 33, 34, 36, 39 | 0 on every seed |
| Free lab place-periods (of 720) | 293 | 389 | 283, 301, 295, 289, 277 | 389 on every seed |
| Periods with no free lab place | 5 | 3 | 4, 7, 8, 3, 5 | 0, 1, 5, 2, 1 |
| Backtracking | 92 nodes, −162.5, 251.0 ms | 92 nodes, −107.0, 246.4 ms | 92 nodes, −162.5 | 92 nodes, −107.0 |
| `improve()` run time | 68.2 s | 68.5 s | 13.6–14.0 s | 13.6–14.1 s |

At the committed parameters the option scores 26.5, above the printed timetable's 21.5, with 0
hard violations. It is better on all five seeds at 200,000 moves, at the same run time. How it
changes repair, including from a timetable regenerated this way, is in
`docs/repair-even-2025-26.md` § S14s, with the recommendation. The default stays off (D58)
until the team decides.

## S14u: both D58 options are the default (committed result)

2026-10-31 · Dhruv (with Claude Code) · branch `track/solver-d58-default`. Machine: Intel64
Family 6 Model 183 Stepping 1, Windows, Python 3.12.10.

The team decided on 2026-10-31 to make both options the default (D58), after § S14s showed
that both meet its three criteria. `backtrack_solve`, `improve` and `repair` now default to
`prefer_sub_rooms=True`, and `repair` to `last_ring_portfolio=True`. Both remain parameters:
passed as `False`, they give the pre-S14u results. `solver/tests/test_d58_options.py`
re-derives the old `solution.json` (−15.0) that way and checks its digest (slow).
`explain()` (`solver/mus.py`) passes `prefer_sub_rooms=False`, so explanations keep the id
order S14s measured them with. The backend passes neither option, so its solve and repair jobs
follow the new defaults.

`solution.json` was regenerated with the documented command,
`python -m solver.benchmarks.real_solve --time-limit 600` (1,000,000 moves, seed 0; neither
chosen by score). It is the run S14s measured, exactly, and passes `validate_solution` and the
`solution_v2` schema.

| | Committed until S14u (S12g) | **Committed since S14u** |
|---|---|---|
| Score | −15.0 | **26.5** |
| S-GAP raw (penalty) | 13 (26.0) | 1 (2.0): SE-Comp C batch B, Thursday 10.00 |
| S-B2B | 30 (30.0) | 20 (20.0) |
| S-LOAD16 | 6 (6.0) | 6 (6.0) |
| FAC_LOAD_IMBALANCE | 106 (53.0) | 91 (45.5) |
| Hard violations | 0 | **0** |
| Batch practicals in a whole split lab | 35 | **0** |
| Free lab place-periods (of 720, as in § D58) | 293 | **389** |
| Periods with no free lab place | 5 | 3 |
| Backtracking | 92 nodes, −162.5 | 92 nodes, −107.0, 263.8 ms |
| `improve()` | 136.1 s (AMD machine, S12g) | 77.7 s; 860,159 infeasible, 92,639 accepted (relocate 9,752, swap 76,967, block 5,920), 65 new bests |
| sha256 of `json.dumps(assignment, sort_keys=True)` | `70040ba1…a17d` | `995a4756…e6b7` |

Against the printed timetable (21.5, 36 hard violations), the generated one now scores 5.0
higher with 0 hard violations. S-GAP is 1 raw against the printed 2.

**The documented extended run** (S12h: from the backtracking timetable, seed 0, 1,000,000
moves, `extended_moves=True`) with the new defaults: **26.0** (S-GAP 1, S-B2B 20, S-LOAD16 6,
FAC_LOAD_IMBALANCE 92 raw), sha256 `035a6cedb05998551f9549a2f1ec714176c0eeddd8f547060055cffef07c53c2`,
73.7 s. `test_extended_run_reproduces_the_documented_result` pins it.

**Found: a fresh solve that sub-rooms first cannot finish.** S14s measured fresh solves of the
committed edge list only. With the SE-Comp A CE207 lecture (`obs-t0-r1-c3-l0`) given to Sudhir
Dhage, the one qualified teacher free at its new slot, a fresh `backtrack_solve` of the changed
edge list:

| Room order | Outcome | Nodes | Time |
|---|---|---|---|
| sub-rooms first (default) | timeout | 131,291 | 30.0 s |
| sub-rooms first (default) | timeout | 430,708 | 120.0 s |
| id order (`prefer_sub_rooms=False`) | solved | 92 | 0.34 s |

The change is feasible, and its repair is immediate (nothing moves). But a backend solve job
built with that accepted substitution (D52) now reports a timeout where the old order solved it
in under a second. The timeout is reported as a timeout, never as infeasible (D33). The same
substitution to Prasenjit Bhavathankar or Nataasha Raul solves in 92 nodes either way. This
is the S14l pattern in the other direction: each room order has instances it thrashes on.
Proposed for the team, not built: give a fresh solve the same portfolio as repair's last ring
(a node budget, then the other room order). `backend/tests/test_substitution.py` therefore
accumulates the Bhavathankar substitution, as it did before S14u.

### Fixed: a fresh solve tries rooms by id when sub-rooms first runs out of nodes

2026-10-31 · Dhruv (with Claude Code) · branch `track/solver-solve-fallback`. Same machine.

The regression broke D58's first criterion ("nothing that finished before times out") for
fresh solves. The fix is in `backtrack_solve`, the call the backend's solve job makes
(`backend/app/service.py`, `solve_edge_list`; no backend code changed). With
`prefer_sub_rooms` on and no `node_limit` from the caller, it makes up to two attempts:

1. **Sub-rooms first, within `SUB_ROOM_NODES = 5,000` nodes.** A verdict stands: solved, or
   infeasible whether proven by pre-solve or by search. If the clock runs out first, the result
   is a timeout, never infeasible (D33).
2. **Rooms by id, in what is left of `time_limit_s`.** Only if the first attempt used up its
   nodes with no verdict.

Then `improve()` runs as before.

- **The node budget rule.** `SUB_ROOM_NODES` equals `RING_NODES`, the budget `repair` already
  gives each frozen ring (S14a). It was fixed before any measurement of this fix, never by a
  score, and `test_the_first_attempt_gets_repairs_ring_budget` holds the two equal.
- **Deterministic.** The budget is in nodes, so whether the second attempt runs is the same on
  every machine. Only a clock that runs out first changes it, and that is a timeout.
- **What is recorded.** `backtrack_solve(..., stats=)` gets `attempts`: `[order, nodes, outcome]`
  per attempt. After a second attempt the result has `rooms_by_id_fallback` set and
  `nodes_explored` counts both attempts. `solution.v2`'s `metadata` allows no new key, so the
  free-text `metadata.algorithm` says it instead: `backtracking(forward-checking, mrv), rooms by
  id after 5000 nodes`. No contract change; a first-attempt result keeps today's text.
- **Repair is unchanged.** It passes `sub_room_nodes=None`, because its rings and its last-ring
  portfolio have their own budgets. Every number in `docs/repair-even-2025-26.md` § S14u
  stands. `explain()` keeps rooms by id, so it makes one attempt.

The id-order attempt runs in full after the budget. So whatever the id order solved before
S14u still solves, given the budget's extra time (about 1.5 s here).

Fresh solves, 30 s limit, as the backend calls it:

| Edge list | Attempts (order, nodes, outcome) | Result | Time |
|---|---|---|---|
| committed | sub-rooms first, 92, solved | solved, 92 nodes | as before |
| committed + CE207 to Sudhir Dhage | sub-rooms first, 5,001, budget out; rooms by id, 92, solved | **solved**, 5,093 nodes, 0 hard violations | **1.79 s** (two runs; was a timeout at 30 s and 120 s) |
| committed + CE207 to Nataasha Raul | sub-rooms first, 92, solved | solved | 0.27 s |
| committed + CE207 to Prasenjit Bhavathankar | sub-rooms first, 92, solved | solved | 0.29 s |
| synthetic `infeasible` preset, seed 1 | sub-rooms first, 0, infeasible (pre-solve, `cohort_load`) | infeasible, no second attempt | |
| odd cycle (`test_search_equivalence.py`) | sub-rooms first, 3, infeasible (search) | infeasible, no second attempt | |

`solution.json` is byte-identical: the committed instance solves in the first attempt, and
`test_real_instance_reproduces_the_committed_result` (slow) re-derives it. The search-equivalence
digests (defaults), the pre-S12h digests (options off) and the verdicts of the property
instances and synthetic presets are all unchanged. None of them needs a second attempt. Tests:
`solver/tests/test_d58_options.py`.

**Fresh solves after the S14u demo flows** (2026-11-01, branch `track/solver-leftovers`, same
machine). Each change is accepted and applied as the backend builds a solve's edge list
(`apply_change` for every accepted change; D52). The search runs as the solve job runs it:
`backtrack_solve`, `time_limit_s=30`. Hard violations are counted against the changed edge
list. The flows are in `docs/repair-even-2025-26.md` § S14u "Demo flows". The drag onto the
MDM-I lab is impossible and needs no solve.

| Change accepted | Attempts used | Outcome | Time (two runs) | Hard violations |
|---|---|---|---|---|
| (a) Swapnali Kurhade unavailable Tue P1 and Thu P1 | sub-rooms first only (92 nodes) | solved | 0.29 s, 0.29 s | 0 |
| (c) Amey Ganesh Nile takes CE206 for SE-Comp C (`obs-t4-r1-c2-l0`) | sub-rooms first only (92 nodes) | solved | 0.30 s, 0.31 s | 0 |
| (d) CE207 lecture dragged to Wed P0, 601 | sub-rooms first only (92 nodes) | solved | 0.31 s, 0.30 s | 0 |
| (a) and (c) both | sub-rooms first only (92 nodes) | solved | 0.30 s, 0.31 s | 0 |
| S14i sequence: Kurhade unavailable Tue P5–P9, then the SE-Comp A CE207 lecture (`obs-t0-r1-c3-l0`) to Prasenjit Bhavathankar | sub-rooms first only (92 nodes) | solved | 0.31 s, 0.32 s | 0 |

An accepted drag is only a placement (D52): the backend accumulates absences, room closures and
substitutions, not moves (`ACCUMULATED` in `backend/app/service.py`). So the fresh solve after
(d) runs on the committed edge list. None of these solves needs the second attempt. Only the
search was timed; a solve job's `improve()` comes after it.

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
