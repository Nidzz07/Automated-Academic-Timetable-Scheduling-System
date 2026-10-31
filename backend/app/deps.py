"""FastAPI dependencies: the service, auth settings, and the S13b bearer-token check."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from backend.app.auth import Actor, AuthSettings, read_token
from backend.app.service import ChronosService
from db.models import UserRole

# auto_error=False: FastAPI's own error for a missing header is 403; the API answers 401
_bearer = HTTPBearer(auto_error=False)


def get_service(request: Request) -> ChronosService:
    return request.app.state.service


def get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth


def current_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Actor:
    """The caller named by a valid bearer token; 401 when it is missing, invalid or expired."""
    try:
        if credentials is None:
            raise ValueError("no bearer token")
        return read_token(credentials.credentials, settings)
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing, invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_role(*roles: UserRole) -> Callable[[Actor], Actor]:
    """A dependency that admits only *roles* (403 for any other logged-in caller)."""

    def check(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
        if actor.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{actor.role.value} may not do this")
        return actor

    return check
