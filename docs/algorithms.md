# Chronos solver: algorithms (S16a)

2026-10-25 · Dhruv (with Claude Code) · branch `docs/algorithms`. One section per algorithm in
`solver/`, checked against the code on `main` (commit 0d6b10e). Every measured number links to
where it was recorded: [evaluation](evaluation-even-2025-26.md), [real
solve](real-solve-even-2025-26.md), [repair](repair-even-2025-26.md). Course names are the
eight of CLAUDE.md rule 6. Where a docstring names another course (CE303, Artificial
Intelligence and Soft Computing), this document gives the closest of the eight and says why
(S14s); those docstrings still say CE303. Rechecked against `main` on 2026-10-31 (S14s).

## Overview

**Pipeline.** The solver reads one `edge_list_v1` payload (plain data from Track B's export)
and returns `solution.v2`. A solve, as run by `solver.benchmarks.real_solve` and by the
backend's solve job (`backend/app/service.py`, `solve_edge_list`), goes:

1. **Edge list → conflict graph.** `build_conflict_graph` builds one vertex per session and one
   edge per declared conflict.
2. **Pre-solve.** Polynomial infeasibility checks (pigeonhole, Hall via Hopcroft–Karp, lab
   capacity) run inside `backtrack_solve` before any search. A failed check is a proof of
   infeasibility (ROADMAP D21).
3. **Backtracking.** Forward checking, MRV with a degree tie-break, least-constraining starts,
   lab blocks placed jointly. The outcome is `solved`, `infeasible` or `timeout`, and a timeout
   is never reported as infeasible (D33).
4. **Improve** (solved only). Simulated annealing over valid timetables (`improve.py`).
5. **Validate.** The independent checker (`validate.py`) re-checks every hard rule.
   `improve()` runs it on its input and its result.
6. **Score.** The four YAML rules (`scoring.py`), computed when the result is written and
   re-checked by `improve()`.

If the solve is infeasible, the backend's solve job explains it with `explain()` (`mus.py`).

**On a change** (an absence, a closed room, a drag, a substitution), `repair()` (`repair.py`)
keeps the accepted timetable and moves as little as it can. If no timetable exists, `explain()`
gives a minimal conflicting set and a verified relaxation. `substitute_candidates()` lists who
can take a session where it is. `lower_bounds()` (`bounds.py`) is a standalone check that no
pipeline calls.

**Symbols** used in every complexity below:

| Symbol | Meaning (real EVEN instance, from [real solve § Instance](real-solve-even-2025-26.md#instance)) |
|---|---|
| n | sessions (156) |
| m | conflict edges in the payload (1,568) |
| s | teaching slots in the week, days × teaching periods (5 × 9 = 45) |
| r | rooms and sub-rooms (25) |
| k | local-search moves (`max_moves`) |
| d | periods one session occupies, at most 2 here |
| p | `pinned_occupancy` entries (339) |
| C, F | cohorts, faculty members with sessions (40, 24) |
| g | constraint groups in an explanation (493 on the real instance, [repair § S14b](repair-even-2025-26.md#s14b-explaining-an-infeasible-change)) |
| q | qualified faculty ids passed to `substitute_candidates` |

**At a glance.** "Exp." marks a search that is exponential in the worst case, and the last
column says what stops it in practice.

| Algorithm | File: main function | Time | Course (as in the code) | Bounded by |
|---|---|---|---|---|
| Conflict graph | `graph.py`: `build_conflict_graph` | O(n + m + p) | DSGT | n/a |
| Welsh-Powell colouring | `colouring.py`: `welsh_powell` | O(n log n + s·d·(n + m)) | DSGT | n/a (greedy) |
| Backtracking + FC, MRV, degree, LCV, lab blocks | `backtracking.py`: `backtrack_solve` | Exp.: O((s·r)^n) nodes, O(n·s·r) per node | DAA (CE207) | `node_limit`, `time_limit_s` |
| Pre-solve (pigeonhole, Hall/Hopcroft–Karp, lab capacity) | `presolve.py`: `presolve`, `hopcroft_karp` | O(n·s·r + (F + C)·s²·√s) | Discrete Structures, CE201; CE207 | n/a (polynomial) |
| Independent validator | `validate.py`: `validate_solution` | O(n log n + m·d + p + n²·d) worst | Software Engineering | n/a |
| YAML quality scoring | `scoring.py`: `score`, `load_rules` | O((C + m)·s + n·d + p) | Data Structures; DSGT; Statistical Methods, CE205; Software Engineering | n/a |
| Simulated-annealing `improve()` (+ Kempe, gap moves, D54) | `improve.py`: `improve` | O(n·s·r·d + k·L), L local | DAA; DSGT; Data Structures; Statistical Methods | `max_moves` (k) |
| Freeze-and-expand repair | `repair.py`: `repair`, `apply_change` | Exp. in its last ring | CE207; DSGT | `RING_NODES`, `time_limit_s` |
| Minimal conflicting set + verified relaxation | `mus.py`: `explain`, `apply_action` | Exp. without budgets; O(g) checks | DAA | `MUS_NODES`, `time_limit_s` (S14k) |
| Substitution candidates | `repair.py`: `substitute_candidates` | O(q·(n + m + V + S)) | Data Structures | n/a |
| Clique and load lower bounds | `bounds.py`: `lower_bounds` | Exp. exact clique, O(n) per node | DSGT; DAA; Data Structures | `EXACT_NODES`, then greedy |

V and S are the validator's and the scorer's costs.

## Conflict graph

**What.** `build_conflict_graph` turns the edge list into one vertex per session and one
undirected edge per declared FACULTY, COHORT or ROOM conflict. It keeps every reason of a pair,
and it also keeps faculty unavailability, pinned slots per cell and the lab blocks. It trusts
the data layer's edges and checks only structure: known ids, no self-loops, every faculty has
an availability entry, a well-formed grid, and consistent lab blocks.

**Where.** `solver/graph.py`: `build_conflict_graph`, `ConflictGraph` (`neighbours`, `degree`),
`slot_is_open`, `available_slots_for`. The grid is `solver/slots.py`: `SlotGrid`.

**Complexity.** Time O(n + m + p + u), with u the unavailable-slot entries: one pass over each
payload list. Space O(n + m) for the adjacency dict of dicts, which gives O(1) neighbour
lookups.

**Determinism.** A pure function of the payload.

**Course.** Discrete Structures and Graph Theory, as `graph.py`'s docstring says: an undirected
conflict graph, adjacency as a map of neighbour sets. `slots.py` describes each day's teaching
periods as disjoint paths (Discrete Structures, CE201).

**Measured.** Real instance: 156 sessions, 1,568 edges (1,020 COHORT, 548 FACULTY), 1,430
conflicting pairs ([real solve § Instance](real-solve-even-2025-26.md#instance)).

## Welsh-Powell colouring

**What.** A greedy colouring in which a colour is a start slot. Units (a lab block whole, or
one session) go in this order: fixed first, then descending degree, then the smallest id. Each
takes the first start in slot order at which every occupied period is open for its teacher and
cohort and clear of already-coloured neighbours. It assigns no rooms and never backtracks, so a
unit with no start is left unplaced.

**Where.** `solver/colouring.py`: `welsh_powell`, `_units`, `_try_start`.

**Complexity.** Time O(n log n + s·d·(n + m)): the sort, then for each unit at most s starts,
each checking its members' d periods and their neighbours. Space O(n·d + m).

**Determinism.** Fully deterministic: the unit order and the start order are both sorted.

**Course.** Discrete Structures and Graph Theory, as `colouring.py`'s docstring says: greedy
vertex colouring in Welsh-Powell's largest-degree-first order.

**Measured.** Real instance: 8 sessions unplaced, 148 coloured with 0 time-only violations,
10.9 ms ([evaluation § 1](evaluation-even-2025-26.md#1-algorithms)). Which sessions were left
out: [real solve § What Welsh-Powell could not
colour](real-solve-even-2025-26.md#what-welsh-powell-could-not-colour). On the synthetic
presets it colours every session of `small`, `medium` and `large` ([evaluation §
1](evaluation-even-2025-26.md#1-algorithms)).

## Backtracking with forward checking

**What.** A depth-first search over (start slot, room) values.

- **Variable choice.** The next variable is the one with the fewest start slots left (MRV).
  Ties go to the most unassigned conflict neighbours (degree), then to the smaller id. Lab
  blocks and single sessions compete in that one ordering.
- **Value order.** Starts are tried least constraining first: fewest (neighbour, start) values
  removed, then slot order, with rooms by id. With `prefer_sub_rooms` (on by default since
  S14u, D58; added in S14s) a split lab's sub-rooms come just before the whole lab. A lab block is one variable:
  every member takes the same start, each in its own room or sub-room.
- **Forward checking.** After each placement, the values that now clash are pruned from
  neighbours' domains and from every domain using the same room. Each prune is recorded on a
  trail and undone exactly when the search backtracks.
- **Symmetry breaking.** Interchangeable rooms on an unused day are tried only once. The
  docstring states that this never changes the first solution found.
- **Two attempts when sub-rooms come first.** Each room order has feasible instances it
  thrashes on. So with `prefer_sub_rooms` and no caller `node_limit`, the first attempt gets
  `SUB_ROOM_NODES = 5,000` nodes (repair's `RING_NODES`, fixed before any measurement). If they
  run out with no verdict, a second attempt with rooms by id runs in the time left. A verdict of
  the first attempt stands, infeasible included. `stats["attempts"]` records each attempt, and
  `metadata.algorithm` names the fallback. Repair passes `sub_room_nodes=None` (its rings have
  their own budgets), and `explain()` uses rooms by id. Course: Design and Analysis of
  Algorithms (a portfolio of two orders with a fixed budget).

**Where.** `solver/backtracking.py`:

- `backtrack_solve`, the entry point;
- `_select_variable` (MRV and degree), `_start_order` (LCV), `_forward_check`, `_undo_trail`;
- `_lab_block_candidates` and `_gen_room_tuples` (joint lab placement);
- `_symmetric_duplicate`.

**Complexity.**

- Building the domains is O(n·s·r·d).
- One node costs O(n·s·r): choosing the variable reads every domain, and forward checking scans
  every unassigned domain for the room it used.
- The tree is **exponential in the worst case**, O((s·r)^n) leaves.
- Space is O(n·s·r) for the domains and the trail.

In practice, pre-solve refutes the counting cases before any search. `node_limit` (machine
independent) and `time_limit_s` stop it and report `timeout`, never `infeasible` (D21, D33).

**Determinism.** Every order is sorted with an id tie-break, so the same input gives the same
search. `time_limit_s` is wall clock, so whether a long search ends `solved` or `timeout` can
differ between machines. `node_limit` cannot.

**Course.** Backtracking and its search tree: Design and Analysis of Algorithms, CE207. MRV,
degree and least-constraining-value: also Design and Analysis of Algorithms, as the orderings
that prune a backtracking search tree (the docstrings say CE303, not one of the eight).

**Measured.**

- Real instance: solved in 92 nodes, 187.6 ms, score −162.5 before improve ([evaluation §
  1](evaluation-even-2025-26.md#1-algorithms)). The S12d run was 0.26 s and 92 nodes ([real
  solve § S12d result](real-solve-even-2025-26.md#s12d-result-before-local-search)).
- The earlier order (labs first, ascending starts) timed out at 300 s; why LCV fixed it is in
  [real solve § S12d: what changed](real-solve-even-2025-26.md#s12d-what-changed-and-what-each-step-measured).
- Runtime vs size: [evaluation § 2](evaluation-even-2025-26.md#2-runtime-vs-size) and [§
  6](evaluation-even-2025-26.md#6-runtime-and-score-vs-size-s15c): 33 to 183 nodes, 157.9 ms
  to 2,921.2 ms, for 50 to 290 sessions.

## Pre-solve checks

**What.** Necessary conditions, checked on the initial domains before the search. They run in
this order:

1. **Room suitability:** every session has a room of the right type and capacity.
2. **Pigeonhole load:** a greedy clique of pairwise-conflicting sessions is grown per teacher
   (on FACULTY edges) and per cohort (on COHORT edges). If its periods exceed the slots they
   can reach, the instance is infeasible.
3. **Lab capacity:** the lab sessions forced into one period cannot outnumber the lab rooms
   usable in parallel then.
4. **Hall's condition:** a maximum bipartite matching of the group's periods to slots, found
   by Hopcroft–Karp. An unmatched period gives a Hall violator.

A failure is a `Certificate`, a proof of infeasibility (method `presolve`, D43). A pass proves
nothing.

**Where.** `solver/presolve.py`: `presolve`, `_clique`, `_load`, `_lab_capacity`, `_hall`,
`hopcroft_karp`. It is called inside `backtrack_solve`.

**Complexity.** Polynomial.

- Reachable slots per session: O(n·s·r).
- One greedy clique per teacher and per cohort: F + C groups.
- The load check is linear in each group.
- Hall runs only if every load check passed, so a group's periods are at most s. Each
  Hopcroft–Karp is then O(E·√V) = O(s²·√s) (its docstring gives O(E sqrt(V))).
- Lab capacity: O(n·s·d + s·r).
- Space: O(n·s + s²).

**Determinism.** Groups, sessions and slots are iterated in sorted order, and the first failed
check is returned.

**Course.** Pigeonhole: Discrete Structures, CE201. Hall's theorem and Hopcroft–Karp: Design
and Analysis of Algorithms, CE207.

**Measured.**

- The real instance passes ([real solve § S12d
  result](real-solve-even-2025-26.md#s12d-result-before-local-search)).
- The synthetic `infeasible` preset is refuted by `cohort_load` with 0 search nodes ([evaluation
  § 1](evaluation-even-2025-26.md#1-algorithms)).
- Swapnali Kurhade's all-Tuesday absence is refuted by `faculty_load`: 16 periods in 13 ([repair
  § 1](repair-even-2025-26.md#1-swapnali-kurhade-unavailable-all-tuesday-cannot-be-repaired)).

## Independent validator

**What.** It re-checks every hard rule of a solved timetable from scratch: conflict edges over
every occupied period, faculty unavailability, pins, contiguity, lab blocks starting together,
fixed slots, then room occupancy with sub-room lockout, pinned rooms, capacity and room type. It
imports nothing from the search (`backtracking`, `colouring`, `graph`), so a bug in the search's
helpers cannot hide in it. A malformed input raises `ValueError` instead of reporting a
violation.

**Where.** `solver/validate.py`: `validate_solution`, plus `validate_slot_placements` for
slot-only results such as Welsh-Powell's.

**Complexity.** Time O(n log n + m·d + p + Σ c_t²), where c_t is the number of sessions in slot
t. The room-occupancy check compares the sessions that share a slot pairwise, which is O(n²·d)
in the worst case. Space O(n·d + p).

**Determinism.** Violations are returned in a fixed sort order.

**Course.** Software Engineering, as `validate.py`'s docstring says: an independent test oracle,
verification that shares no code with what it verifies.

**Measured.** 0 hard violations for every generated timetable reported. The printed timetable
has 36 time-only violations (26 FACULTY_CLASH, 10 PINNED_BLOCK) and cannot be room-checked,
because 58 of its sessions are in rooms outside the edge list ([evaluation §
3](evaluation-even-2025-26.md#3-real-generated-vs-printed-timetable)).

## YAML quality scoring

**What.** It scores a solved timetable against exactly the four D34 rules in
`solver/rules/quality_rules.yaml` (version "1"):

| Rule | What it measures | Weight |
|---|---|---|
| S-GAP | idle teaching periods inside a cohort's day | 2.0 |
| S-B2B | a teacher in two adjacent teaching periods | 1.0 |
| S-LOAD16 | teachers above 16 h a week | 1.0 |
| FAC_LOAD_IMBALANCE | each teacher's heaviest day minus lightest day | 0.5 |

`score = 100 − Σ weight × raw`, with one breakdown entry per rule. The weights are data, so a
department changes one without a code change, and `load_rules` refuses any other rule set.

**Where.** `solver/scoring.py`: `score`, `load_rules`, and the rule functions `_student_gaps`,
`_back_to_back`, `_load_above`, `_daily_load_spread`.

**Complexity.**

- S-GAP: O((C + m)·s). It unions each cohort's slots with those of the cohorts it shares
  students with, one per COHORT edge at most, then scans each day.
- S-B2B: O(F·s).
- FAC_LOAD_IMBALANCE: O(days·(n·d + p)), one count per day of the grid.
- S-LOAD16: O(F).
- The YAML file is read on every call.
- Space: O(C·s + n·d).

**Determinism.** Ids, days and periods are walked in sorted order, so the same timetable always
gets the same block, explanation text included.

**Course.** Hash sets and maps: Data Structures. The day's path of teaching periods for S-B2B:
DSGT. The range statistic for FAC_LOAD_IMBALANCE: Statistical Methods in Computer Science,
CE205. Configuration over code: Software Engineering.

**Measured.** Every score in the three docs. The committed timetable's 26.5 (since S14u)
against the printed 21.5, by rule: [real solve § S14u](real-solve-even-2025-26.md#s14u-both-d58-options-are-the-default-committed-result).
The earlier −15.0, by rule: [evaluation § 3](evaluation-even-2025-26.md#3-real-generated-vs-printed-timetable)
(re-run in S15e).

## Simulated-annealing `improve()`

**What.** A local search that moves only between valid timetables and lowers the scoring
penalty. Its three default moves:

- **relocate:** one session outside a lab block to another start and room;
- **swap:** the starts of two sessions that share a cohort or a teacher;
- **block:** a whole lab block to another start, trading places with what is in its way.

Every move goes through the backtracker's domain and `_placement_ok` checks. Pins, fixed
sessions and blocks holding one never move.

A move that does not raise the penalty is kept. A worse one is kept with probability
exp(−Δ/T), where Δ is the penalty increase and T cools geometrically from 10 to 0.3 over the budget. The best timetable seen
is returned, so the score never drops.

**Optional moves (D54, off by default).** With `extended_moves=True` it also proposes:

- **Kempe-chain interchanges:** the chain of conflict neighbours at two starts swaps between
  them;
- **gap-aimed moves:** a unit holding a cohort's students is sent onto that cohort's idle
  period, along a Kempe chain or by ejecting at most two sessions.

With the option off, no extra random number is drawn, so results are those of the three moves
alone.

**Where.** `solver/improve.py`: `improve`, `_Penalty` (incremental penalty). Constants:
`MAX_MOVES = 200_000`, `T_START`, `T_END`, `P_GAP`, `P_KEMPE`, `P_EJECT`, `KEMPE_MAX = 24`.

**Complexity.**

- Setup is O(n·s·r·d): static domains and penalty counts.
- Then k moves, each costing a local L:
  - the moved sessions (at most a block plus what is in its way; a Kempe chain at most 24) are
    checked over their periods against their neighbours and rooms;
  - only the touched (cohort, day), (teacher, day) and teacher penalties are recounted.
- A gap-aimed move also lists the current gaps, O(C × days).
- Total time O(n·s·r·d + k·L). Space O(n·s·r).

**Determinism.** One `random.Random(seed)`, and every choice is drawn from a sorted list.

- The docstring says a seed and a move budget fix the result "on any machine".
- It accepts moves with `math.exp` and cools with a float power. That they round identically on
  every platform is the docstring's claim, not something checked here.
- `solver/tests/test_improve.py` checks the off path against digests recorded before S12h,
  and checks that the extended path gives the same result under other string-hash seeds. Both
  were checked on one machine only ([real solve §
  S12h](real-solve-even-2025-26.md#s12h-kempe-chains-and-gap-aimed-moves-off-by-default)).
- `time_limit_s` is a safety cap: a run it stops depends on the machine.

**Course.** Simulated annealing and the guided and ejection moves: Design and Analysis of
Algorithms, the closest of the eight. They are heuristic optimisation over the same states the
backtracking searches; the docstrings say CE303. The acceptance rule exp(−Δ/T) draws from a
seeded random generator: Statistical Methods. Kempe-chain interchange: Discrete Structures and
Graph Theory. The incremental penalty's hash maps: Data Structures.

**Measured.**

- Real instance, committed parameters (1,000,000 moves, seed 0): −107.0 → 26.5 with sub-rooms
  first, the default since S14u (the committed `solution.json`, [real solve §
  S14u](real-solve-even-2025-26.md#s14u-both-d58-options-are-the-default-committed-result)).
  Before S14u, in id order: −162.5 → −15.0, and −18.5 at 200,000 moves ([real solve § S12g:
  the local search](real-solve-even-2025-26.md#s12g-the-local-search)).
- Extended against default, seeds 0–9: +1.85 [−5.81, +9.51] at 200,000 moves and +1.45 [−6.68,
  +9.58] at 1,000,000, so no measurable gain; it trades S-GAP for imbalance ([real solve §
  Comparison](real-solve-even-2025-26.md#comparison)).
- On the synthetic presets, `+ improve` drives S-GAP, S-B2B and S-LOAD16 to 0 at every size
  ([evaluation § 6](evaluation-even-2025-26.md#6-runtime-and-score-vs-size-s15c)).

## Freeze-and-expand repair

**What.** `repair()` takes the accepted timetable and one change. `apply_change` writes the
change into existing edge-list fields: an absence, a closed room, a drag, or a substitution.

- **Hit sessions:** sessions whose placement the change forbids, plus what stands in a drag's
  way. A lab block is hit whole.
- **Freeze and expand:** everything else is frozen, and only the hit sessions are re-placed by
  the backtracker. If that fails, the free set grows by one BFS ring (conflict neighbours and
  same room, same day) until every session is free.
- **After a success:** a greedy restore puts moved sessions back where they now fit, and
  `improve()` may move only the sessions that already moved.
- **Infeasible:** the result goes to `explain()`.
- **Drag onto a pin:** a drag onto a frozen pin is explained before any search.
- **Never relaxed:** protected pins (S14e) are never suggested as the relaxation.
- **Options, on by default since S14u (added in S14s, D58):** `prefer_sub_rooms` (as in
  backtracking) and `last_ring_portfolio`. With the portfolio, the every-session-free ring gets
  `RING_NODES`, then a second search with sub-rooms first and no preference for old places,
  before a timeout. `False` gives the pre-S14u behaviour. Measured in [repair §
  S14s](repair-even-2025-26.md#s14s-the-d58-options-in-repair-measured-off-by-default) and [repair §
  S14u](repair-even-2025-26.md#s14u-the-d58-options-are-the-default).

**Where.** `solver/repair.py`: `repair`, `apply_change`, `_in_the_way`, `_frozen_in_the_way`.
Constants: `RING_NODES = 5_000`, `MAX_MOVES = 20_000`.

**Complexity.**

- `apply_change` copies the payload: O(n + m).
- Each frozen ring is a backtracking search capped at `RING_NODES` nodes, and the free set grows
  every ring, so there are at most n rings.
- The last ring, with every session free, gets `RING_NODES` by default (`last_ring_portfolio`,
  S14u); its fallback search has no node cap. That fallback (and the last ring itself with the
  option off) is **exponential in the worst case** and stopped only by `time_limit_s`
  (`TimeoutError`, never infeasible). Since S14k that limit covers the whole call: the rings,
  the explanation and `improve()`.
- The restore pass repeats over the units until nothing improves, and the code gives no tighter
  bound on its number of passes.
- Space: O(n·s·r).

**Determinism.** Ring budgets are node counts, so without a time limit the result is the same
on every machine. A run that hits `time_limit_s` depends on the machine.

**Course.** Backtracking: Design and Analysis of Algorithms, CE207. Breadth-first search:
Discrete Structures and Graph Theory.

**Measured.**

- The six real scenarios moved 1–6 sessions or were shown impossible ([repair §
  Results](repair-even-2025-26.md#results); [evaluation §
  5](evaluation-even-2025-26.md#5-repair)).
- Over 19 changes solved both ways, repair moved 4.53 sessions [0.98, 8.07] and regeneration
  85.68 [80.45, 90.92].
- 6 of 30 repairs hit the 300 s limit in that run ([evaluation §
  7](evaluation-even-2025-26.md#7-repair-vs-regeneration-on-the-real-instance-s15c)).

## Minimal conflicting set and verified relaxations

**What.** `explain()` takes an infeasible result (a pre-solve certificate or an exhausted
search) and finds a small set of constraint groups that cannot hold together. A group is one
pin, one teacher's unavailable day, one fixed slot, one lab block, the clash edges per teacher
or cohort pair, one room's capacity or type, or the change itself.

- **Deletion filter.** Chunks are dropped while pre-solve still proves the rest infeasible,
  halving the chunk size each pass. Then every member is tried alone with a full check.
- **Checks.** A full check is pre-solve, then backtracking within `MUS_NODES = 300` nodes. A
  check that runs out is *unknown*, never feasible or infeasible.
- **Method.** With no unknown member the set is minimal (`mus`). Otherwise it goes out as
  `presolve` (proven, not minimal) if pre-solve proved it, else the input comes back unchanged.
- **Relaxations.** Each member's witness timetable suggests actions. They are tried smallest
  first, and the first whose re-solve passes `validate_solution` is the `suggested_relaxation`.
  The change itself and protected pins (S14e) are never relaxed. If nothing is verified, it is
  MANUAL.
- **Deadline (S14k).** `time_limit_s` stops the whole explanation where it is and returns that
  unfinished result.

**Where.** `solver/mus.py`: `explain`, `apply_action`, `_Problem` (`check`, `search`,
`candidates`).

**Complexity.**

- Groups: g = O(m + p + r + n) at most (493 on the real instance).
- The halving passes over the chunks add up to at most about 2g checks, so O(g) checks in all.
- First, each check tries the timetables it already knows, by validation only.
- After that it makes at most four solver calls: pre-solve alone (polynomial), two local repairs
  of a known timetable, then the whole instance, each search within `MUS_NODES` nodes.
- Relaxations: one verification per candidate action.
- Without the node budget each check is a backtracking search, so the extraction is
  **exponential in the worst case**. In practice it is bounded by `MUS_NODES` per search and,
  since S14k, by `time_limit_s` over the whole call.
- Space: O(n·s·r) per check, plus the kept witnesses.

**Determinism.** With no deadline, only node budgets apply, so the result is the same on every
machine. A result cut by a deadline can differ between machines, like a timeout. The verdict
(infeasible, by the same proof) does not.

**Course.** The deletion filter is Chinneck and Dravnieks 1991, with QuickXplain-style halving
(Junker 2004) and witnesses as in model rotation (Marques-Silva and Lynce 2011). Design and
Analysis of Algorithms, the closest of the eight: the halving is divide and conquer, and each
check is a bounded backtracking search. The docstring says CE303 (constraint satisfaction).

**Measured.**

- The drag onto SE-Comp A's frozen MDM-I lab gives `mus` {`pin.238`, the drag}, and the relaxation
  is verified `restored`, 2.40 s ([repair § Scenario 4](repair-even-2025-26.md#scenario-4-drag-onto-se-comp-as-frozen-mdm-i-lab)).
- Kurhade all Tuesday gives a 24-member set that is not proven minimal (one unknown), MANUAL,
  56.16 s ([repair § Scenario 1](repair-even-2025-26.md#scenario-1-swapnali-kurhade-unavailable-all-tuesday)).
- S15c's change 9, whose explanation ran over 20 minutes, now ends at its limit: 5.13 s at 5 s,
  15.03 s at 15 s, 30.53 s at 30 s ([repair §
  S14k](repair-even-2025-26.md#s14k-the-time-limit-covers-the-explanation)).
- Protected lunch pins: [repair § S14e](repair-even-2025-26.md#protected-pins-are-never-suggested).

## Substitution candidates

**What.** `substitute_candidates()` takes the faculty ids the caller says are qualified. D53:
SPIT's faculty–subject sheets decide that; the solver never does. It returns those under whom
the unchanged timetable still passes `validate_solution`, best score change first, ties by id.
The matching change, `substitute_faculty`, gives the session the new teacher and redraws its
FACULTY edges. The session keeps its slot unless the new teacher clashes there, and then it is
repaired as usual.

**Where.** `solver/repair.py`: `substitute_candidates`, and `apply_change` for
`substitute_faculty`.

**Complexity.** O(q·(n + m + V + S)): per qualified id, one payload copy with its edges redrawn,
one validation and one score. Space O(n + m).

**Determinism.** Sorted by (−score change, faculty id).

**Course.** "A filter, then a sort by key (Data Structures)" in its docstring.

**Measured.** On the real instance, as a mechanism check with the instance's own CE207 teachers
(not SPIT data). On the committed `solution.json` since S14u (the lecture at Thu P1, 701), only
Sudhir Dhage fits (−0.5). Nataasha Raul clashes, so substituting her moves only the lecture, to
Wed P0 (26.5 → 16.0, 0.34 s, ring 0). On the earlier `solution.json`: Prasenjit Bhavathankar
0.0 and Nataasha Raul −2.0 fit; Sudhir Dhage clashed, and substituting him moved only the
lecture (−15.0 → −27.0) ([repair § Substitutes](repair-even-2025-26.md#substitutes-d53)).

## Clique and load lower bounds

**What.** `lower_bounds()` computes how many teaching periods the week must hold at least.

- **Clique bound:** the heaviest clique of pairwise-conflicting sessions, each weighted by the
  periods it occupies, since the sessions of a clique need different periods. It is found by
  branch and bound within `EXACT_NODES = 200_000` nodes, else by the best greedy clique, and
  `method` says which.
- **Load bounds:** the heaviest teacher (session periods plus pinned or unavailable teaching
  slots) and the heaviest cohort (session periods plus pinned teaching slots).

It solves nothing, and no pipeline calls it.

**Where.** `solver/bounds.py`: `lower_bounds`, `_exact`, `_greedy`.

**Complexity.**

- The exact clique search is **exponential in the worst case**, at most 2^n nodes, and is capped
  at `EXACT_NODES`. Each node filters its candidate list in O(n).
- The greedy fallback is O(n²·ω), with ω its clique size.
- The loads are O(n + p + u).
- Space: O(n + m).

**Determinism.** Vertices are ordered by (−weight, id), and the budget is a node count, not a
clock. A test checks that the result is the same with sessions and edges shuffled.

**Course.** Clique number ≤ chromatic number: Discrete Structures and Graph Theory. Branch and
bound: Design and Analysis of Algorithms. Counting over hash maps: Data Structures.

**Measured.** Real instance, 0.008 s ([real solve §
S12i](real-solve-even-2025-26.md#s12i-lower-bounds-on-the-periods-a-week-needs)):

- exact clique of 18 periods, against 40 per year;
- heaviest teacher load 25, against 45 teaching slots;
- heaviest cohort load 41 (SE-Comp C, 5 of its pins being lunch), against 45.

## Limits and honest caveats

- **No algorithm here proves the score optimal.**
  - Backtracking proves feasibility or infeasibility, not quality.
  - `improve()` is a heuristic: it returns the best timetable it saw, not the best one there is.
  - The lower bounds are about periods, not about the score.
- **The generated timetable beats the printed one on soft rules only since S14u, on one seed.**
  The committed `solution.json` scores 26.5 against the printed timetable's 21.5 (S-GAP 1 raw
  against 2). It has 0 hard violations; the printed one has 36 against this edge list (26
  FACULTY_CLASH, 10 PINNED_BLOCK) ([real solve §
  S14u](real-solve-even-2025-26.md#s14u-both-d58-options-are-the-default-committed-result)).
  At 200,000 moves, seeds 0–4 average 12.9, below 21.5 ([real solve §
  S14s](real-solve-even-2025-26.md#s14s-prefer_sub_rooms-now-an-option-off-by-default)).
  - Before S14u, in id room order, it scored −15.0 and S-GAP blocked it: its lowest value in the
    S12h runs is 7 raw ([real solve § S12h](real-solve-even-2025-26.md#s12h-kempe-chains-and-gap-aimed-moves-off-by-default)).
    S12g put the remaining gaps down to frozen items (D24); D58 showed the room order held most
    of them ([real solve § D58](real-solve-even-2025-26.md#d58-what-preferring-sub-rooms-would-change-measured-not-adopted)).
  - Each room order has instances it thrashes on. Sub-rooms first alone could not finish a fresh
    solve after one feasible substitution that the id order solves in 92 nodes. A fresh solve
    therefore tries rooms by id after 5,000 nodes: 1.79 s for that case ([real solve §
    S14u](real-solve-even-2025-26.md#fixed-a-fresh-solve-tries-rooms-by-id-when-sub-rooms-first-runs-out-of-nodes)).
- **Repair minimises moves heuristically.** No search proves that fewer moves are impossible.
  Its last ring can run until `time_limit_s`, and 6 of 30 changes did so in S15c ([evaluation §
  7](evaluation-even-2025-26.md#7-repair-vs-regeneration-on-the-real-instance-s15c)).
- **Wall-clock limits make results machine-dependent.**
  - Backtracking's `time_limit_s` can turn `solved` into `timeout` on a slower machine.
  - `improve()`'s cap can stop it early.
  - A repair or an explanation cut by its deadline (S14k) can differ between machines.
  - Node and move budgets do not have this problem. Without a wall-clock limit, every result is
    fixed by its inputs and seed.
- **Not proven minimal is reported as such.** `solution.v2` has no `method` for "proven by
  search, not minimal", so such a set falls back to `presolve` or to the input
  diagnosis ([repair § Open questions](repair-even-2025-26.md#open-questions)).
- **Complexities are from reading the code, not measured.** Where the code gives no tighter bound
  (repair's restore passes), this document says so. The measured runtimes are in the three
  linked docs, each on the machine it names.
