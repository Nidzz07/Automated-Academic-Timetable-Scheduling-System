"""HTTP routes (S13a). Routers only translate HTTP; the service does the work.

S13b: /health and /auth/login are public; every other route needs a bearer token.
Any role may read; only administrator and coordinator may solve; only administrator
reads the audit log.

S14c: administrator and coordinator may also repair the official solution and accept
a solved repair (ROADMAP D49). A login returns the account's faculty or cohort link
(D50).

S14f (ROADMAP D52): any role may list the accepted changes every solve and repair
includes; only administrator clears them. A job names the accepted changes it was
built with, and a repair's base solution is served as it started from it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.app.auth import Actor, AuthSettings, issue_token
from backend.app.deps import current_actor, get_auth_settings, get_service, require_role
from backend.app.service import (
    DEFAULT_MAX_MOVES,
    DEFAULT_REPAIR_MAX_MOVES,
    DEFAULT_TIME_LIMIT_S,
    MAX_MAX_MOVES,
    MAX_TIME_LIMIT_S,
    ChronosService,
)
from db.models import UserRole

Service = Annotated[ChronosService, Depends(get_service)]
Solver = Annotated[
    Actor, Depends(require_role(UserRole.ADMINISTRATOR, UserRole.COORDINATOR))
]
Administrator = Annotated[Actor, Depends(require_role(UserRole.ADMINISTRATOR))]
JobStatus = Literal["queued", "running", "solved", "infeasible", "timeout", "error"]


class SolveRequest(BaseModel):
    time_limit_s: float = Field(
        DEFAULT_TIME_LIMIT_S, gt=0, le=MAX_TIME_LIMIT_S, description="search and improve"
    )
    max_moves: int = Field(
        DEFAULT_MAX_MOVES, ge=0, le=MAX_MAX_MOVES,
        description="local-search moves after a solve; 0 skips the improvement",
    )


class Slot(BaseModel):
    day: int = Field(ge=0)
    period: int = Field(ge=0)


# a week has at most 50 cells (solver/slots.py: 5 days x 10 periods)
Slots = Annotated[list[Slot], Field(min_length=1, max_length=50)]


class FacultyUnavailable(BaseModel):
    kind: Literal["faculty_unavailable"]
    faculty_id: str
    slots: Slots


class RoomUnavailable(BaseModel):
    kind: Literal["room_unavailable"]
    room_id: str
    slots: Slots


class MoveSession(BaseModel):
    kind: Literal["move_session"]
    session_id: str
    day: int = Field(ge=0)
    period: int = Field(ge=0)
    room_id: str
    sub_room_id: str | None = None


class RepairRequest(SolveRequest):
    """One change (solver.repair.apply_change), and the budgets as for a solve."""

    change: Annotated[
        FacultyUnavailable | RoomUnavailable | MoveSession, Field(discriminator="kind")
    ]
    max_moves: int = Field(
        DEFAULT_REPAIR_MAX_MOVES, ge=0, le=MAX_MAX_MOVES,
        description="local-search moves on the sessions the repair moved; 0 skips it",
    )


class SolveAccepted(BaseModel):
    job_id: str
    status: JobStatus


class JobView(BaseModel):
    id: str
    instance_id: str
    kind: Literal["solve", "repair"]
    time_limit_s: float
    max_moves: int
    status: JobStatus
    phase: Literal["search", "improve", "repair"] | None = Field(
        None, description="while running"
    )
    base: str | None = Field(
        None, description="repair: the job id of the solution it started from, or 'committed'"
    )
    change: dict[str, Any] | None = Field(None, description="repair: the change")
    accepted_at: datetime | None = Field(None, description="repair: when it became official")
    accepted_by: str | None = Field(None, description="repair: who made it official")
    built_with: list[str] | None = Field(
        None, description="the job ids of the accepted changes its edge list includes (D52)"
    )
    solution: dict[str, Any] | None = Field(
        None, description="solution.v2, present when status is solved or infeasible"
    )
    error: str | None = None


class AcceptedChange(BaseModel):
    job_id: str = Field(description="the accepted repair")
    change: dict[str, Any]
    requested_by: str
    accepted_by: str | None = Field(description="null for repairs accepted before S14f")
    accepted_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: UserRole
    faculty_id: str | None = None
    cohort_id: str | None = None


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
    return Token(access_token=issue_token(actor, settings), role=actor.role,
                 faculty_id=actor.faculty_id, cohort_id=actor.cohort_id)


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


@instances.get(
    "/{instance_id}/solution",
    description="the official solution.v2: the latest finished solve or accepted repair, "
    "else the committed solution.json",
)
def get_solution(instance_id: str, service: Service) -> dict[str, Any]:
    return _found(service.solution(instance_id), "solution")


@instances.post("/{instance_id}/solve", status_code=status.HTTP_202_ACCEPTED)
def start_solve(
    instance_id: str, service: Service, actor: Solver, req: SolveRequest | None = None
) -> SolveAccepted:
    req = req or SolveRequest()
    job_id = _found(
        service.start_solve(instance_id, req.time_limit_s, req.max_moves, actor.username),
        "instance",
    )
    return SolveAccepted(job_id=job_id, status=_found(service.job(job_id), "job")["status"])


@instances.post(
    "/{instance_id}/repair", status_code=status.HTTP_202_ACCEPTED,
    description="repair the official solution; 422 for an unknown id or slot, 409 when "
    "there is no solved official solution",
)
def start_repair(
    instance_id: str, req: RepairRequest, service: Service, actor: Solver
) -> SolveAccepted:
    job_id = _found(
        service.start_repair(instance_id, req.change.model_dump(exclude_none=True),
                             req.time_limit_s, req.max_moves, actor.username),
        "instance",
    )
    return SolveAccepted(job_id=job_id, status=_found(service.job(job_id), "job")["status"])


@instances.get(
    "/{instance_id}/changes",
    description="the accepted faculty and room unavailability changes every solve and "
    "repair includes (D52), in acceptance order",
)
def get_changes(instance_id: str, service: Service) -> list[AcceptedChange]:
    return [AcceptedChange(**c) for c in _found(service.changes(instance_id), "instance")]


@instances.delete(
    "/{instance_id}/changes",
    description="administrator: clear the accepted changes (audited); returns the cleared ones",
)
def clear_changes(
    instance_id: str, service: Service, actor: Administrator
) -> list[AcceptedChange]:
    cleared = service.clear_changes(instance_id, actor.username)
    return [AcceptedChange(**c) for c in _found(cleared, "instance")]


@jobs.get("/{job_id}", response_model_exclude_none=True)
def get_job(job_id: str, service: Service) -> JobView:
    return JobView(**_found(service.job(job_id), "job"))


@jobs.get(
    "/{job_id}/base-solution",
    description="the solution.v2 a repair started from; 404 for a solve",
)
def get_base_solution(job_id: str, service: Service) -> dict[str, Any]:
    return _found(service.base_solution(job_id), "base solution")


@jobs.post(
    "/{job_id}/accept", response_model_exclude_none=True,
    description="make a solved repair official; 409 unless its base is still official",
)
def accept_repair(job_id: str, service: Service, actor: Solver) -> JobView:
    return JobView(**_found(service.accept(job_id, actor.username), "job"))


@audit.get("", description="newest first")
def get_audit(
    service: Service, limit: Annotated[int, Query(ge=1, le=1000)] = 100
) -> list[AuditView]:
    return [AuditView(**row) for row in service.audit_entries(limit)]
