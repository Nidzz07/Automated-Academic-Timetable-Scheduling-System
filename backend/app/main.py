"""FastAPI application entrypoint.

Run locally with:  uvicorn backend.app.main:app --reload  (see backend/README.md)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine

from backend.app import routers
from backend.app.auth import AuthSettings, TooManyAttempts
from backend.app.service import BadChange, Busy, ChronosService, Conflict
from backend.app.store import INSTANCES_DIR, InstanceStore
from db.local_guard import local_database_url

# Supabase closes idle connections: test each one before use, and renew it after 5 minutes
POOL_RECYCLE_S = 300


def create_app(
    instances_dir: Path = INSTANCES_DIR,
    database_url: str | None = None,
    auth: AuthSettings | None = None,
    docs: bool = True,
) -> FastAPI:
    """Defaults: DATABASE_URL (local only) and SECRET_KEY, read when the app starts.
    ``docs=False`` serves no /docs, /redoc or /openapi.json (the production app, S14r)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.auth = auth or AuthSettings.from_env()
        engine = create_engine(database_url or local_database_url(), pool_pre_ping=True,
                               pool_recycle=POOL_RECYCLE_S)
        app.state.service = ChronosService(InstanceStore(instances_dir), engine)
        yield
        app.state.service.close()
        engine.dispose()

    off = {} if docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Chronos API", lifespan=lifespan, **off)
    for error, code in ((BadChange, 422), (Conflict, 409), (Busy, 429)):
        app.add_exception_handler(
            error, lambda _request, exc, code=code: JSONResponse({"detail": str(exc)}, code)
        )
    app.add_exception_handler(TooManyAttempts, lambda _request, exc: JSONResponse(
        {"detail": str(exc)}, 429, headers={"Retry-After": str(exc.retry_after)}))
    for router in (routers.health, routers.auth, routers.instances, routers.jobs, routers.audit):
        app.include_router(router)
    return app


app = create_app()
