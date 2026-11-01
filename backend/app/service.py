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

S14g: a repair (and the explanation of an infeasible one) never suggests relaxing a pin
that ``display.json`` marks as a lunch, coffee or other break, by its kind (D41). A repair
may substitute a session's teacher, only with one ``qualifications.json`` lists for the
session's subject and type (D53); accepted substitutions accumulate (D52). The substitutes
of a session are the qualified faculty free at its slot in the official solution.

S14i (ROADMAP D56): the official solution is always valid for the accepted changes in
force. A finished solve or accepted repair is official only if it was built with exactly
the changes in force when it finished or was accepted (else it is ``stale``: kept, never
official) and depends on no cleared change. A repair's time limit covers the whole job,
explanation included (S14k); an infeasible solve is explained as a repair is. The edge
lists jobs run on are served.

S14n: a faculty or room unavailability already in force (every slot held by an accepted,
uncleared change for the same faculty or room) is refused, never queued nor accepted again.

S14r: a job's error keeps the exception in the job row, the audit row and the server log;
clients other than an administrator get :data:`JOB_FAILED`. At most :data:`MAX_QUEUED`
jobs wait; failed logins are limited per username (:class:`backend.app.auth.LoginLimiter`).

S17b: ``CHRONOS_SOLVER_WORKERS`` sets the worker processes (default 2, at least 1). A worker
that dies (killed for memory, say) ends its job ``error`` with :data:`WORKER_STOPPED` and the
next job gets a new pool. Each job's end is logged on one line.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Collection
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from functools import cache, partial
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import Engine, and_, create_engine, func, or_, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool

from backend.app.auth import Actor, LoginLimiter, TooManyAttempts, verify_password
from backend.app.store import REPO, InstanceStore
from db.models import AuditEntry, SolveJob, User
from solver.backtracking import backtrack_solve
from solver.graph import build_conflict_graph
from solver.improve import MAX_MOVES, improve
from solver.mus import explain
from solver.repair import MAX_MOVES as REPAIR_MAX_MOVES
from solver.repair import apply_change, repair, substitute_candidates
from solver.validate import validate_solution

CONTRACTS_DIR = REPO / "contracts"
DEFAULT_TIME_LIMIT_S = 300.0  # the budget of the S12a real solve (solver/benchmarks/real_solve.py)
MAX_TIME_LIMIT_S = 1800.0
DEFAULT_MAX_MOVES = MAX_MOVES  # solver.improve's default, about 20 s on the real instance
MAX_MAX_MOVES = 2_000_000
DEFAULT_REPAIR_MAX_MOVES = REPAIR_MAX_MOVES  # solver.repair's default
COMMITTED = "committed"  # a repair's base when it started from the committed solution.json
# D52: the changes every later solve and repair includes; a move is not re-applied
ACCUMULATED = ("faculty_unavailable", "room_unavailable", "substitute_faculty")
BREAK_PIN_KINDS = ("lunch", "coffee", "break")  # display.json pin kinds never relaxed (D41)
# why a qualified teacher cannot take a session where it is (solver.validate kinds)
LEFT_OUT = {"FACULTY_CLASH": "busy", "PINNED_BLOCK": "busy",
            "FACULTY_UNAVAILABLE": "unavailable"}
IN_FORCE = "This change is already in force"
JOB_FAILED = "The solver failed. An administrator can see the details in the audit log."
WORKER_STOPPED = ("The solver process stopped before the job ended, possibly out of memory. "
                  "Try again.")
# job errors that carry no exception text
PLAIN_ERRORS = ("server restarted", "cancelled", WORKER_STOPPED)
DEFAULT_SOLVER_WORKERS = 2
MAX_QUEUED = 5  # jobs waiting for a pool worker; one more is refused (HTTP 429)
AUDIT_ERROR_CHARS = 400  # of the exception text, so the row stays within detail's 1024
log = logging.getLogger(__name__)
UNAVAILABLE_OF = {"faculty_unavailable": "faculty_id", "room_unavailable": "room_id"}


class ContractError(ValueError):
    """A payload does not conform to its contract schema."""


class BadChange(ValueError):
    """A repair change names an unknown faculty, room, session or slot (HTTP 422)."""


class Conflict(Exception):
    """The request does not fit the instance's current state (HTTP 409)."""


class Busy(Exception):
    """Too many jobs are already waiting (HTTP 429)."""


@cache
def _validator(contract: str) -> Draft202012Validator:
    path = CONTRACTS_DIR / f"{contract}.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def check_contract(contract: str, payload: Any) -> None:
    """Raise :class:`ContractError` unless *payload* conforms to ``contracts/<contract>``."""
    errors = [e.message for e in _validator(contract).iter_errors(payload)]
    if errors:
        raise ContractError(f"{contract}: {len(errors)} errors, first: {errors[0]}")


def _in_force(change: dict[str, Any], accepted: list[SolveJob]) -> bool:
    """*change* is a faculty or room unavailability every slot of which an *accepted* change
    of the same kind for the same faculty or room already holds (S14n)."""
    key = UNAVAILABLE_OF.get(change["kind"])
    if key is None:
        return False
    held = {(s["day"], s["period"]) for job in accepted
            if job.params["change"]["kind"] == change["kind"]
            and job.params["change"][key] == change[key]
            for s in job.params["change"]["slots"]}
    return {(s["day"], s["period"]) for s in change["slots"]} <= held


def solve_edge_list(
    edge_list: dict[str, Any],
    time_limit_s: float,
    max_moves: int = 0,
    protected: Collection[int] = (),
    on_phase: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Runs in a pool worker: (outcome, solution.v2 payload or None on a timeout).

    Backtracking, then, when solved and *max_moves* > 0, local search (seed 0) in what
    is left of *time_limit_s*; when infeasible, :func:`solver.mus.explain` in what is
    left of it, never suggesting a *protected* pin (S14i). *on_phase* hears ``search``,
    then ``improve``.
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
    if result.outcome == "infeasible":
        remaining = max(0.0, time_limit_s - (time.perf_counter() - started))
        solution = explain(edge_list, solution, protected=protected,
                           time_limit_s=remaining) or solution
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
    protected: Collection[int] = (),
    on_phase: Callable[[str], None] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Runs in a pool worker: (outcome, solution.v2 payload or None on a timeout).

    *time_limit_s* covers the whole :func:`solver.repair.repair` call, explanation
    included (S14k); running out of it with every session free is a timeout, never
    infeasible (D33), and in the explanation keeps its unfinished result. *protected* pins are
    never suggested as the relaxation. *on_phase* hears ``repair``.
    """
    if on_phase:
        on_phase("repair")
    try:
        repaired = repair(edge_list, solution, change, max_moves=max_moves,
                          time_limit_s=time_limit_s, protected=protected)
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


def solver_workers() -> int:
    """The solver worker processes: ``CHRONOS_SOLVER_WORKERS``, default 2. Each one holds
    an instance and its search in memory; Render's free instance (512 MB) runs 1."""
    workers = int(os.environ.get("CHRONOS_SOLVER_WORKERS") or DEFAULT_SOLVER_WORKERS)
    if workers < 1:
        raise ValueError(f"CHRONOS_SOLVER_WORKERS must be at least 1, not {workers}")
    return workers


def _clock(at: datetime | None) -> str:
    return at.isoformat(timespec="seconds") if at else "-"


class ChronosService:
    def __init__(
        self, store: InstanceStore, engine: Engine, max_workers: int | None = None
    ) -> None:
        self.store = store
        self._engine = engine  # users, the audit log and solve jobs
        self._workers = solver_workers() if max_workers is None else max_workers
        self._pool = ProcessPoolExecutor(max_workers=self._workers)
        self._pool_lock = threading.Lock()  # replacing a broken pool vs. submitting to it
        self._lock = threading.Lock()
        self._official_lock = threading.Lock()  # accepting a repair vs. a job ending
        self._queue_lock = threading.Lock()  # counting queued jobs vs. adding one
        self.logins = LoginLimiter()
        # instance id -> ((mtime_ns, size) of edge_list.json, the contract-checked payload)
        self._edge_lists: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        # shortcut: jobs run in this process's pool and live only in it, so this assumes one
        # API process per database (Render: exactly one instance, one worker); a second one
        # starting would fail the first one's live jobs here. Give jobs an owner id first.
        with OrmSession(engine) as db:
            unfinished = select(SolveJob).where(SolveJob.status.in_(("queued", "running")))
            for job in db.scalars(unfinished):
                log.warning("job %s %s: server restarted while %s (queued %s, started %s)",
                            job.id, job.kind, job.status, _clock(job.created_at),
                            _clock(job.started_at))
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
        """(base reference, solution.v2) of the official solution (D49, D56): the newest
        finished solve (solved or infeasible) or accepted repair that is not
        :meth:`_stale` and depends on no cleared change (its own included), else the
        committed ``solution.json`` (``COMMITTED``); None when there is neither."""
        finished = db.scalars(
            select(SolveJob)
            .where(
                SolveJob.instance_id == instance_id,
                or_(and_(SolveJob.kind == "solve", SolveJob.solution.is_not(None)),
                    SolveJob.accepted_at.is_not(None)),
            )
            .order_by(func.coalesce(SolveJob.accepted_at, SolveJob.ended_at).desc(),
                      SolveJob.id.desc())
        ).all()
        changes = self._accepted(db, instance_id, cleared=True)
        cleared = {c.id for c in changes if c.cleared_at is not None}
        for job in finished:
            if not ({job.id, *(job.built_with or [])} & cleared or self._stale(job, changes)):
                return job.id, job.solution
        committed = self.store.read(instance_id, "solution")
        if committed is None:
            return None
        check_contract("solution_v2", committed)
        return COMMITTED, committed

    @staticmethod
    def _stale(job: SolveJob, changes: list[SolveJob]) -> bool:
        """D56: *job* was built with other accepted *changes* than those in force when it
        finished (a solve) or was accepted (a repair), so it is never official."""
        at = job.accepted_at or job.ended_at
        in_force = [c.id for c in changes if c.id != job.id and c.accepted_at <= at
                    and (c.cleared_at is None or c.cleared_at > at)]
        return (job.built_with or []) != in_force  # no built_with: before S14f, none

    @staticmethod
    def _accepted(db: OrmSession, instance_id: str, cleared: bool = False) -> list[SolveJob]:
        """The accepted repairs whose change accumulates (D52) and is not cleared (with
        *cleared*, also those cleared), in acceptance order."""
        query = (select(SolveJob)
                 .where(SolveJob.instance_id == instance_id, SolveJob.kind == "repair",
                        SolveJob.accepted_at.is_not(None))
                 .order_by(SolveJob.accepted_at, SolveJob.id))
        if not cleared:
            query = query.where(SolveJob.cleared_at.is_(None))
        return [job for job in db.scalars(query) if job.params["change"]["kind"] in ACCUMULATED]

    def _built(
        self, db: OrmSession, instance_id: str, edge_list: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """*edge_list* with every accepted change applied (D52), and their job ids."""
        accepted = self._accepted(db, instance_id)
        for job in accepted:
            edge_list = apply_change(edge_list, job.params["change"])
        return edge_list, [job.id for job in accepted]

    def current_edge_list(self, instance_id: str) -> dict[str, Any] | None:
        """The committed edge list with every accepted change in force, exactly as solves
        and repairs build it (D52), contract-checked; None for an unknown instance."""
        committed = self.edge_list(instance_id)
        if committed is None:
            return None
        with OrmSession(self._engine) as db:
            edge_list, _ = self._built(db, instance_id, committed)
        check_contract("edge_list_v1", edge_list)
        return edge_list

    def job_edge_list(self, job_id: str) -> dict[str, Any] | None:
        """The edge list *job_id* ran on: the committed one with the changes it was built
        with and, for a repair, its own change; contract-checked. None for an unknown job
        or instance."""
        with OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None:
                return None
            # shortcut: the committed file as it is now; it changes only by a commit
            edge_list = self.edge_list(job.instance_id)
            if edge_list is None:
                return None
            for ref in job.built_with or []:
                edge_list = apply_change(edge_list, db.get_one(SolveJob, ref).params["change"])
            if job.kind == "repair":
                edge_list = apply_change(edge_list, job.params["change"])
        check_contract("edge_list_v1", edge_list)
        return edge_list

    def login(self, username: str, password: str) -> Actor | None:
        """The account's actor when the password matches, else None. Audited either way.
        Raises :class:`backend.app.auth.TooManyAttempts` (audited, password unchecked)
        while the username has too many recent failures."""
        try:
            self.logins.check(username)
        except TooManyAttempts:
            with OrmSession(self._engine) as db:
                self._audit(db, username, "login", {"success": False, "limited": True})
                db.commit()
            raise
        with OrmSession(self._engine) as db:
            user = db.scalar(select(User).where(User.username == username))
            ok = verify_password(password, user.password_hash if user else None)
            self._audit(db, username, "login", {"success": ok})
            db.commit()
            if not (ok and user):
                self.logins.failed(username)
                return None
            self.logins.succeeded(username)
            return Actor(user.username, user.role, user.faculty_ref, user.cohort_ref)

    def start_solve(
        self, instance_id: str, time_limit_s: float, max_moves: int, actor: str
    ) -> str | None:
        """Queue a solve of the instance's edge list: the job id, or None when the
        instance is unknown."""
        committed = self.edge_list(instance_id)
        if committed is None:
            return None
        with OrmSession(self._engine) as db:
            edge_list, built_with = self._built(db, instance_id, committed)
        params = {"time_limit_s": time_limit_s, "max_moves": max_moves}
        return self._start(instance_id, "solve", None, params, {}, actor, built_with,
                           solve_edge_list, edge_list, time_limit_s, max_moves,
                           self.protected(instance_id, committed))

    def start_repair(
        self, instance_id: str, change: dict[str, Any], time_limit_s: float, max_moves: int,
        actor: str,
    ) -> str | None:
        """Queue a repair of the instance's official solution for *change*, on the edge
        list with every accepted change (D52): the job id, or None when the instance is
        unknown. Raises :class:`BadChange` for an unknown id or slot, a substitute not
        qualified (D53) or a change already in force (S14n), :class:`Conflict` when the
        official solution is not a solved one."""
        committed = self.edge_list(instance_id)
        if committed is None:
            return None
        with OrmSession(self._engine) as db:
            official = self._official(db, instance_id)
            edge_list, built_with = self._built(db, instance_id, committed)
            accepted = self._accepted(db, instance_id)
        try:  # on the built edge list: a substitution may undo an accepted one
            changed = apply_change(edge_list, change)
        except ValueError as exc:
            raise BadChange(str(exc)) from exc
        if _in_force(change, accepted):
            raise BadChange(IN_FORCE)
        if change["kind"] == "substitute_faculty":
            session = next(s for s in changed["sessions"] if s["id"] == change["session_id"])
            if change["faculty_id"] not in self.qualified(instance_id, session):
                raise BadChange(f"{change['faculty_id']!r} is not listed for this session's "
                                "subject and type in qualifications.json (D53)")
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
                           max_moves, self.protected(instance_id, committed))

    def protected(self, instance_id: str, edge_list: dict[str, Any]) -> list[int]:
        """Indices of the pins ``display.json`` marks as a break (D41), by kind, never by
        shape; none without a ``display.json``. Accepted room changes append pins, so the
        indices hold in the built edge list too."""
        display = self.display(instance_id)
        if display is None:
            return []
        if len(display["pins"]) != len(edge_list["pinned_occupancy"]):
            raise ContractError(f"{instance_id}: display.json pins do not match "
                                "pinned_occupancy (D41)")
        return [i for i, pin in enumerate(display["pins"]) if pin["kind"] in BREAK_PIN_KINDS]

    def qualified(self, instance_id: str, session: dict[str, Any]) -> list[str]:
        """The faculty ``qualifications.json`` lists for *session*'s subject, for its
        session type or with none given (D53); none without that file."""
        sheet = self.store.read(instance_id, "qualifications") or {"subjects": {}}
        listed = sheet["subjects"].get(session["subject_id"], {"faculty": []})["faculty"]
        return [f["faculty_id"] for f in listed
                if f["session_type"] in (None, session["session_type"])]

    def substitutes(self, instance_id: str, session_id: str) -> dict[str, Any] | None:
        """Who can take *session_id* where it is in the official solution, on the edge list
        with every accepted change (D52): the qualified faculty (D53) that fit, best score
        change first (:func:`solver.repair.substitute_candidates`), and why each other one
        was left out (``not_in_instance``: listed, but without a ``faculty_availability``
        entry, so they cannot be checked). None for an unknown instance or session;
        :class:`Conflict` when the official solution is not a solved one valid for the
        accepted changes."""
        edge_list = self.edge_list(instance_id)
        if edge_list is None:
            return None
        with OrmSession(self._engine) as db:
            official = self._official(db, instance_id)
            edge_list, _ = self._built(db, instance_id, edge_list)
        session = next((s for s in edge_list["sessions"] if s["id"] == session_id), None)
        if session is None:
            return None
        if official is None or official[1]["status"] != "solved":
            raise Conflict("the instance has no solved official timetable")
        solution = official[1]
        qualified = self.qualified(instance_id, session)
        known = {a["faculty_id"] for a in edge_list["faculty_availability"]}
        try:
            candidates = substitute_candidates(edge_list, solution, session_id,
                                               [f for f in qualified if f in known])
        except ValueError as exc:  # the official solution is not valid for the changes
            raise Conflict(str(exc)) from exc
        fits = {c["faculty_id"] for c in candidates} | {session["faculty_id"]}
        left_out = []
        for fid in sorted(set(qualified) - fits):
            if fid not in known:
                left_out.append({"faculty_id": fid, "reasons": ["not_in_instance"],
                                 "violations": []})
                continue
            changed = apply_change(edge_list, {"kind": "substitute_faculty",
                                               "session_id": session_id, "faculty_id": fid})
            violations = [v.to_dict() for v in validate_solution(changed, solution)]
            left_out.append({"faculty_id": fid,
                             "reasons": sorted({LEFT_OUT.get(v["kind"], v["kind"])
                                                for v in violations}),
                             "violations": violations})
        return {"session_id": session_id, "faculty_id": session["faculty_id"],
                "candidates": candidates, "left_out": left_out}

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
        # audited before it runs: no unaudited job
        with self._queue_lock, OrmSession(self._engine) as db:
            queued = db.scalar(select(func.count()).select_from(SolveJob)
                               .where(SolveJob.status == "queued"))
            if queued >= MAX_QUEUED:
                raise Busy(f"{queued} jobs are already waiting. Try again when one has ended.")
            audit_id = self._audit(db, actor, kind, detail)
            db.add(SolveJob(id=job_id, instance_id=instance_id, requested_by=actor, kind=kind,
                            base=base, status="queued", params=params, audit_id=audit_id,
                            built_with=built_with))
            db.commit()
        on_phase = partial(
            _mark_running, self._engine.url.render_as_string(hide_password=False), job_id
        )
        try:
            future = self._submit(work, *args, on_phase)
        except Exception as exc:  # the queued row must still end, never wait for ever
            future = Future()
            future.set_exception(exc)
        future.add_done_callback(lambda f: self._job_done(job_id, f))
        return job_id

    def _submit(self, work: Callable[..., Any], *args: Any) -> Future[Any]:
        """Submit to the pool, first replacing it when a dead worker broke it."""
        with self._pool_lock:
            try:
                return self._pool.submit(work, *args)
            except BrokenProcessPool:
                log.warning("solver pool broken by a dead worker: starting a new one")
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = ProcessPoolExecutor(max_workers=self._workers)
                return self._pool.submit(work, *args)

    def _job_done(self, job_id: str, future: Future[Any]) -> None:
        solution, error = None, None
        if future.cancelled():
            status, error = "error", "cancelled"
        elif isinstance(exc := future.exception(), BrokenProcessPool):
            status, error = "error", WORKER_STOPPED
            log.error("job %s: %s", job_id, exc)
        elif exc is not None:
            status, error = "error", f"{type(exc).__name__}: {exc}"
            log.error("job %s failed", job_id, exc_info=exc)
        else:
            status, solution = future.result()
        with self._official_lock, OrmSession(self._engine) as db:
            job = db.get_one(SolveJob, job_id)
            job.status, job.error, job.ended_at = status, error, func.now()
            extra = {}
            if solution is not None:  # assigning None would store JSON null, not SQL NULL
                job.solution = solution
                in_force = [c.id for c in self._accepted(db, job.instance_id)]
                if job.kind == "solve" and (job.built_with or []) != in_force:
                    extra["stale"] = True  # D56: kept, never official
            if error is not None:  # the administrator's view of it (GET /audit)
                extra["error"] = error[:AUDIT_ERROR_CHARS]
            if job.audit_id is not None:
                self._finish_audit(db, job.audit_id, status, extra)
            db.commit()
            # the database's times, reloaded after the commit
            log.info("job %s %s: queued %s, started %s, ended %s, %.1f s, %s", job_id,
                     job.kind, _clock(job.created_at), _clock(job.started_at),
                     _clock(job.ended_at), (job.ended_at - job.created_at).total_seconds(),
                     status)

    def accept(self, job_id: str, actor: str) -> dict[str, Any] | None:
        """Make a solved repair the official solution (D49): the job, or None if unknown.
        Raises :class:`Conflict` unless it is a solved repair whose base is still the
        official solution (so a repair is accepted at most once), that was built with
        exactly the accepted changes in force (D56) and whose change is not already in
        force (S14n: a job queued before that guard at start)."""
        with self._official_lock, OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None:
                return None
            if job.kind != "repair" or job.status != "solved":
                raise Conflict("only a solved repair can be accepted")
            official = self._official(db, job.instance_id)
            if official is None or official[0] != job.base:
                raise Conflict("the timetable this repair started from is no longer official")
            accepted = self._accepted(db, job.instance_id)
            if (job.built_with or []) != [c.id for c in accepted]:
                raise Conflict("the accepted changes changed since this repair started (D56)")
            if _in_force(job.params["change"], accepted):
                raise Conflict(IN_FORCE)
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
        """Clear the accepted changes (D52), audited with the solution that is official
        after it (D56): the cleared ones, or None when the instance is unknown."""
        if self.store.path(instance_id, "edge_list") is None:
            return None
        with self._official_lock, OrmSession(self._engine) as db:
            accepted = self._accepted(db, instance_id)
            cleared = [self._change_view(job) for job in accepted]
            for job in accepted:
                job.cleared_at = func.now()
            db.flush()
            official = self._official(db, instance_id)
            # the count, not the ids: detail holds 1024 characters; the rows keep cleared_at
            self._audit(db, actor, "clear_changes",
                        {"instance_id": instance_id, "cleared": len(cleared),
                         "official": official[0] if official else None})
            db.commit()
        return cleared

    def restore_committed(self, instance_id: str, actor: str) -> str | None:
        """Make the committed ``solution.json`` official without solving (S14y): record it
        as one finished solve job, built with no accepted change and audited as a solve by
        *actor*: its id, or None when the instance has no edge list or no solution.json.
        Raises :class:`Conflict` while accepted changes are in force (D56: it was built
        with none), :class:`ContractError` or ValueError when the file does not conform or
        is not valid for the committed edge list."""
        edge_list = self.edge_list(instance_id)
        committed = self.store.read(instance_id, "solution")
        if edge_list is None or committed is None:
            return None
        check_contract("solution_v2", committed)
        if violations := validate_solution(edge_list, committed):
            raise ValueError(f"solution.json is not valid: {[v.to_dict() for v in violations]}")
        job_id, params, now = uuid.uuid4().hex, {"source": "solution.json"}, _now()
        with self._official_lock, OrmSession(self._engine) as db:
            if self._accepted(db, instance_id):
                raise Conflict("clear the accepted changes before restoring solution.json")
            audit_id = self._audit(db, actor, "solve", {
                "instance_id": instance_id, "job_id": job_id, **params, "status": "solved",
                "started_at": now, "ended_at": now})
            db.add(SolveJob(id=job_id, instance_id=instance_id, requested_by=actor,
                            kind="solve", status="solved", params=params, audit_id=audit_id,
                            built_with=[], solution=committed, started_at=func.now(),
                            ended_at=func.now()))
            db.commit()
        return job_id

    def base_solution(self, job_id: str) -> dict[str, Any] | None:
        """The solution.v2 a repair started from: the committed ``solution.json`` or its
        base job's solution. None for an unknown job or one that is not a repair."""
        with OrmSession(self._engine) as db:
            job = db.get(SolveJob, job_id)
            if job is None or job.base is None:
                return None
            if job.base == COMMITTED:
                # shortcut: the committed file as it is now; it changes only by a commit
                solution = self.store.read(job.instance_id, "solution")
            else:
                solution = db.get_one(SolveJob, job.base).solution
        if solution is not None:  # solution.json removed since: 404, as before
            check_contract("solution_v2", solution)
        return solution

    @staticmethod
    def _finish_audit(
        db: OrmSession, audit_id: int, status: str, extra: dict[str, Any] | None = None
    ) -> None:
        """Complete a job's audit row with its final *status* (and *extra* fields)."""
        entry = db.get_one(AuditEntry, audit_id)
        entry.detail = json.dumps(
            json.loads(entry.detail) | {"status": status, "ended_at": _now(), **(extra or {})}
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

    def job(self, job_id: str, details: bool = False) -> dict[str, Any] | None:
        """The job's kind, status, its phase while running and, once solved or infeasible,
        its solution; a repair's base and change, and when and by whom it was accepted;
        the accepted changes it was built with (D52); for a finished solve, whether it is
        stale (D56); its error, the exception text only with *details* (S14r). None if
        unknown."""
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
                if job.kind == "solve":
                    view["stale"] = self._stale(
                        job, self._accepted(db, job.instance_id, cleared=True))
            if job.error is not None:
                view["error"] = (job.error if details or job.error in PLAIN_ERRORS
                                 else JOB_FAILED)
            return view
