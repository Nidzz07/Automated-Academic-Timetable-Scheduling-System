# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read it fully before making changes.

## Current repo state

**The directory skeleton exists, but it is empty of logic.** `main` carries scaffolding and planning commits only — no application code has been written yet. `solver/`, `backend/`, `data/`, `ingestion/`, `db/`, and `frontend/` exist with `__init__.py` / placeholder files only. Do not assume a module exists because it is named below; check first. `CURRENT-STATUS.md` is the verified file-by-file inventory.

Practical consequences:

- `backend/app/main.py` holds a bare `FastAPI()` instance with **no routes**. `solver/tests/` and `backend/tests/` are empty — pytest collects zero tests.
- `frontend/` is an empty placeholder — **no `package.json`**, so every `npm` command below fails until it is scaffolded (`npm create vite@latest . -- --template react-ts`).
- There is **no `alembic.ini`** and no `migrations/` yet; Alembic must be initialised before the migration commands work.
- The venv is **Python 3.12.10** on Windows, and all of `requirements.txt` is already installed.

## Project

**Chronos** is an explainable, constraint-based academic timetable scheduling system. It generates conflict-free timetables from institutional constraints, and — unlike existing tools (FET, aSc, UniTime) — it does two novel things:

1. **Infeasibility diagnosis** — when no valid timetable exists, it extracts the minimal unsatisfiable constraint subset (MUS) and suggests the smallest relaxation to restore feasibility.
2. **Minimal-disruption rescheduling** — when a constraint changes mid-semester (e.g. a faculty absence), it re-solves only the affected neighbourhood (freeze-and-expand heuristic), displacing as few existing sessions as possible.

This is a university mini-project. Every major design decision must trace to a core CS course: DSGT, DAA, Data Structures, DBMS, OS, OOP, Statistical Methods, Software Engineering. Keep that traceability intact — do not introduce techniques that can't be justified against those courses.

## Non-negotiable constraints

- **NO machine learning anywhere in the decision path.** The solver is deterministic and explainable by design. That determinism is what makes infeasibility diagnosis and quality scoring meaningful. Do not add learned heuristics, ML models, or LLM calls into solving, scoring, or repair. If a natural-language constraint-entry feature is ever added, it is a *pure input adapter only* — the parsed output must be shown for human confirmation before the solver touches it, and the solver stays 100% deterministic.
- **The solver core (`solver/`) is the graded intellectual artifact.** Keep it hand-written and framework-free. It must import no web/DB frameworks. `networkx` is permitted for validation and baseline-colouring comparison ONLY — the actual colouring, backtracking, MUS extraction, and repair logic are written by hand.
- **Explainability over cleverness.** Prefer readable, defensible algorithms the team can explain in a viva over opaque optimisations.
- **Never invent institutional data.** Use the synthetic generator or provided real data. Don't hardcode fake courses/rooms into logic.

## Architecture

```
chronos/
├── contracts/    The three frozen JSON Schemas + example payloads in examples/.
├── solver/       Pure Python. Conflict graph, colouring, backtracking, MUS, repair. NO framework imports.
│   └── rules/    quality_rules.yaml — scoring rules are data, not code.
├── ingestion/    Parsers for the real .docx/.xlsx sources, anomaly reporter, seeder.
├── db/           SQLAlchemy schema + Alembic migrations.
├── backend/      FastAPI + SQLAlchemy + Alembic. Endpoints, auth, integration with solver.
├── frontend/     React 18 + Vite + TypeScript. Timetable grid, drag-and-drop, role views, charts.
├── data/         real/ (committed source files, read-only), reference/ (derived lookups),
│                 synthetic dataset generator (Faker) + sample instances in instances/.
├── tests/        Cross-cutting tests; contracts/ validates each example against its schema.
├── bench/        Benchmark harness and plots.
├── docs/         SRS, UML, reports.
└── docker-compose.yml
```

See `CONTEXT.md` §7 for the authoritative layout and `CURRENT-STATUS.md` for what is actually
populated today — most of the above is still an empty directory.

Data flow: DB (normalised hierarchy) → constraint-derivation queries produce conflict edges → `solver` builds the graph and colours it → backend serves timetables via API → frontend renders role-differentiated views and allows server-validated drag-and-drop edits.

## Tech stack

- **Solver:** Python 3.12 (the local venv is 3.12.10), stdlib (`heapq`, `dataclasses`), `networkx` (validation/baseline only).
- **Backend:** FastAPI, Pydantic, Uvicorn, SQLAlchemy 2.0, Alembic, `python-jose` + `passlib[bcrypt]` for JWT + role-based auth.
- **Database:** PostgreSQL 16. **Local Postgres (the `db` service in `docker-compose.yml`) is the default for development and migrations**; hosted **Supabase Postgres** is shared staging only. Normalised to 3NF — document the decomposition. Connection string comes from `DATABASE_URL` in `backend/.env`; never hardcode it.
- **Frontend:** React 18, Vite, TypeScript, TailwindCSS, shadcn/ui (use these components; don't hand-roll), dnd-kit (drag-and-drop), TanStack Query (server state), Recharts (score/benchmark plots), lucide-react (icons).
- **Testing:** pytest + Hypothesis (property-based) and Faker on the Python side; Vitest + React Testing Library on the frontend.
- **Ops:** Docker Compose runs the **backend plus a local `postgres:16` database**; Render/Railway + Supabase for deployment; GitHub Actions to run tests on push.

> **Shared-database warning.** Develop and migrate against the **local** compose database — it is throwaway, and three people running Alembic against one hosted instance corrupt each other's schema state. Point `DATABASE_URL` at Supabase only when deliberately promoting a migration to shared staging, and coordinate with the team first. `alembic upgrade head`, `alembic downgrade`, and the synthetic data generator all affect everyone when aimed at Supabase; never point destructive operations or test fixtures at it.

## Conventions

- **Solver purity:** anything in `solver/` must be unit-testable in isolation with no DB or network. If a function needs DB data, it takes plain Python objects/edge-lists as arguments — it does not query.
- **Contracts:** the solver ↔ backend boundary is a defined edge-list / JSON contract. Do not change it casually; it is a team handoff point. Flag any proposed change.
- **Types:** use `dataclasses` and type hints in Python; strict TypeScript on the frontend (no `any`).
- **Naming:** entities follow the domain model — Department, Division, Batch, Faculty, Room, Session, Cohort. Use these names consistently across DB, solver, and API.
- **DB changes go through Alembic migrations.** Never edit the schema out of band.
- **Frontend components:** compose from shadcn/ui primitives + Tailwind utilities. Keep the UI professional and consistent.

## Testing requirements

- Every generated timetable must be conflict-free. There is a **Hypothesis property test asserting this over randomised instances** — it must always pass. If a change could affect solver output, run it.
- Cover edge cases explicitly: empty input, single session, and deliberately infeasible constraint sets (the last must produce a diagnosis, not a crash).
- Don't merge solver changes without the solver test suite green.

## Common commands

Dev shell here is **PowerShell on Windows**. Everything below runs from the repo root unless noted.

```powershell
# Activate the venv (already provisioned with all of requirements.txt)
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt        # only after adding a dependency

# Tests
pytest solver/tests                    # solver unit + property tests
pytest backend/tests                   # API integration tests
pytest solver/tests/test_colouring.py                      # single file
pytest solver/tests/test_colouring.py::test_no_conflicts   # single test
pytest -k "mus and not repair"         # by name substring
pytest --cov=solver --cov-report=term-missing              # coverage
pytest --hypothesis-show-statistics    # property-test shrink/coverage detail

# Backend
alembic revision --autogenerate -m "message"   # create a migration
alembic upgrade head                           # apply migrations
uvicorn backend.app.main:app --reload          # API at :8000, docs at /docs
```

Docker Compose runs the backend plus a local `postgres:16` database. The backend reads `backend/.env` and waits for the database's healthcheck before starting.

```powershell
docker compose up --build      # backend on :8000, talking to Supabase
```

Not yet usable — requires scaffolding that does not exist:

```powershell
cd frontend; npm install; npm run dev    # needs frontend/package.json
alembic upgrade head                     # needs alembic init
```

If a venv executable is not on `PATH`, call it directly: `.\.venv\Scripts\pytest.exe`, `.\.venv\Scripts\alembic.exe`.

## Module ownership (respect these boundaries)

- **Rohan — `solver/`:** conflict graph, greedy colouring, backtracking + forward checking + MRV, MUS extraction, freeze-and-expand repair, complexity analysis. (DSGT, DAA, Data Structures)
- **Nidhi — `backend/` + `data/`:** 3NF schema, Alembic migrations, constraint-derivation queries, FastAPI endpoints, JWT/role auth, repair audit log, synthetic generator. (DBMS, OS, Software Engineering)
- **Dhruv — `frontend/` + validation:** React grid, drag-and-drop editing, role-based views, frontend tests, benchmark harness, report plots. (OOP, Statistical Methods, Software Engineering)

When a task spans boundaries (notably the repair feature), call it out rather than silently editing another member's vertical.

## When unsure

Prefer asking over guessing on: schema/contract changes, anything touching the solver's determinism, and anything that would add a dependency. Keep changes small and traceable to a course concept.