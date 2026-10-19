"""HTTP routes (S13a). Routers only translate HTTP; the service does the work."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.deps import current_actor, get_service
from backend.app.service import DEFAULT_TIME_LIMIT_S, MAX_TIME_LIMIT_S, ChronosService

Service = Annotated[ChronosService, Depends(get_service)]
Actor = Annotated[str | None, Depends(current_actor)]
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


def _found[T](value: T | None, what: str) -> T:
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return value


health = APIRouter(tags=["health"])
# S13b: auth and audit attach through current_actor, which every non-health route depends on
_hooks = [Depends(current_actor)]
instances = APIRouter(prefix="/instances", tags=["instances"], dependencies=_hooks)
jobs = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=_hooks)


@health.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}


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
    instance_id: str, service: Service, actor: Actor, req: SolveRequest | None = None
) -> SolveAccepted:
    job = _found(
        service.start_solve(instance_id, (req or SolveRequest()).time_limit_s, actor), "instance"
    )
    return SolveAccepted(job_id=job.id, status=_found(service.job(job.id), "job")["status"])


@jobs.get("/{job_id}", response_model_exclude_none=True)
def get_job(job_id: str, service: Service) -> JobView:
    return JobView(**_found(service.job(job_id), "job"))
