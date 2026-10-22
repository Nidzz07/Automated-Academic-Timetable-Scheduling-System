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

S14c: a repair job runs :func:`solver.repair.repair` on the instance's official solution
for one change and records that solution as its ``base``. The official solution
(ROADMAP D49) is the latest finished solve or accepted repair, else the committed
``solution.json``; a solved repair becomes official only when accepted while its base is
still official.

S14f (ROADMAP D52): every solve and repair builds its edge list as the committed one plus
every accepted faculty and room unavailability change not yet cleared, in acceptance order
(:func:`solver.repair.apply_change`), and records their job ids as ``built_with``. An
accepted move is only a placement and is not re-applied. An administrator can clear the
accepted changes.
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
from sqlalchemy import Engine, and_, create_engine, func, or_, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool

from backend.app.auth import Actor, verify_password
from backend.app.store import REPO, InstanceStore
from db.models import AuditEntry, SolveJob, User
from solver.backtracking import backtrack_solve
from solver.graph import build_conflict_graph
from solver.improve import MAX_MOVES, improve
from solver.repair import MAX_MOVES as REPAIR_MAX_MOVES
from solver.repair import apply_change, repair
from solver.validate import validate_solution

CONTRACTS_DIR = REPO / "contracts"
DEFAULT_TIME_LIMIT_S = 300.0  # the budget of the S12a real solve (solver/benchmarks/real_solve.py)
MAX_TIME_LIMIT_S = 1800.0
DEFAULT_MAX_MOVES = MAX_MOVES  # solver.improve's default, about 20 s on the real instance
MAX_MAX_MOVES = 2_000_000
DEFAULT_REPAIR_MAX_MOVES = REPAIR_MAX_MOVES  # solver.repair's default
COMMITTED = "committed"  # a repair's base when it started from the committed solution.json
ACCUMULATED = ("faculty_unavailable", "room_unavailable")  # D52; a move is not re-applied


class ContractError(ValueError):
    """A payload does not conform to its contract schema."""


class BadChange(ValueError):
    """A repair change names an unknown faculty, room, session or slot (HTTP 422)."""


class Conflict(Exception):
    """The request does not fit the instance's current state (HTTP 409)."""


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


def repair_edge_list(
    edge_list: dict[str, Any],
    solution: dict[str, Any],
    change: dict[str, Any],
    time_limit_s: float,
    max_moves: int,
    on_phase: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Runs in a pool worker: (outcome, solution.v2 payload or None on a timeout).

    *time_limit_s* caps each search of :func:`solver.repair.repair`; running out of it
    with every session free is a timeout, never infeasible (D33). *on_phase* hears
    ``repair``.
    """
    if on_phase:
        on_phase("repair")
    try:
        repaired = repair(edge_list, solution, change, max_moves=max_moves,
                          time_limit_s=time_limit_s)
    except TimeoutError:
        return "timeout", None
    check_contract("solution_v2", repaired)  # repair() itself validates the hard rules
    return repaired["status"], repaired


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
        self._official_lock = threading.Lock()  # accepting a repair vs. a job ending
        # instance id -> ((mtime_ns, size) of edge_list.json, the contract-checked payload)
        self._edge_lists: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        # shortcut: assumes one API process per database (a second one starting would fail
        # the first one's live jobs); give jobs an owner id before running several workers.
        with OrmSession(engine) as db:
            unfinished = select(SolveJob).where(SolveJob.status.in_(("queued", "running")))
            for job in db.scalars(unfinished):
                job.status, job.error, job.ended_at = "error", "server restarted", func.now()
                if job.audit_id is not None:
                    self._finish_audit(db, job.audit_id, "error")
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
        """The instance's official solution.v2 (see :meth:`_official`), else None."""
        if self.store.path(instance_id, "edge_list") is None:
            return None
        with OrmSession(self._engine) as db:
            official = self._official(db, instance_id)
        return official[1] if official else None

    def _official(
        self, db: OrmSession, instance_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        """(base reference, solution.v2) of the official solution (D49): the latest
        finished solve (solved or infeasible) or accepted repair, else the committed
        ``solution.json`` (``COMMITTED``); None when there is neither."""
        latest = db.execute(
            select(SolveJob.id, SolveJob.solution)
            .where(
                SolveJob.instance_id == instance_id,
                or_(and_(SolveJob.kind == "solve", SolveJob.solution.is_not(None)),
                    SolveJob.accepted_at.is_not(None)),
            )
            .order_by(func.coalesce(SolveJob.accepted_at, SolveJob.ended_at).desc())
            .limit(1)
        ).first()
        if latest is not None:
            return latest.id, latest.solution
        committed = self.store.read(instance_id, "solution")
        if committed is None:
            return None
        check_contract("solution_v2", committed)
        return COMMITTED, committed

    @staticmethod
    def _accepted(db: OrmSession, instance_id: str) -> list[SolveJob]:
        """The accepted repairs whose change accumulates (D52) and is not cleared, in
        acceptance order."""
        rows = db.scalars(
            select(SolveJob)
            .where(SolveJob.instance_id == instance_id, SolveJob.kind == "repair",
                   SolveJob.accepted_at.is_not(None), SolveJob.cleared_at.is_(None))
            .order_by(SolveJob.accepted_at, SolveJob.id)
        )
        return [job for job in rows if job.params["change"]["kind"] in ACCUMULATED]

    def _built(
        self, db: OrmSession, instance_id: str, edge_list: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """*edge_list* with every accepted change applied (D52), and their job ids."""
        accepted = self._accepted(db, instance_id)
        for job in accepted:
            edge_list = apply_change(edge_list, job.params["change"])
        return edge_list, [job.id for job in accepted]

    def login(self, username: str, password: str) -> Actor | None:
        """The account's actor when the password matches, else None. Audited either way."""
        with OrmSession(self._engine) as db:
            user = db.scalar(select(User).where(User.username == username))
            ok = verify_password(password, user.password_hash if user else None)
            self._audit(db, username, "login", {"success": ok})
            db.commit()
            if not (ok and user):
                return None
            return Actor(user.username, user.role, user.faculty_ref, user.cohort_ref)

    def start_solve(
        self, instance_id: str, time_limit_s: float, max_moves: int, actor: str
    ) -> str | None:
        """Queue a solve of the instance's edge list: the job id, or None when the
        instance is unknown."""
        edge_list = self.edge_list(instance_id)
        if edge_list is None:
            return None
        with OrmSession(self._engine) as db:
            edge_list, built_with = self._built(db, instance_id, edge_list)
        params = {"time_limit_s": time_limit_s, "max_moves": max_moves}
        return self._start(instance_id, "solve", None, params, {}, actor, built_with,
                           solve_edge_list, edge_list, time_limit_s, max_moves)

    def start_repair(
        self, instance_id: str, change: dict[str, Any], time_limit_s: float, max_moves: int,
        actor: str,
    ) -> str | None:
        """Queue a repair of the instance's official solution for *change*, on the edge
        list with every accepted change (D52): the job id, or None when the instance is
        unknown. Raises :class:`BadChange` for an unknown id or slot, :class:`Conflict`
        when the official solution is not a solved one."""
        edge_list = self.edge_list(instance_id)
        if edge_list is None:
            return None
        try:
            apply_change(edge_list, change)
        except ValueError as exc:
            raise BadChange(str(exc)) from exc
        with OrmSession(self._engine) as db:
            official = self._official(db, instance_id)
            edge_list, built_with = self._built(db, instance_id, edge_list)
        if official is None or official[1]["status"] != "solved":
            raise Conflict("the instance has no solved official timetable to repair")
        base, solution = official
        params = {"time_limit_s": time_limit_s, "max_moves": max_moves, "change": change}
        # slots as [day, period] pairs keep the row inside audit_entry.detail's 1024 chars
        logged = {k: v for k, v in change.items() if k != "slots"}
        if "slots" in change:
            logged["slots"] = [[s["day"], s["period"]] for s in change["slots"]]
        return self._start(instance_id, "repair", base, params,
                           {"base": base, "change": logged}, actor, built_with,
                           repair_edge_list, edge_list, solution, change, time_limit_s,
                           max_moves)

    def _start(
        self, instance_id: str, kind: str, base: str | None, params: dict[str, Any],
        logged: dict[str, Any], actor: str, built_with: list[str], work: Callable[..., Any],
        *args: Any,
    ) -> str:
        """Audit and store a queued job of *kind*, then run ``work(*args, on_phase)``
        in the pool."""
        job_id = uuid.uuid4().hex
        detail = {
            "instance_id": instance_id,
            "time_limit_s": params["time_limit_s"],
            "job_id": job_id,
            **logged,
            "status": "queued",
            "started_at": _now(),
            "ended_at": None,
        }
        with OrmSession(self._engine) as db:  # audited before it runs: no unaudited job
            audit_id = self._audit(db, actor, kind, detail)
            db.add(SolveJob(id=job_id, instance_id=instance_id, requested_by=actor, kind=kind,
                            base=base, status="queued", params=params, audit_id=audit_id,
                            built_with=built_with))
            db.commit()
        on_phase = partial(
            _mark_running, self._engine.url.render_as_string(hide_password=False), job_id
        )
        future = self._pool.submit(work, *args, on_phase)
        future.add_done_callback(lambda f: self._job_done(job_id, f))
        return job_id

    def _job_done(self, job_id: str, future: Future[Any]) -> None:
        solution, error = None, None
        if future.cancelled():
            status, error = "error", "cancelled"
        elif (exc := future.exception()) is not None:
            status, error = "error", f"{type(exc).__name__}: {exc}"
        else:
            status, solution = future.result()
        with self._official_lock, OrmSession(self._engine) as db:
            job = db.get_one(SolveJob, job_id)
            job.status, job.error, job.ended_at = status, error, func.now()
            if solution is not None:  # assigning None would store JSON null, not SQL NULL
                job.solution = solution
            if job.audit_id is not None:
                self._finish_audit(db, job.audit_id, status)
            db.commit()

    def accept(self, job_id: str, actor: str) -> dict[str, Any] | None:
        """Make a solved repair the official solution (D49): the job, or None if unknown.
        Raises :class:`Conflict` unless it is a solved repair whose base is still the
        official solution (so a repair is accepted at most once)."""
        with self._official_lock, OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None:
                return None
            if job.kind != "repair" or job.status != "solved":
                raise Conflict("only a solved repair can be accepted")
            official = self._official(db, job.instance_id)
            if official is None or official[0] != job.base:
                raise Conflict("the timetable this repair started from is no longer official")
            job.accepted_at, job.accepted_by = func.now(), actor
            self._audit(db, actor, "accept",
                        {"instance_id": job.instance_id, "job_id": job_id, "base": job.base})
            db.commit()
        return self.job(job_id)

    @staticmethod
    def _change_view(job: SolveJob) -> dict[str, Any]:
        return {"job_id": job.id, "change": job.params["change"],
                "requested_by": job.requested_by, "accepted_by": job.accepted_by,
                "accepted_at": job.accepted_at}

    def changes(self, instance_id: str) -> list[dict[str, Any]] | None:
        """The accepted changes every solve and repair includes (D52), in acceptance
        order; None when the instance is unknown."""
        if self.store.path(instance_id, "edge_list") is None:
            return None
        with OrmSession(self._engine) as db:
            return [self._change_view(job) for job in self._accepted(db, instance_id)]

    def clear_changes(self, instance_id: str, actor: str) -> list[dict[str, Any]] | None:
        """Clear the accepted changes (D52), audited: the cleared ones, or None when the
        instance is unknown. The official solution stays what it is."""
        if self.store.path(instance_id, "edge_list") is None:
            return None
        with self._official_lock, OrmSession(self._engine) as db:
            accepted = self._accepted(db, instance_id)
            cleared = [self._change_view(job) for job in accepted]
            for job in accepted:
                job.cleared_at = func.now()
            # the count, not the ids: detail holds 1024 characters; the rows keep cleared_at
            self._audit(db, actor, "clear_changes",
                        {"instance_id": instance_id, "cleared": len(cleared)})
            db.commit()
        return cleared

    def base_solution(self, job_id: str) -> dict[str, Any] | None:
        """The solution.v2 a repair started from: the committed ``solution.json`` or its
        base job's solution. None for an unknown job or one that is not a repair."""
        with OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None or job.base is None:
                return None
            if job.base == COMMITTED:
                # shortcut: the committed file as it is now; it changes only by a commit
                return self.store.read(job.instance_id, "solution")
            return db.get_one(SolveJob, job.base).solution

    @staticmethod
    def _finish_audit(db: OrmSession, audit_id: int, status: str) -> None:
        """Complete a job's audit row with its final *status*."""
        entry = db.get_one(AuditEntry, audit_id)
        entry.detail = json.dumps(
            json.loads(entry.detail) | {"status": status, "ended_at": _now()}
        )

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
        """The job's kind, status, its phase while running and, once solved or infeasible,
        its solution; a repair's base and change, and when and by whom it was accepted;
        the accepted changes it was built with (D52). None if unknown."""
        with OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None:
                return None
            view: dict[str, Any] = {
                "id": job.id, "instance_id": job.instance_id, "kind": job.kind, **job.params,
                "status": job.status,
            }
            if job.kind == "repair":
                view["base"] = job.base
            if job.accepted_at is not None:
                view["accepted_at"], view["accepted_by"] = job.accepted_at, job.accepted_by
            if job.built_with is not None:
                view["built_with"] = job.built_with
            if job.status == "running":
                view["phase"] = job.phase
            if job.solution is not None:
                view["solution"] = job.solution
            if job.error is not None:
                view["error"] = job.error
            return view
