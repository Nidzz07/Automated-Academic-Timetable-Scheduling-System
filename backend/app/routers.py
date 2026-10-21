"""HTTP routes (S13a). Routers only translate HTTP; the service does the work.

S13b: /health and /auth/login are public; every other route needs a bearer token.
Any role may read; only administrator and coordinator may solve; only administrator
reads the audit log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.app.auth import Actor, AuthSettings, issue_token
from backend.app.deps import current_actor, get_auth_settings, get_service, require_role
from backend.app.service import DEFAULT_TIME_LIMIT_S, MAX_TIME_LIMIT_S, ChronosService
from db.models import UserRole

Service = Annotated[ChronosService, Depends(get_service)]
Solver = Annotated[
    Actor, Depends(require_role(UserRole.ADMINISTRATOR, UserRole.COORDINATOR))
]
JobStatus = Literal["queued", "running", "solved", "infeasible", "timeout", "error"]


class SolveRequest(BaseModel):
    time_limit_s: float = Field(DEFAULT_TIME_LIMIT_S, gt=0, le=MAX_TIME_LIMIT_S)


class SolveAccepted(BaseModel):
    job_id: str
    status: JobStatus


class JobView(BaseModel):
    id: str
    instance_id: str
    time_limit_s: float
    status: JobStatus
    solution: dict[str, Any] | None = Field(
        None, description="solution.v2, present when status is solved or infeasible"
    )
    error: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: UserRole


class AuditView(BaseModel):
    id: int
    actor: str
    action: str
    timestamp: datetime
    detail: dict[str, Any] | None


def _found[T](value: T | None, what: str) -> T:
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return value


health = APIRouter(tags=["health"])
auth = APIRouter(prefix="/auth", tags=["auth"])
_logged_in = [Depends(current_actor)]
instances = APIRouter(prefix="/instances", tags=["instances"], dependencies=_logged_in)
jobs = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=_logged_in)
audit = APIRouter(
    prefix="/audit", tags=["audit"], dependencies=[Depends(require_role(UserRole.ADMINISTRATOR))]
)


@health.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}


@auth.post("/login")
def login(
    req: LoginRequest,
    service: Service,
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Token:
    actor = service.login(req.username, req.password)
    if actor is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=issue_token(actor, settings), role=actor.role)


@instances.get("")
def list_instances(service: Service) -> list[dict[str, str]]:
    return [{"id": i} for i in service.instance_ids()]


@instances.get("/{instance_id}/edge-list", description="edge_list_v1")
def get_edge_list(instance_id: str, service: Service) -> dict[str, Any]:
    return _found(service.edge_list(instance_id), "instance")


@instances.get("/{instance_id}/display", description="display.json (D41 sidecar)")
def get_display(instance_id: str, service: Service) -> Any:
    return _found(service.display(instance_id), "display")


@instances.get("/{instance_id}/anomalies")
def get_anomalies(instance_id: str, service: Service) -> Any:
    return _found(service.anomalies(instance_id), "anomalies")


@instances.get("/{instance_id}/solution", description="the latest solution.v2")
def get_solution(instance_id: str, service: Service) -> dict[str, Any]:
    return _found(service.solution(instance_id), "solution")


@instances.post("/{instance_id}/solve", status_code=status.HTTP_202_ACCEPTED)
def start_solve(
    instance_id: str, service: Service, actor: Solver, req: SolveRequest | None = None
) -> SolveAccepted:
    time_limit_s = (req or SolveRequest()).time_limit_s
    job = _found(service.start_solve(instance_id, time_limit_s, actor.username), "instance")
    return SolveAccepted(job_id=job.id, status=_found(service.job(job.id), "job")["status"])


@jobs.get("/{job_id}", response_model_exclude_none=True)
def get_job(job_id: str, service: Service) -> JobView:
    return JobView(**_found(service.job(job_id), "job"))


@audit.get("", description="newest first")
def get_audit(
    service: Service, limit: Annotated[int, Query(ge=1, le=1000)] = 100
) -> list[AuditView]:
    return [AuditView(**row) for row in service.audit_entries(limit)]
