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

> **Status:** work in progress. The solver, real-data ingestion, the API, quality scoring,
> diagnosis and repair, the frontend and the evaluation are on `main`; deployment and the final
> report are open. See [`docs/CURRENT-PROGRESS.md`](docs/CURRENT-PROGRESS.md) for the current state.

## Tracks

| Track | Owner | Scope | Directories |
|---|---|---|---|
| A — Solver | Dhruv | conflict graph, colouring, backtracking, MUS, repair, scoring | `solver/` |
| B — Data & Backend | Nidhi | schema, migrations, ingestion of the real .docx/.xlsx files, API | `db/`, `migrations/`, `ingestion/`, `backend/` |
| C — Frontend & Validation | Rohan | timetable UI, role views, frontend tests, benchmarks | `frontend/`, `bench/` |

The tracks meet only at the three frozen JSON contracts in [`contracts/`](contracts/):
ingestion → DB, DB → solver (edge list), and solver → API (solution).

## Repository layout

```
contracts/    frozen JSON Schemas + example payloads
solver/       pure-Python solver core (stdlib only)
db/           SQLAlchemy models          migrations/  Alembic revisions
ingestion/    parsers and seeders for data/real/
backend/      FastAPI app                frontend/    React + Vite + TypeScript
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

## Run locally on Windows (PowerShell)

From the repo root. First terminal:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Local Postgres. Use "5432" if no native PostgreSQL owns that port.
$env:CHRONOS_DB_PORT = "55432"
docker compose up db -d

# This shell only; or put both in backend\.env (see .env.example).
$env:DATABASE_URL = "postgresql+psycopg2://chronos:chronos@localhost:$env:CHRONOS_DB_PORT/chronos"
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
alembic upgrade head

# Demo accounts demo-admin, demo-coordinator, demo-faculty, demo-student (typed, not echoed).
$env:CHRONOS_DEMO_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Demo password')).Password
python -m backend.app.demo_seed

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Second terminal (the dev server proxies `/api` to port 8000):

```powershell
cd frontend; npm ci; npm run dev
```

Open http://localhost:5173 and log in as one of the demo accounts.

`python -m backend.app.demo_seed` creates the four accounts only if they are missing, so a second
run changes nothing. The password must be at least 8 characters. With `--reset` it also clears
the accepted changes of `even-2025-26`, exactly as `DELETE /instances/{id}/changes` does
(audited as `demo_seed`), then runs one solve with the default budget (about 30 s). That solve
becomes the official timetable (D56). Run `--reset` while the API is not solving: like an API
start, it marks jobs left queued or running as `error`.

## Deploy (D55)

One Render web service serves the API under `/api` and the built frontend at `/`
(`backend/app/prod.py`). Supabase Postgres is the database.

| Render setting | Value |
|---|---|
| Language / runtime | Docker |
| Dockerfile path | `backend/Dockerfile.prod` |
| Docker build context | `.` (repo root) |
| Health check path | `/api/health` |
| Instances | 1 (one API process per database, `backend/README.md`) |

Environment variables (set them in Render, never in the repo): `DATABASE_URL`, `SECRET_KEY`,
`ACCESS_TOKEN_EXPIRE_MINUTES` (optional). Render sets `PORT`.

- **Applying migrations to Supabase is a human-only step.** Nidhi runs `alembic upgrade head`
  by hand, with `CHRONOS_ALLOW_REMOTE_DB=1` for that one command (D55). Agents never do.
- **Remote database access (D57).** The backend refuses every database host outside
  `localhost`, `127.0.0.1`, `::1`, `db` and `postgres` unless `CHRONOS_ALLOW_REMOTE_DB=1` is set
  (`db/local_guard.py`, used by `backend.app.main` and `demo_seed`). Only the Render service
  sets `CHRONOS_ALLOW_REMOTE_DB=1`, by hand in Render's environment settings, so it can use
  Supabase. It is never set in `.env` files, the repository, tests or an agent session.

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
alembic upgrade head      # current head: 0009_accepted_changes
alembic current
alembic revision --autogenerate -m "describe the change"
```

`migrations/env.py` reads `DATABASE_URL` from the environment first, then from `backend/.env`.

It **refuses to migrate a non-local database** unless `CHRONOS_ALLOW_REMOTE_DB=1` is set. The
hosted Supabase instance is the production database (D55). Only Nidhi promotes a reviewed
migration there, by hand, after agreeing it with the team.

### Frontend

```bash
cd frontend
npm ci              # install exactly what package-lock.json pins
npm test            # vitest run
npm run build       # tsc type-check + vite production build
npm run dev         # dev server
```

By default (http mode) the frontend calls the backend at `VITE_API_BASE_URL`, default `/api`; the
dev server proxies `/api` to port 8000. `VITE_API_MODE=static` serves the bundled
`contracts/examples` and `data/instances` files instead, with no backend. Every payload is
validated against the contracts. It has login, solve, repair and diagnosis, accepted changes,
substitutes, room views, the anomaly panel and the audit log. `package.json` has no `lint`
script.

### Backend

```bash
uvicorn backend.app.main:app --reload    # http://localhost:8000/docs
```

The API needs a migrated database and `SECRET_KEY` (see
[`backend/README.md`](backend/README.md)). Routes: `GET /health`, `POST /auth/login`; under
`/instances`: the list, `/{id}/edge-list`, `/{id}/edge-list/current`, `/{id}/display`,
`/{id}/anomalies`, `/{id}/solution`, `POST /{id}/solve`, `POST /{id}/repair`,
`GET`/`DELETE /{id}/changes`, `GET /{id}/sessions/{session_id}/substitutes`; `GET /jobs/{id}`,
`/jobs/{id}/base-solution`, `/jobs/{id}/edge-list`, `POST /jobs/{id}/accept`; `GET /audit`
(administrator). `backend.app.prod:app` serves the same API under `/api` and the built frontend
at `/` (Deploy, above).

## Documentation

- [`docs/CONTEXT.md`](docs/CONTEXT.md) covers what the system is, the non-negotiable rules, the
  real data, and the domain model.
- [`ROADMAP.md`](ROADMAP.md) is the phased plan and the parallel-work protocol.
- [`docs/CURRENT-PROGRESS.md`](docs/CURRENT-PROGRESS.md) tracks what is done, blockers, the
  decision log and the contract change log.
- [`docs/contract-change-proposal-v2.md`](docs/contract-change-proposal-v2.md) is the v2
  contract changes. All three members signed it off on 2026-10-06; the v2 schema files are in
  `contracts/`.
- [`CLAUDE.md`](CLAUDE.md) holds the rules for coding agents working in this repo.
