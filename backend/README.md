# Chronos backend

FastAPI app in `backend/app/`: routers (`routers.py`) → service (`service.py`, the only
module that calls the solver) → data access (`store.py` for instance files, SQLAlchemy for
users, the audit log and solve jobs). Run every command from the repo root, inside the venv.

## Configuration

Read from the environment, else from `backend/.env` (never committed):

| Variable | Use |
|---|---|
| `DATABASE_URL` | Postgres for users, the audit log and solve jobs. Local hosts only (`db/local_guard.py`). |
| `SECRET_KEY` | HS256 signing key for access tokens, at least 32 characters. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 30. |

The database must be at Alembic head (`0008_repair_and_links` or later):

```powershell
alembic upgrade head
```

## Run the server

```powershell
uvicorn backend.app.main:app --reload
```

Interactive docs at http://127.0.0.1:8000/docs ("Authorize" takes a token from `/auth/login`).

## Create a user

```powershell
python -m backend.app.create_user <username> --role <administrator|coordinator|faculty|student> [--faculty <id> | --cohort <id>]
```

`--faculty` or `--cohort` (at most one, ROADMAP D50) links the account to one faculty member
or cohort by its id in the real instance's edge list (`data/instances/even-2025-26`), e.g.
`fac-kailas-devadkar` or `coh-se-a`; an id that is not there is refused. The UI opens on
and locks to that timetable; the API does not filter by it (timetables are not secret).

The password is prompted for twice and never echoed, so it does not end up in a file or
the shell history. Minimum 8 characters.

## Access

| Route | Who |
|---|---|
| `GET /health`, `POST /auth/login` | anyone |
| every other `GET` (`/instances...`, `/jobs/{id}`) | any logged-in user |
| `POST /instances/{id}/solve`, `POST /instances/{id}/repair`, `POST /jobs/{id}/accept` | administrator, coordinator |
| `GET /audit` | administrator |

`POST /auth/login` takes `{"username", "password"}` and returns
`{"access_token", "token_type": "bearer", "role", "faculty_id", "cohort_id"}` (the account's
link, else null; the token carries the same claims). Send the token as
`Authorization: Bearer <token>`. A missing, invalid or expired token gets 401; a valid
token with the wrong role gets 403.

Every login attempt (username, success or failure, time; never the password), every
solve or repair request (user, instance, time budget, job id, final status, start and end;
for a repair also its base and change, slots as `[day, period]`) and every accepted repair
(user, instance, job id, base) is a row in `audit_entry`.

## Solve jobs

`POST /instances/{id}/solve` takes `{"time_limit_s", "max_moves"}` (defaults 300 s and
200000; at most 1800 s and 2000000). The job backtracks, then, if solved, improves the
timetable by local search (`solver.improve.improve`, seed 0) for at most `max_moves`
moves; `max_moves: 0` skips the improvement. `time_limit_s` covers both. While it runs,
`GET /jobs/{id}` has `"phase": "search"` or `"improve"`.

Jobs and their solutions are rows of `solve_job`, so `GET /jobs/{id}` and
`GET /instances/{id}/solution` survive a restart. On startup, jobs left queued or running
are marked `error` with `"server restarted"`, and so are their audit rows. Run one API
process per database: a second process starting would mark the first one's live jobs the
same way.

`GET /jobs/{id}` has `"kind": "solve"` or `"repair"`.

## The official solution (ROADMAP D49)

`GET /instances/{id}/solution` serves the official solution: the latest finished solve
(solved or infeasible) or accepted repair, else the committed `solution.json`. A repair
result becomes official only when accepted.

## Repair jobs

`POST /instances/{id}/repair` repairs the official solution after one change
(`solver.repair.repair`, S14a) and takes `{"change", "time_limit_s", "max_moves"}`:

| `change.kind` | other fields |
|---|---|
| `faculty_unavailable` | `faculty_id`, `slots: [{"day", "period"}, ...]` (1 to 50) |
| `room_unavailable` | `room_id`, `slots` |
| `move_session` | `session_id`, `day`, `period`, `room_id`, optional `sub_room_id` |

`time_limit_s` (default 300, at most 1800) caps each search of the repair; `max_moves`
(default 20000, the repair's own default; at most 2000000; 0 skips it) bounds the local
search over the sessions the repair moved. A faculty, room or session that is not in the
instance, or a slot off its grid, gets 422; no official solution, or an infeasible one,
gets 409. While it runs, the job's phase is `"repair"`. It ends `solved` or `infeasible`
(the repair's diagnosis) with its solution.v2, or `timeout` with none (D33). The job's
`base` is the job id of the solution it started from, or `"committed"`, and `change` is the
change. `displaced` lists the sessions whose slot changed (D48); room-only changes are found
by comparing with the base.

`POST /jobs/{id}/accept` makes a solved repair official and returns the job with
`accepted_at`. It answers 409 if the job is not a solved repair, or if its base is no longer
the official solution (another repair was accepted or a solve finished since), so a repair
is accepted at most once. Unknown job: 404.

Each repair starts from the instance's edge list plus its own change only: changes of
earlier accepted repairs are not carried forward, so a later repair may move a session back
into a slot an earlier accepted change closed.
