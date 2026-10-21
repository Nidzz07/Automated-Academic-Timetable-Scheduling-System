# Chronos backend

FastAPI app in `backend/app/`: routers (`routers.py`) → service (`service.py`, the only
module that calls the solver) → data access (`store.py` for instance files, SQLAlchemy for
users and the audit log). Run every command from the repo root, inside the venv.

## Configuration

Read from the environment, else from `backend/.env` (never committed):

| Variable | Use |
|---|---|
| `DATABASE_URL` | Postgres for users and the audit log. Local hosts only (`db/local_guard.py`). |
| `SECRET_KEY` | HS256 signing key for access tokens, at least 32 characters. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 30. |

The database must be at Alembic head (`0006_app_user` or later):

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
python -m backend.app.create_user <username> --role <administrator|coordinator|faculty|student>
```

The password is prompted for twice and never echoed, so it does not end up in a file or
the shell history. Minimum 8 characters.

## Access

| Route | Who |
|---|---|
| `GET /health`, `POST /auth/login` | anyone |
| every other `GET` (`/instances...`, `/jobs/{id}`) | any logged-in user |
| `POST /instances/{id}/solve` | administrator, coordinator |
| `GET /audit` | administrator |

`POST /auth/login` takes `{"username", "password"}` and returns
`{"access_token", "token_type": "bearer", "role"}`. Send the token as
`Authorization: Bearer <token>`. A missing, invalid or expired token gets 401; a valid
token with the wrong role gets 403.

Every login attempt (username, success or failure, time; never the password) and every
solve request (user, instance, time budget, job id, final status, start and end) is a row
in `audit_entry`.
