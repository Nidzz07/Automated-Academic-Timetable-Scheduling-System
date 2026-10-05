# CLAUDE.md

Guidance for Claude Code (and any other coding agent) working in this repository. Read it fully
before making changes.

## Read first, every session

1. `docs/CONTEXT.md` — what Chronos is, the non-negotiable rules, what the real data looks like.
2. `ROADMAP.md` (repo root) — the phased plan, the [M]/[S]/[C] tags, and the parallel-work protocol.
3. `docs/CURRENT-PROGRESS.md` — what is actually done, blockers, decision log, contract change log.

`docs/CURRENT-STATUS.md` is a **historical snapshot from 2026-09-24** (before any application
code existed). Do not treat it as the current inventory — check the code and
`docs/CURRENT-PROGRESS.md` instead.

## Git: agents never commit or push

- **Never** `git commit`, `git push`, or open/merge a PR. Leave every change in the working tree
  for a human to review, stage and commit.
- Do not run git commands that rewrite or move state (`checkout`/`switch` of another branch,
  `reset`, `rebase`, `merge`, `stash`, `branch -d`, `tag`) unless the human explicitly asks.
- A committed merge-conflict marker in `docs/CURRENT-PROGRESS.md` already happened once. Before
  handing work back, `grep -rn "<<<<<<<\|>>>>>>>" docs/ *.md` must return nothing.

## Non-negotiable rules

These come from `docs/CONTEXT.md` §2. Breaking one invalidates the project's academic claim.

1. **No machine learning anywhere in the decision path.** Nothing that generates, validates,
   diagnoses, repairs or scores a timetable may use a learned model or an LLM call. Identical input
   must always produce identical output. A future natural-language input adapter, if ever added,
   must show its parsed output for human confirmation before the solver sees it.
2. **Solver purity.** Nothing under `solver/` may import a web framework, an ORM, or a database
   driver. It takes plain Python data (the edge-list contract) and returns plain Python data. If you
   need DB data in the solver, it belongs in the edge-list payload, not in a query.
3. **Hand-written algorithms.** Colouring, backtracking, MUS extraction and repair are written in
   this project. `networkx` is allowed **only in tests**, for validation and baseline comparison.
   Purity tests enforce this (`TestSolverPurity`, `TestSolverPurityBacktracking`,
   `solver/tests/test_validate.py::TestIndependence`).
4. **Quality rules are versioned YAML data, not code.** Rules and weights live in
   `solver/rules/quality_rules.yaml` (not written yet — Phase 3). A department must be able to
   change a weight without a code change.
5. **Multi-department schema.** `Room` / `SubRoom` belong to the institute and carry no
   `department_id`; every other entity is department-scoped.
6. **Traceability.** Each major design decision must map to a course: DSGT, DAA, Data Structures,
   DBMS, OS, OOP, Statistical Methods, Software Engineering.

Also: **never invent institutional data**, and **report data-quality anomalies, never silently
fix them** (`docs/CONTEXT.md` §3.5).

## Contracts are frozen

`contracts/` holds `ingestion_v1`, `edge_list_v1` and `solution_v1` JSON Schemas plus examples.
Changing one needs all three members' agreement and an entry in the Contract change log in
`docs/CURRENT-PROGRESS.md`. `docs/contract-change-proposal-v2.md` is an **unsigned proposal** —
no `*_v2` schema exists, so do not emit or consume v2 shapes.

## Ownership — stay inside your track's directory

| Directory | Owner |
|---|---|
| `solver/` | Rohan (Track A) |
| `ingestion/`, `db/`, `migrations/`, `backend/` | Nidhi (Track B) |
| `frontend/`, `bench/`, `tests/e2e/` | Dhruv (Track C) |
| `contracts/` | all three, by agreement only |

Do not "fix" a failing test in another track's directory — report it instead.

## Environment setup

- **Python 3.12** (CI and ruff's `target-version` pin 3.12). On Windows a plain `python` may
  resolve to a different version — always use the venv.

  ```powershell
  py -3.12 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  ```

- **Local Postgres 16 via Docker Compose** (`db` service, user/password/db all `chronos`). The
  host port is `CHRONOS_DB_PORT` (default 5432). If a native PostgreSQL already owns 5432, pick
  another port and use it consistently for compose, tests and Alembic:

  ```powershell
  $env:CHRONOS_DB_PORT = "55432"
  docker compose up db -d
  ```

- **DB-backed tests** (`db/tests`, `ingestion/tests/test_seed_*.py`) connect to
  `CHRONOS_TEST_DATABASE_URL` if set, else `chronos:chronos@127.0.0.1:$CHRONOS_DB_PORT`. They
  create and drop their own scratch databases and **skip** when Postgres is unreachable — a
  skipped DB test is not a pass. They refuse to run against non-local hosts.

## Migrations

- Alembic head is **`0004_faculty_initials`** (chain: `1c8c78738a94` (0001) →
  `0002_room_used_as_raw` → `0003_subject_type_null` → `0004_faculty_initials`).
- `migrations/env.py` reads `DATABASE_URL` from the environment, then from `backend/.env`. It
  **refuses to migrate any non-local host** (`localhost`, `127.0.0.1`, `::1`, `db`, `postgres`
  only) unless `CHRONOS_ALLOW_REMOTE_DB=1`.
- **Agents never set `CHRONOS_ALLOW_REMOTE_DB=1`.** Supabase is shared staging; promoting a
  migration there is a deliberate human decision coordinated with the team.
- Every schema change goes through a new Alembic revision. Never edit the schema out of band.

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://chronos:chronos@localhost:$env:CHRONOS_DB_PORT/chronos"
alembic upgrade head
alembic current
```

## Common commands (repo root)

```powershell
ruff check .                                   # lint (CI runs this); never --fix someone else's track
pytest -q -rs                                  # full suite; -rs shows skip reasons
pytest solver/tests                            # solver unit + property tests
pytest solver/tests/test_backtracking.py::TestLabBlock
pytest -k "fixed_slot"

cd frontend; npm ci; npm test; npm run build   # vitest; build = tsc + vite build
cd frontend; npm run dev                       # Vite dev server
```

`frontend/package.json` has no `lint` script.

## What exists today (verify before relying on it)

- `solver/`: `slots.py`, `graph.py`, `colouring.py` (Welsh-Powell — known hard-constraint bugs,
  see Blockers), `backtracking.py` (forward checking + MRV, lab blocks, sub-rooms), `validate.py`
  (independent checker). **Placeholders:** infeasible results carry a placeholder diagnosis
  (`unplaced.<id>` / `UNSATISFIABLE_DOMAIN`), and solved results carry a hardcoded
  `{"score": 100.0, "breakdown": []}`. No `scoring.py`, `mus.py`, `repair.py` yet.
- `db/models.py` + migrations 0001–0004; `ingestion/` has the docx reader, initials-legend
  extraction and reference seeders. No timetable parsers (`class_tt.py` etc.) yet.
- `backend/app/main.py` is a bare `FastAPI()` with no routes.
- `frontend/` renders contract fixtures through a mock API client — not wired to a backend.

## Conventions

- Python: `dataclasses` and type hints; ruff config in `pyproject.toml` (line length 100).
- TypeScript: strict, no `any`; compose UI from the shadcn/ui primitives in
  `frontend/src/components/ui/`.
- Use domain names consistently across DB, solver and API: Department, Division, Batch, Cohort,
  Faculty, Room, SubRoom, Session, LabBlock, PinnedBlock.
- Every solved timetable must pass `solver.validate.validate_solution`; the seeded property test
  (`solver/tests/test_property_solved_is_valid.py`) must stay green. Never loosen the validator to
  make a test pass.
- End every session by updating `docs/CURRENT-PROGRESS.md` — tick only what is merged to `main`
  with a test.

## When unsure

Ask rather than guess on: contract or schema changes, anything touching solver determinism, new
dependencies, and anything outside your track's directory.
