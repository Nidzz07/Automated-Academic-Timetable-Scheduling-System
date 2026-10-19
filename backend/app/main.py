"""FastAPI application entrypoint.

Run locally with:  uvicorn backend.app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.app import routers
from backend.app.service import ChronosService
from backend.app.store import INSTANCES_DIR, InstanceStore


def create_app(instances_dir: Path = INSTANCES_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.service = ChronosService(InstanceStore(instances_dir))
        yield
        app.state.service.close()

    app = FastAPI(title="Chronos API", lifespan=lifespan)
    for router in (routers.health, routers.instances, routers.jobs):
        app.include_router(router)
    return app


app = create_app()
