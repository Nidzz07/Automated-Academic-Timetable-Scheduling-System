# Chronos

**Chronos** is an explainable, constraint-based academic timetable scheduler, built as a B.Tech
mini project for the Department of Computer Engineering (CE), Sardar Patel Institute of
Technology (SPIT).

Each semester, SPIT CE has to fit 41 teachers, every division, batch and elective, 20 rooms
(labs split into sub-rooms), two-hour lab blocks, lunch breaks and slots fixed by other
departments into one weekly timetable. Existing tools (FET, aSc TimeTables, UniTime) report a
bare failure when no timetable exists, and none of them answers the daily question of who can take
a class when a teacher is absent. Chronos reads the department's own files, turns every clash
into an edge of a conflict graph and colours it with hand-written algorithms. On the even
semester 2025–26 it builds a timetable with no hard-rule violations, scoring 26.5 on the
department's soft rules. The printed timetable, checked against the same rules, scores 21.5 and
has 36 violations; 26 of them are combined lectures, which Chronos models as one lecture per
division ([baseline](docs/real-baseline-even-2025-26.md)). When no timetable exists, Chronos names
a minimal set of conflicting constraints and a relaxation verified to restore feasibility. When a
teacher is absent, it suggests qualified free substitutes, or repairs only the part of the
timetable that must move: on average 4.48 sessions against 87.76 for a full regeneration
([evaluation](docs/evaluation-even-2025-26.md)). It is fully deterministic, with no machine
learning anywhere in the decision path.

## Try it

**Deployed site:** <https://chronos-l6x6.onrender.com/>

| Username | Role |
|---|---|
| `demo-admin` | Administrator |
| `demo-coordinator` | Timetable coordinator |
| `demo-faculty` | Faculty member (linked to Anant Nimkar) |
| `demo-student` | Student (linked to SE-Comp A) |

The passwords are not published: ask the team.

The site runs on Render's free instance, which is about 9 times slower than a laptop. A repair
that takes 2 s locally takes 20–70 s there, and the first request after it has been idle takes
about a minute while the instance wakes up. Live demos run on a laptop, and the deployed site is
shown, not driven (ROADMAP D64). Five failed logins for one username within five minutes lock that
username for the rest of those five minutes.

## Screenshots

Taken on a local run (http://localhost:5173) after `demo_seed --reset`.

| | |
|---|---|
| ![Login screen](docs/figures/screens/login.png) | ![Administrator view: role, Generate and Repair](docs/figures/screens/admin.png) |
| **Login.** One account per person; the role decides what the page offers. | **Administrator.** Generate a new timetable, repair the official one, accepted changes. |
| ![Weekly timetable for SE-Comp A](docs/figures/screens/timetable.png) | ![Timetable quality score 26.5](docs/figures/screens/quality.png) |
| **Weekly timetable** (student view, SE-Comp A). Lab blocks, combined lectures and fixed items. | **Quality.** Each soft rule, what it found and the points it cost. |
| ![Generated and printed timetables compared](docs/figures/screens/compare.png) | ![Find a substitute](docs/figures/screens/substitute.png) |
| **Generated vs printed.** 0 hard-rule violations against the printed timetable's 36. | **Find a substitute.** Qualified teachers free at that time, and why others are left out. |
| ![Repair proposal with workload before and after](docs/figures/screens/repair.png) | ![Faculty view: weekly load and timetable](docs/figures/screens/faculty.png) |
| **Repair proposal.** Score and both teachers' load before and after; accept or discard. | **Faculty.** Own timetable and weekly load against the 16 h limit. Read only. |
| ![Problems found in the source files](docs/figures/screens/anomalies.png) | ![Audit log](docs/figures/screens/audit.png) |
| **Source-file problems.** 475 anomalies reported, none fixed silently. | **Audit log** (administrator). Sign-ins, solves, repairs, accepts, clears. |

## Features by role

| | Administrator | Coordinator | Faculty | Student |
|---|:-:|:-:|:-:|:-:|
| See the whole department's timetable, room timetables and free rooms | ✓ | ✓ | | |
| See their own timetable (locked to their linked teacher or class) | | | ✓ | ✓ |
| See their own weekly load in lecture, practical and fixed hours, with the 16 h warning | | | ✓ | |
| Quality score, generated vs printed comparison, every teacher's load | ✓ | ✓ | | |
| Generate a new timetable (a solve job on the server) | ✓ | ✓ | | |
| Repair: mark a teacher or room unavailable, or drag a session to a new slot | ✓ | ✓ | | |
| Find a qualified substitute for a session, then accept or discard the repair | ✓ | ✓ | | |
| Infeasibility diagnosis: the conflicting constraints and a verified relaxation | ✓ | ✓ | | |
| Free and engaged teachers at a chosen slot | ✓ | ✓ | | |
| Problems found in the source files (anomaly report) | ✓ | ✓ | | |
| Audit log; clear the accepted changes | ✓ | | | |

Every role can open a session's details. The interface shows periods as T0–T9 and times in
12-hour form (D60).

## Architecture

```mermaid
flowchart LR
    B["Browser<br/>React + Vite + TypeScript<br/>(frontend/)"]
    subgraph API["FastAPI app, one process (backend/app/)"]
        R["routers.py<br/>login, roles, audit"]
        S["service.py<br/>solve and repair jobs"]
    end
    subgraph W["Worker processes<br/>(CHRONOS_SOLVER_WORKERS, default 2)"]
        SV["solver/<br/>pure Python: colouring, backtracking,<br/>local search, MUS diagnosis, repair"]
    end
    DB[("PostgreSQL 16<br/>users, audit log,<br/>solve jobs, accepted changes")]
    F["data/instances/even-2025-26/<br/>edge list, display, solution.json"]

    B -- "HTTPS, JSON, JWT<br/>(/api in production)" --> R
    R --> S
    S -- "edge_list_v1 in,<br/>solution.v2 out" --> SV
    R -- "SQLAlchemy" --> DB
    S -- "SQLAlchemy" --> DB
    S -- "reads" --> F
```

- The browser talks only to the API. Locally the Vite dev server proxies `/api` to port 8000. In
  production, `backend/app/prod.py` serves the API under `/api` and the built frontend at `/`.
- Solve and repair requests return `202` at once. The job runs in a separate worker process, and
  the browser polls `GET /jobs/{id}`.
- The solver never touches the database or the web framework. It takes the edge-list contract
  and returns a solution as plain Python data (`contracts/`).
- The quality rules and their weights are data in `solver/rules/quality_rules.yaml`, not code.

More detail:

- [docs/algorithms.md](docs/algorithms.md): every algorithm in `solver/` and the course it comes from.
- [docs/srs.md](docs/srs.md): the requirements specification.
- [docs/uml.md](docs/uml.md): UML diagrams: use cases, classes, sequences, job states, repair activity, components, deployment.
- [docs/fet-coverage.md](docs/fet-coverage.md): constraint coverage compared with FET.
- [docs/evaluation-even-2025-26.md](docs/evaluation-even-2025-26.md): every measured number.
- [docs/demo-script.md](docs/demo-script.md): the demo script and the demo video.

## Run it locally

You need:

- **Git.**
- **Python 3.12.** CI runs 3.12. On Windows a plain `python` may be another version, so create
  the venv with `py -3.12`.
- **Docker Desktop**, running, for the local PostgreSQL 16 database. `docker info` must answer
  without an error.
- **Node.js LTS** and npm, for the frontend.

The local database is the `db` service in `docker-compose.yml`. Its user, password and database
name are all `chronos`. Its host port is `CHRONOS_DB_PORT`, default 5432. If a native PostgreSQL
already owns 5432, choose another port (the examples use `55432`) and use it for every command
below: Compose, Alembic, the API and the tests.

On Windows, clone into a short folder such as your Desktop or `C:\src`. A deeply nested folder
can pass Windows' 260-character path limit, and then `git clone` fails with "Filename too long".

### Windows (PowerShell)

Terminal 1, the database and the API:

```powershell
git clone https://github.com/Nidzz07/Automated-Academic-Timetable-Scheduling-System.git
cd Automated-Academic-Timetable-Scheduling-System

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Database. Use "5432" if no native PostgreSQL owns that port.
$env:CHRONOS_DB_PORT = "55432"
docker compose up db -d
docker compose ps          # wait until the db service says "healthy"

# This shell's database. It wins over the DATABASE_URL in backend\.env.
$env:DATABASE_URL = "postgresql+psycopg2://chronos:chronos@localhost:$env:CHRONOS_DB_PORT/chronos"

# backend\.env with a new SECRET_KEY. Only once: skip it if backend\.env already exists.
Copy-Item .env.example backend\.env
$key = python -c "import secrets; print(secrets.token_hex(32))"
(Get-Content backend\.env) -replace '^SECRET_KEY=$', "SECRET_KEY=$key" | Set-Content backend\.env

alembic upgrade head
alembic current            # 0009_accepted_changes (head)

# Demo accounts. The password (8 characters or more) is typed and never echoed.
$env:CHRONOS_DEMO_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Demo password')).Password
python -m backend.app.demo_seed --reset

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

If `Activate.ps1` says running scripts is disabled, allow scripts for your user once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then run it again.

Terminal 2, the frontend (no venv needed):

```powershell
cd Automated-Academic-Timetable-Scheduling-System\frontend
npm ci
npm run dev
```

Open <http://localhost:5173> and log in as `demo-admin`, `demo-coordinator`, `demo-faculty` or
`demo-student` with the demo password.

### macOS / Linux (bash or zsh)

Terminal 1:

```bash
git clone https://github.com/Nidzz07/Automated-Academic-Timetable-Scheduling-System.git
cd Automated-Academic-Timetable-Scheduling-System

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Database. Leave CHRONOS_DB_PORT at 5432 if no native PostgreSQL owns that port.
export CHRONOS_DB_PORT=55432
docker compose up db -d
docker compose ps          # wait until the db service says "healthy"

export DATABASE_URL="postgresql+psycopg2://chronos:chronos@localhost:${CHRONOS_DB_PORT}/chronos"

# backend/.env with a new SECRET_KEY. Only once: skip it if backend/.env already exists.
cp .env.example backend/.env
key=$(python -c "import secrets; print(secrets.token_hex(32))")
sed -i.bak "s/^SECRET_KEY=$/SECRET_KEY=$key/" backend/.env && rm backend/.env.bak

alembic upgrade head
alembic current            # 0009_accepted_changes (head)

# Demo accounts. The password (8 characters or more) is typed and never echoed.
read -rs -p "Demo password: " CHRONOS_DEMO_PASSWORD; echo; export CHRONOS_DEMO_PASSWORD
python -m backend.app.demo_seed --reset

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd Automated-Academic-Timetable-Scheduling-System/frontend
npm ci
npm run dev
```

### What the steps do

- `backend/.env` is gitignored: never commit it. The environment wins over it, which is why
  `DATABASE_URL` is set in the shell when your port is not 5432. The file lists every variable
  the backend reads (`.env.example`; details in [backend/README.md](backend/README.md)).
- `demo_seed --reset` creates the four demo accounts if they are missing and sets their
  passwords again. It clears the accepted changes and makes the committed
  `data/instances/even-2025-26/solution.json` (score 26.5) the official timetable without
  solving. It ends with `job …: solved, official`. `--solve` in place of `--reset` runs one fresh
  solve instead (about 30 s), and that solve becomes official (D63). Without either flag it only
  creates missing accounts. Run it while the API is not solving: like an API start, it marks jobs
  left queued or running as `error`.
- `CHRONOS_DEMO_PASSWORD_ADMIN`, `_COORDINATOR`, `_FACULTY` and `_STUDENT` give one account its
  own password. Other accounts: `python -m backend.app.create_user` ([backend/README.md](backend/README.md)).
- Interactive API docs are at <http://127.0.0.1:8000/docs> on a local run.
- `npm ci` installs exactly what `frontend/package-lock.json` pins. `npm install` also works, but
  may rewrite the lock file. Both end with an `npm audit` vulnerability summary; it does not stop
  the install.
- In Windows PowerShell 5.1, `pip install` can print its upgrade notice in red as a
  `NativeCommandError`. That is only how PowerShell shows text on stderr; check that the install
  ends without an `ERROR:` line.
- `VITE_API_MODE=static npm run dev` runs the frontend with no backend, from the bundled
  `contracts/examples` and `data/instances` files. It has no login, Generate, repair or audit log.

## Tests

From the repo root, with the venv active, Docker's `db` running and `CHRONOS_DB_PORT` set as
above:

```powershell
ruff check .               # lint, as CI runs it
pytest -q -rs              # every fast test, about 8 minutes; -rs lists every skip and its reason
pytest -q -m slow          # the 10 slow tests, left out of the default run and CI; can take an hour
pytest solver/tests        # one folder
pytest solver/tests/test_backtracking.py::TestLabBlock   # one class

cd frontend
npm test                   # vitest, about 2 minutes
npm run build              # tsc type-check + production build
```

- `pytest -q -rs` must end with **0 skipped**. The DB-backed tests (`db/tests`,
  `backend/tests`, `ingestion/tests/test_seed_*.py`) skip when Postgres is unreachable, and a
  skipped test is not a pass. They connect to `CHRONOS_TEST_DATABASE_URL` if set, else to
  `chronos:chronos@127.0.0.1:$CHRONOS_DB_PORT`. They create and drop their own scratch
  databases, and they refuse any non-local host.
- The frontend tests run in static mode and need no backend.
- `frontend/package.json` has no `lint` script.

## Deploy (D55, D57, D59, D64)

The deployed site is one Render web service, **Free** instance, region **Ohio (US East)**. It
serves the API under `/api` and the built frontend at `/` (`backend/app/prod.py`, which serves no
`/api/docs`, `/api/redoc` or `/api/openapi.json`). The database is Supabase Postgres in
**eu-west-2 (London)**. Every value below in angle brackets is a placeholder: never write a real
password, key or URL into the repository.

The backend refuses every database host outside `localhost`, `127.0.0.1`, `::1`, `db` and
`postgres` unless `CHRONOS_ALLOW_REMOTE_DB=1` is set (`db/local_guard.py`, used by
`backend.app.main` and `demo_seed`; `migrations/env.py` has the same rule). Only the Render
service sets it permanently, by hand in Render's environment settings (D57). Nidhi sets it for
the commands in step 2 only (D55, D59). It is never set in `.env` files, the repository, tests or
an agent session.

### 1. Supabase

1. Create a project in eu-west-2 (London); keep its database password somewhere safe.
2. **Connect → Session pooler**: copy that connection string. Do not use the direct host
   (`db.<project-ref>.supabase.co`): it is IPv6-only, and Render has no IPv6 outbound.
3. Make it a SQLAlchemy URL. Change the scheme to `postgresql+psycopg2://`, URL-encode the
   password and add `?sslmode=require` at the end. Characters such as `@`, `:`, `/`, `#`, `%` and
   `?` break the URL unless they are encoded (in PowerShell, `[uri]::EscapeDataString(...)`).
   The user is `postgres.<project-ref>`, and the pooler host for eu-west-2 is
   `aws-0-eu-west-2.pooler.supabase.com` on port 5432:

   ```
   postgresql+psycopg2://postgres.<project-ref>:<url-encoded-password>@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require
   ```

### 2. Migrations and demo accounts, by hand from a laptop (D55, D59)

Only Nidhi runs this, in a **new** PowerShell window at the repo root, closed afterwards, so
nothing below outlives it:

```powershell
.\.venv\Scripts\Activate.ps1

# The database password, typed and never echoed; the URL is built in memory only.
$pw = [Net.NetworkCredential]::new('', (Read-Host -AsSecureString 'Supabase database password')).Password
$env:DATABASE_URL = "postgresql+psycopg2://postgres.<project-ref>:$([uri]::EscapeDataString($pw))@aws-0-eu-west-2.pooler.supabase.com:5432/postgres?sslmode=require"
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

`demo_seed --reset` behaves exactly as in a local run (above) and prints no password. Run it
when nobody is solving on the site. It ends with `job …: solved, official`.

### 3. Render

**New → Web Service**, from this GitHub repository:

| Render setting | Value |
|---|---|
| Language | Docker |
| Branch | `main` |
| Region | Ohio (US East) |
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
| `CHRONOS_SOLVER_WORKERS` | `1` (set). Each solver worker process holds an instance and its search in memory, and two can exceed the free instance's 512 MB (default 2, at least 1) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | optional, 5 to 1440; default 30 |

Already set, do not add: `PORT` (Render sets it; `backend/Dockerfile.prod` defaults it to 8000)
and `CHRONOS_FRONTEND_DIST` (unset in the image: the app serves `/app/frontend/dist`, where the
image puts the built frontend). The image has no `.env` file.

The free instance sleeps when idle, so the first request after a while takes about a minute. A
sleep or redeploy ends any running job, which is then marked `error` ("server restarted"). The
instance is about 9 times slower than a laptop (deployed check, 2026-11-01; D64). Render's logs
have one line per finished job (`job <id> <kind>: queued …, started …, ended …, <seconds> s,
<outcome>`), one per request slower than 5 s, and one per job a restart interrupted.

### 4. After deploying

- Open <https://chronos-l6x6.onrender.com/> and log in with a demo account. `/api/health` must
  answer `{"status":"ok"}`.
- To reset the demo data, run step 2 again in a new window. `alembic upgrade head` changes
  nothing when Supabase is already at head.

## Repository map

| Directory | What | Track and owner |
|---|---|---|
| `solver/` | pure-Python solver core: conflict graph, Welsh-Powell colouring, backtracking, presolve, scoring, local search, MUS diagnosis, repair, validation, lower bounds; `solver/rules/quality_rules.yaml`; `solver/benchmarks/` | A — Solver core and algorithms · Dhruv |
| `ingestion/` | readers and parsers for the department's `.docx`/`.xlsx` files, anomaly report, instance emitters | B — Backend and data layer · Nidhi |
| `db/` | SQLAlchemy models, edge-list export, the local-host guard | B · Nidhi |
| `migrations/` | Alembic revisions `0001`–`0009` | B · Nidhi |
| `backend/` | FastAPI app, solve and repair jobs, demo accounts, production Dockerfile | B · Nidhi |
| `data/` | `real/` (the department's source files, read-only), `reference/`, `instances/even-2025-26/` (committed edge list, display, anomalies, qualifications, solution) | B · Nidhi |
| `frontend/` | React + Vite + TypeScript UI | C — Frontend and validation · Rohan |
| `bench/` | evaluation and benchmark scripts; results in `bench/results/`, figures in `docs/figures/` | C · Rohan |
| `contracts/` | frozen JSON Schemas (`ingestion_v1`, `edge_list_v1`, `solution_v1`, v2 files) and examples | all three, by agreement only |
| `tests/` | cross-cutting tests (contract validation) | all three |
| `docs/` | context, roadmap progress, algorithms, SRS, UML, evaluation, demo script | all three |

The tracks meet only at the JSON contracts in [`contracts/`](contracts/): ingestion → database,
database → solver (edge list), and solver → API (solution).

## Documentation

| Document | What it covers |
|---|---|
| [docs/CONTEXT.md](docs/CONTEXT.md) | what Chronos is, the non-negotiable rules, the real data, the domain model |
| [ROADMAP.md](ROADMAP.md) | the phased plan, ownership and every decision (D1–D64) |
| [docs/CURRENT-PROGRESS.md](docs/CURRENT-PROGRESS.md) | what is done, blockers, the decision and contract change logs |
| [docs/algorithms.md](docs/algorithms.md) | every solver algorithm and its source course |
| [docs/srs.md](docs/srs.md) | software requirements specification |
| [docs/uml.md](docs/uml.md) | UML diagrams |
| [docs/fet-coverage.md](docs/fet-coverage.md) | constraint coverage compared with FET |
| [docs/evaluation-even-2025-26.md](docs/evaluation-even-2025-26.md) | evaluation on synthetic presets and the real even-semester instance |
| [docs/demo-script.md](docs/demo-script.md) | demo script and the link to the demo video |
| [docs/repair-even-2025-26.md](docs/repair-even-2025-26.md) | repair measurements on the real instance |
| [docs/real-baseline-even-2025-26.md](docs/real-baseline-even-2025-26.md) | the printed timetable scored and validated |
| [docs/real-solve-even-2025-26.md](docs/real-solve-even-2025-26.md) | solving the real instance |
| [docs/faculty-mapping-even-2025-26.md](docs/faculty-mapping-even-2025-26.md) | faculty initials mapped to names |
| [docs/contract-change-proposal-v2.md](docs/contract-change-proposal-v2.md) | the v2 contract changes |
| [backend/README.md](backend/README.md) | API configuration, access rules, jobs, repair, substitutes |
| [CLAUDE.md](CLAUDE.md) | rules for coding agents working in this repository |

## Team

| Member | UID | Track |
|---|---|---|
| Dhruv Hemant Gangurde | 2024300061 | A — Solver core and algorithms |
| Nidhi Rajkamal Dhyani | 2024300050 | B — Backend and data layer |
| Rohan Shashikant Dhumal | 2024300049 | C — Frontend and validation |

**Project guide:** Mr. Devang Parab.

Department of Computer Engineering, Sardar Patel Institute of Technology.
