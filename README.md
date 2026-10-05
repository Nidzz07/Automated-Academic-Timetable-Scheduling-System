# Chronos

**Chronos** is an explainable, constraint-based academic timetable scheduler, built as a B.Tech
mini project for the Department of Computer Engineering, Sardar Patel Institute of Technology.

It reduces timetabling to **graph vertex colouring** over a conflict graph (faculty, room and
cohort clashes) and solves it with hand-written greedy colouring and backtracking search. It
targets two things existing tools (FET, aSc TimeTables, UniTime) do not offer:

1. **Infeasibility diagnosis.** When no valid timetable exists, it reports the minimal set of
   conflicting constraints and the smallest relaxation that would restore feasibility.
2. **Live rescheduling.** When a faculty member is absent, it finds a qualified, free substitute.
   If there is none, it repairs only the affected neighbourhood of the timetable.

The solver is fully deterministic. There is no machine learning anywhere in the decision path.

> **Status:** work in progress. The core solver, the database schema and the frontend shell
> exist. Real-data ingestion, the API, quality scoring and both novelty features are not built
> yet. See [`docs/CURRENT-PROGRESS.md`](docs/CURRENT-PROGRESS.md) for the current state.

## Tracks

| Track | Owner | Scope | Directories |
|---|---|---|---|
| A — Solver | Rohan | conflict graph, colouring, backtracking, MUS, repair, scoring | `solver/` |
| B — Data & Backend | Nidhi | schema, migrations, ingestion of the real .docx/.xlsx files, API | `db/`, `migrations/`, `ingestion/`, `backend/` |
| C — Frontend & Validation | Dhruv | timetable UI, role views, frontend tests, benchmarks | `frontend/`, `bench/` |

The tracks meet only at the three frozen JSON contracts in [`contracts/`](contracts/):
ingestion → DB, DB → solver (edge list), and solver → API (solution).

## Repository layout

```
contracts/    frozen JSON Schemas + example payloads
solver/       pure-Python solver core (stdlib only)
db/           SQLAlchemy models          migrations/  Alembic revisions
ingestion/    parsers and seeders for data/real/
backend/      FastAPI app (scaffold)     frontend/    React + Vite + TypeScript
tests/        cross-cutting tests (contract validation)
data/real/    the department's source timetables and spreadsheets (read-only)
docs/         context, progress, proposals
```

## Prerequisites

- **Python 3.12.** CI runs 3.12. On Windows, a plain `python` may be a different version, so
  create the venv with `py -3.12`.
- **Docker** with Compose, for the local PostgreSQL 16 database.
- **Node.js LTS** and npm, for the frontend.

## Setup

The local database is the `db` service in `docker-compose.yml`. Its user, password and database
name are all `chronos`. The host port comes from `CHRONOS_DB_PORT` and defaults to 5432.

If a native PostgreSQL already uses 5432, pick another port (the examples use `55432`). Use the
same port for Compose, the tests and Alembic.

### Windows (cmd)

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt

rem Backend config. Copy it only if backend\.env does not exist yet.
copy .env.example backend\.env

rem Local Postgres. Skip the first line if 5432 is free.
set CHRONOS_DB_PORT=55432
docker compose up db -d

rem Point Alembic at the local database.
set DATABASE_URL=postgresql+psycopg2://chronos:chronos@localhost:%CHRONOS_DB_PORT%/chronos
alembic upgrade head
```

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Backend config. Copy it only if backend/.env does not exist yet.
cp -n .env.example backend/.env

# Local Postgres. Skip the export if 5432 is free.
export CHRONOS_DB_PORT=55432
docker compose up db -d

# Point Alembic at the local database.
export DATABASE_URL="postgresql+psycopg2://chronos:chronos@localhost:${CHRONOS_DB_PORT:-5432}/chronos"
alembic upgrade head
```

`backend/.env` is gitignored. Never commit real credentials.

## Running things

Run everything from the repo root with the venv active.

### Tests

```bash
pytest -q -rs                          # full Python suite; -rs prints skip reasons
pytest solver/tests                    # solver only
pytest solver/tests/test_backtracking.py::TestLabBlock
```

**DB-backed tests** (`db/tests`, `ingestion/tests/test_seed_*.py`) connect as follows:
- They use `CHRONOS_TEST_DATABASE_URL` if it is set.
- Otherwise they use `postgresql+psycopg2://chronos:chronos@127.0.0.1:$CHRONOS_DB_PORT/chronos`.
- They create and drop their own scratch databases.
- They refuse to run against any non-local host.
- They **skip** when Postgres is unreachable, so check the skip list from `-rs`.

### Lint

```bash
ruff check .
```

The configuration is in `pyproject.toml`.

### Migrations (Alembic)

```bash
alembic upgrade head      # current head: 0004_faculty_initials
alembic current
alembic revision --autogenerate -m "describe the change"
```

`migrations/env.py` reads `DATABASE_URL` from the environment first, then from `backend/.env`.

It **refuses to migrate a non-local database** unless `CHRONOS_ALLOW_REMOTE_DB=1` is set. The
hosted Supabase instance is shared staging for the whole team. Only promote a reviewed migration
there deliberately, after agreeing it with the team.

### Frontend

```bash
cd frontend
npm ci              # install exactly what package-lock.json pins
npm test            # vitest run
npm run build       # tsc type-check + vite production build
npm run dev         # dev server
```

The frontend currently runs against contract example fixtures and a mock API client. It is not
connected to a backend yet. `package.json` has no `lint` script.

### Backend

```bash
uvicorn backend.app.main:app --reload    # http://localhost:8000/docs
```

This is a scaffold: there are no routes yet.

## Documentation

- [`docs/CONTEXT.md`](docs/CONTEXT.md) covers what the system is, the non-negotiable rules, the
  real data, and the domain model.
- [`ROADMAP.md`](ROADMAP.md) is the phased plan and the parallel-work protocol.
- [`docs/CURRENT-PROGRESS.md`](docs/CURRENT-PROGRESS.md) tracks what is done, blockers, the
  decision log and the contract change log.
- [`docs/contract-change-proposal-v2.md`](docs/contract-change-proposal-v2.md) is the proposed v2
  contract changes. It is not yet signed.
- [`CLAUDE.md`](CLAUDE.md) holds the rules for coding agents working in this repo.
