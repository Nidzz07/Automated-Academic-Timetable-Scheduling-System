"""FastAPI application entrypoint.

Run locally with:  uvicorn backend.app.main:app --reload  (see backend/README.md)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine

from backend.app import routers
from backend.app.auth import AuthSettings
from backend.app.service import ChronosService
from backend.app.store import INSTANCES_DIR, InstanceStore
from db.local_guard import local_database_url


def create_app(
    instances_dir: Path = INSTANCES_DIR,
    database_url: str | None = None,
    auth: AuthSettings | None = None,
) -> FastAPI:
    """Defaults: DATABASE_URL (local only) and SECRET_KEY, read when the app starts."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.auth = auth or AuthSettings.from_env()
        engine = create_engine(database_url or local_database_url())
        app.state.service = ChronosService(InstanceStore(instances_dir), engine)
        yield
        app.state.service.close()
        engine.dispose()

    app = FastAPI(title="Chronos API", lifespan=lifespan)
    for router in (routers.health, routers.auth, routers.instances, routers.jobs, routers.audit):
        app.include_router(router)
    return app


app = create_app()
