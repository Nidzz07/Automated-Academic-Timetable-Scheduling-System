# Chronos backend

FastAPI app in `backend/app/`: routers (`routers.py`) → service (`service.py`, the only
module that calls the solver) → data access (`store.py` for instance files, SQLAlchemy for
users, the audit log and solve jobs). Run every command from the repo root, inside the venv.

## Configuration

Read from the environment, else from `backend/.env` (never committed):

| Variable | Use |
|---|---|
| `DATABASE_URL` | Postgres for users, the audit log and solve jobs. Local hosts only (`db/local_guard.py`), except with `CHRONOS_ALLOW_REMOTE_DB`. Connections are tested before use and renewed after 5 minutes (Supabase closes idle ones). |
| `CHRONOS_ALLOW_REMOTE_DB` | `1` lets the app use a non-local database. D57: set only in the Render service's environment, by hand, and for Nidhi's own hand-run `alembic` and `demo_seed` commands (D55, D59); never in a `.env` file, the repository, tests or an agent session. |
| `SECRET_KEY` | HS256 signing key for access tokens, at least 32 characters. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 30; a value outside 5 to 1440 stops the app at startup. |
| `CHRONOS_DEMO_PASSWORD` | Password of the demo accounts, `python -m backend.app.demo_seed` only (README.md). `CHRONOS_DEMO_PASSWORD_ADMIN`, `_COORDINATOR`, `_FACULTY`, `_STUDENT` override it per account. `--reset` sets them again, clears the accepted changes and makes the committed `solution.json` official without solving; `--solve` solves once instead. |
| `CHRONOS_FRONTEND_DIST` | Built frontend that `backend.app.prod:app` serves at `/` (API under `/api`); default `frontend/dist`. |
| `PORT` | Port `backend/Dockerfile.prod` listens on; Render sets it; default 8000. |

The database must be at Alembic head (`0009_accepted_changes` or later):

```powershell
alembic upgrade head
```

## Run the server

```powershell
uvicorn backend.app.main:app --reload
```

Interactive docs at http://127.0.0.1:8000/docs ("Authorize" takes a token from `/auth/login`).
The production app (`backend.app.prod:app`) serves no docs, ReDoc or OpenAPI schema.

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
| every other `GET` (`/instances...`, `/instances/{id}/edge-list/current`, `/jobs/{id}`, `/jobs/{id}/edge-list`) | any logged-in user |
| `POST /instances/{id}/solve`, `POST /instances/{id}/repair`, `POST /jobs/{id}/accept`, `GET /instances/{id}/sessions/{session_id}/substitutes` | administrator, coordinator |
| `GET /audit`, `DELETE /instances/{id}/changes` | administrator |

`POST /auth/login` takes `{"username", "password"}` and returns
`{"access_token", "token_type": "bearer", "role", "faculty_id", "cohort_id"}` (the account's
link, else null; the token carries the same claims). Send the token as
`Authorization: Bearer <token>`. A missing, invalid or expired token gets 401; a valid
token with the wrong role gets 403. After 5 failed logins for one username within 5 minutes,
that username gets 429 with `Retry-After` (seconds) until the oldest failure is 5 minutes old,
even with the right password; a successful login clears its failures. The limit is per
username only: behind Render's proxy the client address the app sees is the proxy's. It is
kept in the API process's memory, so a restart forgets it.

Every login attempt (username, success or failure, time; never the password), every
solve or repair request (user, instance, time budget, job id, final status, start and end;
for a repair also its base and change, slots as `[day, period]`; for a stale solve also
`"stale": true`), every accepted repair (user, instance, job id, base) and every clearing of
the accepted changes (user, instance, how many, and `official`: the job id or `"committed"`
official after it, null when there is none) is a row in `audit_entry`.

## Solve jobs

`POST /instances/{id}/solve` takes `{"time_limit_s", "max_moves"}` (defaults 300 s and
200000; at most 1800 s and 2000000). The job backtracks, then, if solved, improves the
timetable by local search (`solver.improve.improve`, seed 0) for at most `max_moves`
moves; `max_moves: 0` skips the improvement. `time_limit_s` covers both. While it runs,
`GET /jobs/{id}` has `"phase": "search"` or `"improve"`.

A solve that ends infeasible is explained as an infeasible repair is (`solver.mus.explain`,
S14i): a minimal conflicting set (`method: "mus"`) and the smallest relaxation verified to
restore feasibility where one exists, never relaxing a break pin (see Repair jobs), in what
is left of `time_limit_s`. Cut short by it, the diagnosis is the unfinished one
(`"presolve"`, or the solver's own); the verdict stays infeasible, never a timeout (D33).

A finished solve (solved or infeasible) has `"stale"`: `true` when the accepted changes in
force when it ended differ from its `built_with` (one was accepted or cleared while it
ran). A stale solve is kept but never official (D56).

Jobs and their solutions are rows of `solve_job`, so `GET /jobs/{id}` and
`GET /instances/{id}/solution` survive a restart. On startup, jobs left queued or running
are marked `error` with `"server restarted"`, and so are their audit rows. Run one API
process per database: a second process starting would mark the first one's live jobs the
same way.

`GET /jobs/{id}` has `"kind": "solve"` or `"repair"`. A job that fails with an exception
ends `error`; the job row, its audit row (`"error"`, first 400 characters) and the server
log keep the exception, and `GET /jobs/{id}` shows it to an administrator only. Everyone
else gets `"The solver failed. An administrator can see the details in the audit log."`

Jobs run in the API process's own pool (two at a time); at most 5 wait in `queued`. One
more solve or repair gets 429 and is not queued.

## The official solution (ROADMAP D49, D56)

`GET /instances/{id}/solution` serves the official solution: the newest finished solve
(solved or infeasible) or accepted repair that was built with exactly the accepted changes
in force when it ended or was accepted (not stale) and depends on no cleared change (its
own included), else the committed `solution.json`. A repair result becomes official only
when accepted. So the official solution is always valid for the accepted changes in force,
also after they are cleared.

## Repair jobs

`POST /instances/{id}/repair` repairs the official solution after one change
(`solver.repair.repair`, S14a) and takes `{"change", "time_limit_s", "max_moves"}`:

| `change.kind` | other fields |
|---|---|
| `faculty_unavailable` | `faculty_id`, `slots: [{"day", "period"}, ...]` (1 to 50) |
| `room_unavailable` | `room_id`, `slots` |
| `move_session` | `session_id`, `day`, `period`, `room_id`, optional `sub_room_id` |
| `substitute_faculty` | `session_id`, `faculty_id` (the new teacher) |

`time_limit_s` (default 300, at most 1800) covers the whole repair, the explanation of an
infeasible change and the closing local search included (S14k); an explanation cut by it
returns its unfinished diagnosis, which can differ between machines like a timeout; `max_moves`
(default 20000, the repair's own default; at most 2000000; 0 skips it) bounds the local
search over the sessions the repair moved. A faculty, room or session that is not in the
instance, a slot off its grid, or a substitute who already teaches the session or is not
qualified for it (see Substitutes) gets 422; no official solution, or an infeasible one,
gets 409. A `faculty_unavailable` or `room_unavailable` already in force (every slot is in
an accepted, uncleared change of the same kind for the same faculty or room) gets 422
`"This change is already in force"` and is not queued (S14n); one with any new slot is
repaired as usual. While it runs, the job's phase is `"repair"`. It ends `solved` or `infeasible`
(the repair's diagnosis) with its solution.v2, or `timeout` with none (D33). The job's
`base` is the job id of the solution it started from, or `"committed"`, and `change` is the
change. `displaced` lists the sessions whose slot changed (D48); room-only changes are found
by comparing with the base.

An infeasible repair's suggested relaxation never frees a pin that the instance's
`display.json` marks as kind `lunch`, `coffee` or `break` (D41: by its kind, never its
shape); the backend passes those pin indices to the solver as `protected`. An instance
without `display.json` protects none.

`POST /jobs/{id}/accept` makes a solved repair official and returns the job with
`accepted_at` and `accepted_by`. It answers 409 if the job is not a solved repair, or if its
base is no longer the official solution (another repair was accepted or a solve finished
since), so a repair is accepted at most once, or if its `built_with` is not the accepted
changes now in force (D56), or if its change is already in force (a job queued before the
check above existed): so an accepted change is never listed twice. Unknown job: 404.

`GET /jobs/{id}/base-solution` returns the exact solution.v2 a repair started from: the
committed `solution.json` or its base job's solution. A solve or unknown job: 404.

## Accepted changes accumulate (ROADMAP D52)

Every solve and repair builds its edge list as the committed `edge_list.json` plus every
accepted `faculty_unavailable`, `room_unavailable` and `substitute_faculty` change, in
acceptance order
(`solver.repair.apply_change`); a repair then adds its own change. An accepted
`move_session` is only a placement and is not re-applied: later repairs keep it when they
can, a fresh solve may place it elsewhere. A job's `built_with` lists the job ids of the
accepted changes it was built with. `GET /instances/{id}/edge-list` still serves the
committed file.

The edge lists jobs really use (edge_list_v1, contract-checked; any logged-in user):

- `GET /instances/{id}/edge-list/current`: the committed edge list with every accepted,
  uncleared change applied, exactly as the next solve or repair builds it;
- `GET /jobs/{id}/edge-list`: the edge list that job ran on: the committed one with the
  changes in its `built_with` and, for a repair, its own change. Unknown job: 404.

Both start from the committed file as it is now (it changes only by a commit).

`GET /instances/{id}/changes` lists the accepted changes (`job_id`, `change`,
`requested_by`, `accepted_by`, `accepted_at`), oldest first. `DELETE
/instances/{id}/changes` (administrator) clears them and returns the cleared ones; later
jobs are built without them, and the official solution becomes the newest finished solve
or accepted repair that depends on none of them, else the committed `solution.json` (D56).

## Substitutes (ROADMAP D53)

A session's qualified faculty are those the instance's `qualifications.json` lists for its
subject with its session type (`theory`, `lab`) or with none given; an instance without
that file has none. `GET /instances/{id}/sessions/{session_id}/substitutes` returns
`{"session_id", "faculty_id" (who teaches it now), "candidates", "left_out"}` for the
official solution on the edge list with every accepted change:

- `candidates`: `[{"faculty_id", "score_change"}]`, the qualified faculty who can take the
  session where it is (`solver.repair.substitute_candidates`), best score change first,
  ties by id;
- `left_out`: every other qualified teacher but the current one, by id, with `reasons`
  (`busy`: they teach or hold a frozen item then; `unavailable`: an unavailable slot) and
  the `violations` (`solver.validate`) the timetable would have with them; a teacher listed
  but without a `faculty_availability` entry in the edge list is left out with
  `not_in_instance` and no violations (their week is unknown, so they cannot be checked,
  nor be the substitute of a repair: 422).

Unknown instance or session: 404; no solved official solution, or one the accepted changes
make invalid: 409. Chronos suggests; a coordinator decides, by posting a
`substitute_faculty` repair.
