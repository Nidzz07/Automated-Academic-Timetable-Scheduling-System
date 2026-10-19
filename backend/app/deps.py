"""FastAPI dependencies: the service, and the S13b hook for auth and audit."""

from __future__ import annotations

from fastapi import Request

from backend.app.service import ChronosService


def get_service(request: Request) -> ChronosService:
    return request.app.state.service


def current_actor() -> str | None:
    """Who is calling. S13b: auth replaces this (401 when unauthenticated) and audit
    records it; every router already depends on it. Until then every caller is anonymous.
    """
    return None
