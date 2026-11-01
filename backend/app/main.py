"""FastAPI application entrypoint.

Run locally with:  uvicorn backend.app.main:app --reload  (see backend/README.md)
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from backend.app import routers
from backend.app.auth import AuthSettings, TooManyAttempts
from backend.app.service import BadChange, Busy, ChronosService, Conflict
from backend.app.store import INSTANCES_DIR, InstanceStore
from db.local_guard import local_database_url

# Supabase closes idle connections: test each one before use, and renew it after 5 minutes
POOL_RECYCLE_S = 300
# S17b: Supabase's session pooler gives each client connection its own server connection and
# refuses clients beyond the project's pool size. 5 per API process and none overflowing keeps
# two processes (a deploy overlaps old and new) plus a short connection per solver worker
# well inside it; a request waits at most POOL_TIMEOUT_S for one, then gets a 503.
POOL_SIZE = 5
POOL_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 10  # libpq's connect_timeout: an unreachable database fails, never hangs
DB_UNAVAILABLE = "The database is not answering. Try again in a minute."
SLOW_REQUEST_S = 5.0  # a request slower than this is logged
log = logging.getLogger(__name__)


def _db_unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.warning("%s %s: 503, %s: %s", request.method, request.url.path,
                type(exc).__name__, exc)
    return JSONResponse({"detail": DB_UNAVAILABLE}, 503)


def create_app(
    instances_dir: Path = INSTANCES_DIR,
    database_url: str | None = None,
    auth: AuthSettings | None = None,
    docs: bool = True,
) -> FastAPI:
    """Defaults: DATABASE_URL (local only) and SECRET_KEY, read when the app starts.
    ``docs=False`` serves no /docs, /redoc or /openapi.json (the production app, S14r)."""
    # uvicorn configures only its own loggers: without this, INFO job lines go nowhere
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.auth = auth or AuthSettings.from_env()
        engine = create_engine(database_url or local_database_url(), pool_pre_ping=True,
                               pool_recycle=POOL_RECYCLE_S, pool_size=POOL_SIZE,
                               max_overflow=0, pool_timeout=POOL_TIMEOUT_S,
                               connect_args={"connect_timeout": CONNECT_TIMEOUT_S})
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
    for error in (PoolTimeout, OperationalError):
        app.add_exception_handler(error, _db_unavailable)

    @app.middleware("http")
    async def log_slow(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started, code = time.perf_counter(), 500
        try:
            response = await call_next(request)
            code = response.status_code
            return response
        finally:
            if (seconds := time.perf_counter() - started) > SLOW_REQUEST_S:
                log.warning("slow request: %s %s %d in %.1f s", request.method,
                            request.url.path, code, seconds)

    for router in (routers.health, routers.auth, routers.instances, routers.jobs, routers.audit):
        app.include_router(router)
    return app


app = create_app()
