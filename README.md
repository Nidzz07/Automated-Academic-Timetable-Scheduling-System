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
run changes nothing. Each account's password is `CHRONOS_DEMO_PASSWORD_ADMIN`,
`CHRONOS_DEMO_PASSWORD_COORDINATOR`, `CHRONOS_DEMO_PASSWORD_FACULTY` or
`CHRONOS_DEMO_PASSWORD_STUDENT` when set, else `CHRONOS_DEMO_PASSWORD`; at least 8 characters.
With `--reset` it also sets every existing demo account's password again, clears the accepted
changes of `even-2025-26`, exactly as `DELETE /instances/{id}/changes` does (audited as
`demo_seed`), then makes the committed `data/instances/even-2025-26/solution.json` the official
timetable again without running the solver (S14y): it is recorded as one finished solve, audited
as a solve by `demo_seed`, so the demo starts from the timetable the repair measurements used.
`--solve` does the same but runs one fresh solve with the default budget (about 30 s) instead, and
that solve becomes the official timetable (D56). Run either while the API is not solving: like an
API start, it marks jobs left queued or running as `error`.

## Deploy (D55, D57, D59)

One Render web service serves the API under `/api` and the built frontend at `/`
(`backend/app/prod.py`, which serves no `/api/docs`, `/api/redoc` or `/api/openapi.json`).
Supabase Postgres is the database. Every value below in angle brackets is a placeholder: never
write a real password, key or URL into the repository.

The backend refuses every database host outside `localhost`, `127.0.0.1`, `::1`, `db` and
`postgres` unless `CHRONOS_ALLOW_REMOTE_DB=1` is set (`db/local_guard.py`, used by
`backend.app.main` and `demo_seed`; `migrations/env.py` has the same rule). Only the Render
service sets it permanently, by hand in Render's environment settings (D57); Nidhi sets it for
the commands in step 2 only (D55, D59). It is never set in `.env` files, the repository, tests or
an agent session.

### 1. Supabase

1. Create a project; keep its database password somewhere safe.
2. **Connect → Session pooler**: copy that connection string. Do not use the direct host
   (`db.<project-ref>.supabase.co`): it is IPv6-only, and Render has no IPv6 outbound.
3. Make it a SQLAlchemy URL: the scheme `postgresql+psycopg2://`, the password URL-encoded
   (`@`, `:`, `/`, `#`, `%`, `?` and other special characters break the URL otherwise; PowerShell:
   `[uri]::EscapeDataString(...)`), and `?sslmode=require` at the end:

   ```
   postgresql+psycopg2://postgres.<project-ref>:<url-encoded-password>@<session-pooler-host>:5432/postgres?sslmode=require
   ```

### 2. Migrations and demo accounts, by hand from a laptop (D55, D59)

Only Nidhi runs this, in a **new** PowerShell window at the repo root, closed afterwards, so
nothing below outlives it:

```powershell
.\.venv\Scripts\Activate.ps1

# The database password, typed and never echoed; the URL is built in memory only.
$pw = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Supabase database password')).Password
$env:DATABASE_URL = "postgresql+psycopg2://postgres.<project-ref>:$([uri]::EscapeDataString($pw))@<session-pooler-host>:5432/postgres?sslmode=require"
Remove-Variable pw
$env:CHRONOS_ALLOW_REMOTE_DB = "1"

alembic upgrade head
alembic current        # must print the head revision: 0009_accepted_changes (head)

# Demo passwords (at least 8 characters), typed and never echoed. One for all four accounts,
# or set CHRONOS_DEMO_PASSWORD_ADMIN, _COORDINATOR, _FACULTY, _STUDENT the same way to give
# an account its own.
$env:CHRONOS_DEMO_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Demo password')).Password
python -m backend.app.demo_seed --reset

Remove-Item Env:CHRONOS_DEMO_PASSWORD*, Env:CHRONOS_ALLOW_REMOTE_DB, Env:DATABASE_URL
exit
```

`demo_seed --reset` creates the four demo accounts if missing, sets every demo account's
password again (so the known logins come back), clears the accepted changes and makes the
committed `solution.json` the official timetable again, without solving. `--solve` in place of
`--reset` solves once instead (about 30 s), and that solve becomes official. It prints no
password. Run it when
nobody is solving on the site: like an API start, it marks jobs left queued or running as
`error`.

### 3. Render

**New → Web Service**, from this GitHub repository:

| Render setting | Value |
|---|---|
| Language | Docker |
| Branch | `main` |
| Dockerfile path | `backend/Dockerfile.prod` |
| Docker build context directory | `.` (the repo root) |
| Instance type | Free |
| Instances | exactly 1, never scaled out: solve and repair jobs run inside the one API process, so a second instance would mark the first one's live jobs `error` (`backend/README.md`) |
| Health check path | `/api/health` |
| Auto-Deploy | On Commit |

Environment variables (Render → the service → Environment), every one the production app reads:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the step 1 URL, password URL-encoded, ending `?sslmode=require` |
| `SECRET_KEY` | a new random key for production only, at least 32 characters (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `CHRONOS_ALLOW_REMOTE_DB` | `1` (here and nowhere else, D57) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | optional, 5 to 1440; default 30 |
| `CHRONOS_SOLVER_WORKERS` | `1` on the free instance: each solver worker process holds an instance and its search in memory, and two can exceed the free instance's 512 MB (default 2, at least 1) |

Already set, do not add: `PORT` (Render sets it; `backend/Dockerfile.prod` defaults it to 8000)
and `CHRONOS_FRONTEND_DIST` (unset in the image: the app serves `/app/frontend/dist`, where the
image puts the built frontend). The image has no `.env` file. The free instance sleeps when idle,
so the first request after a while takes about a minute; a sleep or redeploy ends any running
job, which is then marked `error` ("server restarted").

The free instance is about 9 times slower than a laptop (deployed check, 2026-11-01): a repair
that takes 2 s locally takes 20–70 s there. Live demos run on a laptop; the deployed site is
shown, not driven (D64). Render's logs have one line per finished job (`job <id> <kind>: queued
…, started …, ended …, <seconds> s, <outcome>`), one per request slower than 5 s, and one per
job a restart interrupted.

### 4. After deploying

- Open `https://<service-name>.onrender.com` and log in as `demo-admin`, `demo-coordinator`,
  `demo-faculty` or `demo-student` with the step 2 passwords. Five failed logins for one
  username within five minutes lock that username for the rest of those five minutes (429).
- To reset the demo data, run step 2 again in a new window (`alembic upgrade head` changes
  nothing when Supabase is already at head).

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
