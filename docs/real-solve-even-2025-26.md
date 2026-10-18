# First solve of the real EVEN 2025-26 SE+TE instance (S12a)

Date: 2026-10-18 · Track A · reproduce with `python -m solver.benchmarks.real_solve`
(on a timeout it writes nothing; `solver/tests/test_real_solve.py` re-runs it, marked `slow`).

**Outcome: timeout.** Backtracking ran out of its 300 s budget without a timetable or a proof
of infeasibility. Under ROADMAP D33 a timeout is a job status, not a solution, so
`data/instances/even-2025-26/solution.json` is **not written** and there is no quality score.

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

## Result

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

## What this does and does not say

- It does **not** say the instance is infeasible: no pre-solve certificate, no exhausted search.
- It does say the observed EVEN week is very tight once the frozen items (D24, D26, D44) and each
  year's lunch (D6) are pinned: SE cohorts keep 4–5 periods of slack in the week, and Swapnali
  Kurhade 2.
- Names in this report come from `data/instances/even-2025-26/display.json` (D41); the solver
  itself sees only ids.
