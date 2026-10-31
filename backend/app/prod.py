"""Production ASGI app (S16b, ROADMAP D55): the API under /api, the built frontend at /.

Run:  uvicorn backend.app.prod:app --host 0.0.0.0 --port $PORT  (backend/Dockerfile.prod)

The API is ``backend.app.main``'s, without its public docs (S14r: no /api/docs, /api/redoc
or /api/openapi.json; ``uvicorn backend.app.main:app`` keeps them). The frontend's http
client calls
``/api/...`` (``VITE_API_BASE_URL`` defaults to ``/api``) and the Vite dev proxy strips
``/api`` before the backend; the mount strips it the same way, so the UI needs no change.
Any other path that is not a built file gets ``index.html``. ``CHRONOS_FRONTEND_DIST``
overrides the built frontend's directory (default ``frontend/dist``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from backend.app import main
from backend.app.store import REPO


class SinglePage(StaticFiles):
    """The built files, and ``index.html`` for any path that is not one."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def create_app(api: FastAPI | None = None, dist: Path | None = None) -> Starlette:
    """*api* (default: ``main.create_app(docs=False)``) at /api and *dist* (default:
    ``CHRONOS_FRONTEND_DIST``, else ``frontend/dist``) at /. Starting fails when *dist*
    has no ``index.html``."""
    api = api or main.create_app(docs=False)
    dist = dist or Path(os.environ.get("CHRONOS_FRONTEND_DIST") or REPO / "frontend" / "dist")

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        if not (dist / "index.html").is_file():
            raise RuntimeError(f"no built frontend at {dist} (cd frontend; npm run build)")
        # Starlette runs no lifespan of a mounted app: the API's service starts here
        async with api.router.lifespan_context(api):
            yield

    return Starlette(
        lifespan=lifespan,
        routes=[Mount("/api", app=api),
                Mount("/", app=SinglePage(directory=dist, html=True, check_dir=False))],
    )


app = create_app()
