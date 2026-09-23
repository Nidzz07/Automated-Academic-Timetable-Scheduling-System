# CONTEXT.md — Chronos

> **Read this file at the start of every session before writing code.**
> It describes what the system is, the rules that must never be broken, and what the
> real institutional data actually looks like. It changes rarely.
> For *what to build next*, read `ROADMAP.md`. For *what is done*, read `CURRENT-PROGRESS.md`.

---

## 1. What this project is

**Chronos** is an explainable, constraint-based academic timetable scheduling system built as a
B.Tech mini project at Sardar Patel Institute of Technology, Department of Computer Engineering.

It generates conflict-free weekly timetables from real institutional constraint data by reducing
the problem to **graph vertex colouring**, and it does two things existing tools (FET, aSc
TimeTables, UniTime) do not:

1. **Infeasibility diagnosis** — when no valid timetable exists, it extracts the minimal
   unsatisfiable subset of constraints and names the smallest relaxation that restores
   feasibility, instead of reporting a bare failure.
2. **Live rescheduling** — when a faculty member is absent, it substitutes a qualified teacher
   who is free in that slot, recalculates both workloads, and updates both individual
   timetables. When no substitution exists, a freeze-and-expand repair re-solves only the
   affected neighbourhood rather than regenerating the whole timetable.

**Team and ownership**

| Member | Owns | Directories |
|---|---|---|
| Rohan Shashikant Dhumal | Solver core and algorithms | `solver/` |
| Nidhi Rajkamal Dhyani | Backend, data layer, ingestion | `backend/`, `ingestion/`, `db/` |
| Dhruv Hemant Gangurde | Frontend and validation | `frontend/`, `tests/e2e/`, `bench/` |

Supervisor: Mr. Devang Parab.

---

## 2. Non-negotiable rules

These are architectural constraints, not preferences. Breaking one invalidates the project's
academic claim.

1. **No machine learning anywhere in the decision path.** No component that generates,
   validates, diagnoses, repairs or scores a timetable may use a learned model. Identical input
   must always produce identical output. Explainability is the contribution; a learned heuristic
   destroys it. (Reference [16] in the literature review solves the same problem with
   reinforcement learning — we explicitly reject that route.)

2. **Solver purity.** Nothing under `solver/` may import a web framework, an ORM, or a database
   driver. It accepts plain Python data structures and returns plain Python data structures. If
   you find yourself writing `from sqlalchemy import ...` inside `solver/`, stop — the data
   belongs in the edge-list contract instead.

3. **Hand-written algorithms.** Colouring, backtracking, MUS extraction and repair are
   implemented in this project. `networkx` may be used **only** for validation and baseline
   comparison in tests — never in the production path.

4. **Quality rules are data, not code.** Scoring rules and weights live in a versioned YAML file.
   A department must be able to change a weight without a code change.

5. **Multi-department by design.** Rooms belong to the **institute**, not a department — the real
   data shows CE using CSE rooms (`509 new CSE`, `403-B`) and running combined CSE+CE lectures.
   Every entity carries department scoping so CE, CSE and EXTC can coexist later. We build and
   demo **CE only**, but the schema must not need a migration to add another department.

6. **Traceability.** Each major design decision must map to a foundational course: DSGT, DAA,
   Data Structures, DBMS, OS, OOP, Statistical Methods, Software Engineering.

---

## 3. The real data — read this before modelling anything

Source files live in `data/real/` (committed, read-only):

| File | Content |
|---|---|
| `CE_Class_Time_Table-EVEN_sem_25-26.docx` | Division-wise class timetables, EVEN semester |
| `CE_Class_Time_Table-ODD_sem_25-26.docx` | Division-wise class timetables, ODD semester |
| `Lab_CE_Time_Table-Even_sem_25-26.docx` | Room-wise lab timetables with utilisation % |
| `Faculty_Individual_timetable_Even_2025-26.docx` | Per-faculty timetables and T/P workloads |
| `classrooms.xlsx` | Room inventory with capacity and separation |

### 3.1 Scale

| Dimension | Value |
|---|---|
| Teaching slots | 8 per day × 5 days = **40 per week** |
| Division-groups | SE A–D, TE A–D, BE A&B, M.Tech = **10** (EVEN), 9 (ODD) |
| Batches | 4 per division (A/B/C/D) → **~40** |
| Faculty | **32**, workloads 5–18 hours |
| Rooms | **20 physical**, ~35 usable once sub-rooms are counted |
| Sessions | roughly 180–250 per week per semester |

### 3.2 Slot grid

```
09.00–10.00   teaching
10.00–11.00   teaching
11.00–11.15   SHORT BREAK      (not schedulable)
11.15–12.15   teaching
12.15–13.15   teaching
13.15–14.15   BREAK            (not schedulable)
14.15–15.15   teaching
15.15–16.15   teaching
16.15–17.15   teaching
17.15–18.15   teaching
```

Note: some lab blocks span the short break (`ET Lab /DDA /509 (10.00 -12.00)`). Slot adjacency
must be computed on the **teaching sequence**, not on wall-clock contiguity.

### 3.3 Cell notation — differs per source file

There is no single format. Each parser needs its own field-order rule.

| Source | Format | Example |
|---|---|---|
| Class TT (SE/TE theory) | `SUBJECT / FACULTY / ROOM` | `OS / KKD / 002` |
| Class TT (SE/TE lab) | `SUBJECT / BATCH / FACULTY / ROOM` | `OS / A / AGN / 702-A` |
| Class TT (BE) | `SUBJECT / BATCH / ROOM / FACULTY` | `HPC / A /703-B /JR` |
| Faculty TT | `SUBJECT / BATCH / DIVISION / ROOM` | `DAA / C / SE-C /702-C` |
| Lab TT | `SUBJECT / BATCH / FACULTY DIVISION (room)` | `PCS / D / SD SE COMP B (601)` |

### 3.4 Structural facts the model must support

**Rooms subdivide.** `classrooms.xlsx` carries a `separation` column: room 603 is `20-20-20`,
606 is `20-20`, 702 is `20-20-20`. Timetables then reference `603-2`, `702-A`, `606-4`, `703-B`.
A `Room` therefore owns zero or more `SubRoom`s, and two labs can occupy one physical room at
the same time in different sub-rooms.

**Labs are batch-parallel blocks.** One lab slot holds four simultaneous sessions — four batches
of one division, four different subjects, four faculty, four rooms:

```
OS  / A / AGN / 702-A      DAA / B / NR  / 603-2
CCN / C / JS  / 606-4      PCS / D / DN  / 608
```

and the identical content repeats in the next slot (double period). Model this as a `LabBlock`
that owns N parallel `Session`s with a contiguity constraint — not as N independent sessions.

**Workload is theory/practical weighted.** Every faculty page ends with a line like `6T+ 8P =14`
or `4T+12P=16`. The department's own metric separates theory from practical hours. Load
balancing and substitution ordering must use this weighting, not a raw session count.

**Combined divisions are common.** `DAA / SE C & D / 508` is one lecture for two divisions in one
room. Model as a single vertex over the union cohort.

**Elective cohorts span divisions.** `PE-I-D`, `PE-II-A` … `PE-II-G` appear where a batch label
would otherwise go. These are cross-division student groups with their own membership.

**Cross-department sessions exist.** `HMI /A /412 / DRK (CSE+CE)` is a combined CSE + CE lecture.
Rooms in other departments are used (`509 new CSE`).

**Pinned blocks are immovable.** `MDM - I LABs`, `MDM -I THEORY`, `HSS`, `HSS II`, `LLC`,
`STUDENT ACTIVITY`, `Major Project`, and both breaks occupy slots but are not scheduled by the
solver. They enter as fixed constraints.

**Exam blocks appear in lab timetables.** `DAA LAB EXAM ESE SE COMP NR` occupies lab slots.

### 3.5 Known data-quality defects — do not silently "fix" these

The ingestion layer must **report** anomalies, not paper over them. A viva question will
certainly touch on this.

- Room `507` appears twice in `classrooms.xlsx`: capacity 160 marked `class`, and capacity 20
  marked `as a lab`.
- Rooms `605` and `609` have `used as` = `unsure`.
- Sub-room references exceed declared separation: `603-7` and `606-4` are referenced, but 603
  declares 3 sub-rooms and 606 declares 2.
- Sub-room naming is inconsistent — letters (`702-A`) and digits (`603-2`) both appear.
- Faculty appear by initials in class timetables (`KKD`, `AGN`, `PBB`) but by full name in the
  faculty file. An initials→name mapping must be derived and verified, not guessed.

### 3.6 A free validation target

`Lab_CE_Time_Table-Even_sem_25-26.docx` already states, per room, a figure such as
`Lab Utilization in %= 24/30= 80.00 %`. Once ingestion works, the system should reproduce those
percentages from the parsed data. Matching them is proof the parser is correct.

---

## 4. Domain model

```
Institute
└── Department            (CE, CSE, EXTC — only CE populated)
    └── Programme         (B.Tech, M.Tech)
        └── Semester      (III, IV, V, VI, VII, VIII, M.Tech I/II)
            └── Division  (SE-Comp A … M.Tech Comp)
                └── Batch (A, B, C, D)

Room  (institute-level, shared across departments)
└── SubRoom               (derived from the separation column)

Faculty      → Department (owner), schedulable institute-wide
Subject      → Department, carries session_type (theory | lab | both)
Qualification: Faculty ↔ Subject, many-to-many  [drives substitution]

Cohort       polymorphic: Division | Batch | ElectiveGroup | CombinedDivisions
Session      → Cohort, Subject, Faculty, Room|SubRoom, Slot, duration
LabBlock     → owns N parallel Sessions + contiguity constraint
PinnedBlock  → immovable occupancy (MDM, HSS, LLC, breaks, exams)
Timetable    → owns Sessions, carries status and quality score
AbsenceRecord→ faculty, slot, date, replacement
AuditEntry   → actor, action, timestamp, affected sessions
```

`Session` is the hub — it is the vertex the solver colours.

---

## 5. The three frozen contracts

These are the only coupling points between the three tracks. **Changing one requires agreement
from all three members** and a note in `CURRENT-PROGRESS.md` under Decision Log.

1. **Ingestion → DB** — the canonical intermediate JSON that parsers emit and the seeder consumes.
2. **DB → Solver (edge-list contract)** — session records plus conflict edges with a reason on
   each edge. Plain data structures only, no ORM objects.
3. **Solver → API (JSON solution contract)** — either a complete assignment with an itemised
   quality breakdown, or an infeasibility result carrying the minimal conflicting subset and a
   suggested relaxation.

Schemas live in `contracts/` as JSON Schema files with example payloads. Both sides validate
against them in tests.

---

## 6. Tech stack

| Layer | Technology |
|---|---|
| Solver | Python 3.12, stdlib only (`heapq`, `dataclasses`); `networkx` in tests only |
| Ingestion | `python-docx`, `openpyxl`, Pydantic validation |
| Backend | FastAPI, Pydantic, Uvicorn, SQLAlchemy 2.0, Alembic |
| Auth | `python-jose` (JWT), `passlib[bcrypt]` |
| Database | PostgreSQL 16 — local via Docker Compose for development and migrations; Supabase for shared staging |
| Frontend | React 18, Vite, TypeScript, TailwindCSS, shadcn/ui, dnd-kit, TanStack Query, Recharts |
| Testing | pytest, pytest-cov, Hypothesis, httpx, Vitest, React Testing Library |
| Ops | Docker, Git, GitHub Actions, Render or Railway |

---

## 7. Repository layout

```
chronos/
├── CONTEXT.md                  this file
├── ROADMAP.md                  the phased plan
├── CURRENT-PROGRESS.md         living status, updated after every work session
├── CLAUDE.md                   agent rules (mirrors section 2)
├── contracts/                  the three frozen JSON Schemas + examples
├── data/real/                  source .docx and .xlsx, read-only
├── ingestion/                  parsers, anomaly reporter, seeder      [Nidhi]
├── db/                         schema, Alembic migrations             [Nidhi]
├── backend/                    FastAPI app, routers, auth, services   [Nidhi]
├── solver/                     pure Python solver core                [Rohan]
│   ├── graph.py                conflict graph construction
│   ├── colouring.py            Welsh-Powell greedy
│   ├── backtracking.py         forward checking + MRV
│   ├── mus.py                  minimal unsatisfiable subset
│   ├── repair.py               freeze-and-expand
│   ├── scoring.py              YAML rule evaluation
│   └── rules/quality_rules.yaml
├── frontend/                   React app                              [Dhruv]
├── tests/                      unit, property, integration, e2e
├── bench/                      benchmark harness and plots            [Dhruv]
└── docs/                       SRS, UML, reports
```

---

## 8. Notation glossary

| Token | Meaning |
|---|---|
| `SE`, `TE`, `BE` | Second / Third / Fourth year B.Tech |
| `SE-Comp A` | Second year Computer Engineering, division A |
| `A`/`B`/`C`/`D` after a subject | Batch within a division (lab context) |
| `PE-I-D`, `PE-II-A` | Professional elective cohort |
| `702-A`, `603-2` | Sub-room within a separable room |
| `6T+8P=14` | 6 theory hours + 8 practical hours = 14 total workload |
| `KKD`, `AGN`, `PBB` | Faculty initials used in class timetables |
| `MDM`, `HSS`, `LLC` | Multidisciplinary Minor, Humanities, Liberal Learning — pinned blocks |
| `ESE` | End Semester Examination |
