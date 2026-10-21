"""Service layer (S13a): the only backend module that calls the solver.

Solves run in a process pool, so the API never blocks on a search. A job ends
``solved`` or ``infeasible`` with its solution.v2 payload, ``timeout`` with none
(ROADMAP D33: a timeout is a job status, never an infeasible solution) or
``error``. Every payload served is checked against its contract schema first.

S13b: logins and solve requests are written to ``audit_entry``. A solve's row is
written when it is queued and completed with its final status when it ends.

S13d: a solved timetable is then improved by local search (:func:`solver.improve.improve`)
within the same time budget. Jobs and their solutions are rows of ``solve_job``, so they
survive a restart; jobs a restart interrupted are marked ``error``.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import UTC, datetime
from functools import cache, partial
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool

from backend.app.auth import Actor, verify_password
from backend.app.store import REPO, InstanceStore
from db.models import AuditEntry, SolveJob, User
from solver.backtracking import backtrack_solve
from solver.graph import build_conflict_graph
from solver.improve import MAX_MOVES, improve
from solver.validate import validate_solution

CONTRACTS_DIR = REPO / "contracts"
DEFAULT_TIME_LIMIT_S = 300.0  # the budget of the S12a real solve (solver/benchmarks/real_solve.py)
MAX_TIME_LIMIT_S = 1800.0
DEFAULT_MAX_MOVES = MAX_MOVES  # solver.improve's default, about 20 s on the real instance
MAX_MAX_MOVES = 2_000_000


class ContractError(ValueError):
    """A payload does not conform to its contract schema."""


@cache
def _validator(contract: str) -> Draft202012Validator:
    path = CONTRACTS_DIR / f"{contract}.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def check_contract(contract: str, payload: Any) -> None:
    """Raise :class:`ContractError` unless *payload* conforms to ``contracts/<contract>``."""
    errors = [e.message for e in _validator(contract).iter_errors(payload)]
    if errors:
        raise ContractError(f"{contract}: {len(errors)} errors, first: {errors[0]}")


def solve_edge_list(
    edge_list: dict[str, Any],
    time_limit_s: float,
    max_moves: int = 0,
    on_phase: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Runs in a pool worker: (outcome, solution.v2 payload or None on a timeout).

    Backtracking, then, when solved and *max_moves* > 0, local search (seed 0) in what
    is left of *time_limit_s*. *on_phase* hears ``search``, then ``improve``.
    """
    graph = build_conflict_graph(edge_list)
    if on_phase:
        on_phase("search")
    started = time.perf_counter()
    result = backtrack_solve(graph, edge_list, time_limit_s=time_limit_s)
    runtime_ms = (time.perf_counter() - started) * 1000
    if result.outcome == "timeout":
        return "timeout", None
    solution = result.to_solution_v2_dict(runtime_ms=runtime_ms)
    if result.solved and max_moves:
        if on_phase:
            on_phase("improve")
        remaining = max(0.0, time_limit_s - (time.perf_counter() - started))
        solution = improve(edge_list, solution, max_moves=max_moves, seed=0,
                           time_limit_s=remaining)
    if result.solved and (violations := validate_solution(edge_list, solution)):
        raise RuntimeError(f"solved but invalid: {[v.to_dict() for v in violations]}")
    check_contract("solution_v2", solution)
    return result.outcome, solution


def _mark_running(database_url: str, job_id: str, phase: str) -> None:
    """Runs in the pool worker (as ``on_phase``): the job is running *phase*."""
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(update(SolveJob).where(SolveJob.id == job_id).values(
                status="running", phase=phase,
                started_at=func.coalesce(SolveJob.started_at, func.now()),
            ))
    finally:
        engine.dispose()


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChronosService:
    def __init__(self, store: InstanceStore, engine: Engine, max_workers: int = 2) -> None:
        self.store = store
        self._engine = engine  # users, the audit log and solve jobs
        self._pool = ProcessPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        # instance id -> ((mtime_ns, size) of edge_list.json, the contract-checked payload)
        self._edge_lists: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        # shortcut: assumes one API process per database (a second one starting would fail
        # the first one's live jobs); give jobs an owner id before running several workers.
        with OrmSession(engine) as db:
            db.execute(
                update(SolveJob)
                .where(SolveJob.status.in_(("queued", "running")))
                .values(status="error", error="server restarted", ended_at=func.now())
            )
            db.commit()

    def close(self) -> None:
        # waits for solves already running (at most their time budget)
        self._pool.shutdown(cancel_futures=True)

    def instance_ids(self) -> list[str]:
        return self.store.ids()

    def edge_list(self, instance_id: str) -> dict[str, Any] | None:
        """The instance's edge_list_v1, contract-checked once per version of the file."""
        path = self.store.path(instance_id, "edge_list")
        if path is None:
            return None
        stat = path.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._edge_lists.get(instance_id)
        if cached is not None and cached[0] == version:
            return cached[1]
        edge_list = self.store.read(instance_id, "edge_list")
        check_contract("edge_list_v1", edge_list)
        with self._lock:
            self._edge_lists[instance_id] = (version, edge_list)
        return edge_list

    def display(self, instance_id: str) -> Any | None:
        return self.store.read(instance_id, "display")  # D41 sidecar: no contract

    def anomalies(self, instance_id: str) -> Any | None:
        return self.store.read(instance_id, "anomalies")  # no contract

    def solution(self, instance_id: str) -> dict[str, Any] | None:
        """The last-finished job's solution.v2, else the committed ``solution.json``."""
        if self.store.path(instance_id, "edge_list") is None:
            return None
        with OrmSession(self._engine) as db:
            latest = db.scalar(
                select(SolveJob.solution)
                .where(SolveJob.instance_id == instance_id, SolveJob.solution.is_not(None))
                .order_by(SolveJob.ended_at.desc())
                .limit(1)
            )
        if latest is None:
            latest = self.store.read(instance_id, "solution")
            if latest is not None:
                check_contract("solution_v2", latest)
        return latest

    def login(self, username: str, password: str) -> Actor | None:
        """The account's actor when the password matches, else None. Audited either way."""
        with OrmSession(self._engine) as db:
            user = db.scalar(select(User).where(User.username == username))
            ok = verify_password(password, user.password_hash if user else None)
            self._audit(db, username, "login", {"success": ok})
            db.commit()
            return Actor(user.username, user.role) if ok and user else None

    def start_solve(
        self, instance_id: str, time_limit_s: float, max_moves: int, actor: str
    ) -> str | None:
        """Queue a solve of the instance's edge list: the job id, or None when the
        instance is unknown."""
        edge_list = self.edge_list(instance_id)
        if edge_list is None:
            return None
        job_id = uuid.uuid4().hex
        detail = {
            "instance_id": instance_id,
            "time_limit_s": time_limit_s,
            "job_id": job_id,
            "status": "queued",
            "started_at": _now(),
            "ended_at": None,
        }
        params = {"time_limit_s": time_limit_s, "max_moves": max_moves}
        with OrmSession(self._engine) as db:  # audited before it runs: no unaudited solve
            audit_id = self._audit(db, actor, "solve", detail)
            db.add(SolveJob(id=job_id, instance_id=instance_id, requested_by=actor,
                            status="queued", params=params))
            db.commit()
        on_phase = partial(
            _mark_running, self._engine.url.render_as_string(hide_password=False), job_id
        )
        future = self._pool.submit(solve_edge_list, edge_list, time_limit_s, max_moves, on_phase)
        future.add_done_callback(lambda f: self._job_done(job_id, audit_id, detail, f))
        return job_id

    def _job_done(
        self, job_id: str, audit_id: int, detail: dict[str, Any], future: Future[Any]
    ) -> None:
        solution, error = None, None
        if future.cancelled():
            status, error = "error", "cancelled"
        elif (exc := future.exception()) is not None:
            status, error = "error", f"{type(exc).__name__}: {exc}"
        else:
            status, solution = future.result()
        with OrmSession(self._engine) as db:
            job = db.get_one(SolveJob, job_id)
            job.status, job.error, job.ended_at = status, error, func.now()
            if solution is not None:  # assigning None would store JSON null, not SQL NULL
                job.solution = solution
            detail = detail | {"status": status, "ended_at": _now()}
            db.get_one(AuditEntry, audit_id).detail = json.dumps(detail)
            db.commit()

    @staticmethod
    def _audit(db: OrmSession, actor: str, action: str, detail: dict[str, Any]) -> int:
        entry = AuditEntry(actor=actor, action=action, detail=json.dumps(detail))
        db.add(entry)
        db.flush()
        return entry.id

    def audit_entries(self, limit: int) -> list[dict[str, Any]]:
        """The newest *limit* audit rows, newest first; ``detail`` is the JSON written here."""
        with OrmSession(self._engine) as db:
            rows = db.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit))
            return [
                {
                    "id": row.id,
                    "actor": row.actor,
                    "action": row.action,
                    "timestamp": row.timestamp,
                    "detail": json.loads(row.detail) if row.detail else None,
                }
                for row in rows
            ]

    def job(self, job_id: str) -> dict[str, Any] | None:
        """The job's status, its phase while running and, once solved or infeasible, its
        solution; None if unknown."""
        with OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None:
                return None
            view: dict[str, Any] = {
                "id": job.id, "instance_id": job.instance_id, **job.params, "status": job.status
            }
            if job.status == "running":
                view["phase"] = job.phase
            if job.solution is not None:
                view["solution"] = job.solution
            if job.error is not None:
                view["error"] = job.error
            return view
