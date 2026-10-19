"""Service layer (S13a): the only backend module that calls the solver.

Solves run in a process pool, so the API never blocks on a search. A job ends
``solved`` or ``infeasible`` with its solution.v2 payload, ``timeout`` with none
(ROADMAP D33: a timeout is a job status, never an infeasible solution) or
``error``. Every payload served is checked against its contract schema first.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator

from backend.app.store import REPO, InstanceStore
from solver.backtracking import backtrack_solve
from solver.graph import build_conflict_graph
from solver.validate import validate_solution

CONTRACTS_DIR = REPO / "contracts"
DEFAULT_TIME_LIMIT_S = 300.0  # the budget of the S12a real solve (solver/benchmarks/real_solve.py)
MAX_TIME_LIMIT_S = 1800.0


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
    edge_list: dict[str, Any], time_limit_s: float
) -> tuple[str, dict[str, Any] | None]:
    """Runs in a pool worker: (outcome, solution.v2 payload or None on a timeout)."""
    graph = build_conflict_graph(edge_list)
    started = time.perf_counter()
    result = backtrack_solve(graph, edge_list, time_limit_s=time_limit_s)
    runtime_ms = (time.perf_counter() - started) * 1000
    if result.outcome == "timeout":
        return "timeout", None
    solution = result.to_solution_v2_dict(runtime_ms=runtime_ms)
    if result.solved and (violations := validate_solution(edge_list, solution)):
        raise RuntimeError(f"solved but invalid: {[v.to_dict() for v in violations]}")
    check_contract("solution_v2", solution)
    return result.outcome, solution


@dataclass
class Job:
    id: str
    instance_id: str
    time_limit_s: float
    requested_by: str | None  # S13b audit reads this
    future: Future[tuple[str, dict[str, Any] | None]]


class ChronosService:
    def __init__(self, store: InstanceStore, max_workers: int = 2) -> None:
        self.store = store
        self._pool = ProcessPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        # shortcut: jobs and latest solutions live in memory and die with the process;
        # S13 stores them in the database.
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        # waits for solves already running (at most their time budget)
        self._pool.shutdown(cancel_futures=True)

    def instance_ids(self) -> list[str]:
        return self.store.ids()

    def edge_list(self, instance_id: str) -> dict[str, Any] | None:
        edge_list = self.store.read(instance_id, "edge_list")
        if edge_list is not None:
            check_contract("edge_list_v1", edge_list)
        return edge_list

    def display(self, instance_id: str) -> Any | None:
        return self.store.read(instance_id, "display")  # D41 sidecar: no contract

    def anomalies(self, instance_id: str) -> Any | None:
        return self.store.read(instance_id, "anomalies")  # no contract

    def solution(self, instance_id: str) -> dict[str, Any] | None:
        """The latest solve's solution.v2 here, else the committed ``solution.json``."""
        with self._lock:
            latest = self._latest.get(instance_id)
        if latest is None:
            latest = self.store.read(instance_id, "solution")
            if latest is not None:
                check_contract("solution_v2", latest)
        return latest

    def start_solve(
        self, instance_id: str, time_limit_s: float, actor: str | None
    ) -> Job | None:
        """Queue a solve of the instance's edge list; None when the instance is unknown."""
        edge_list = self.edge_list(instance_id)
        if edge_list is None:
            return None
        future = self._pool.submit(solve_edge_list, edge_list, time_limit_s)
        job = Job(uuid.uuid4().hex, instance_id, time_limit_s, actor, future)
        with self._lock:
            self._jobs[job.id] = job
        future.add_done_callback(lambda f: self._store_solution(instance_id, f))
        return job

    def _store_solution(self, instance_id: str, future: Future[Any]) -> None:
        if future.cancelled() or future.exception() is not None:
            return
        _, solution = future.result()
        if solution is not None:
            with self._lock:
                self._latest[instance_id] = solution

    def job(self, job_id: str) -> dict[str, Any] | None:
        """The job's status and, once solved or infeasible, its solution; None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        view: dict[str, Any] = {
            "id": job.id,
            "instance_id": job.instance_id,
            "time_limit_s": job.time_limit_s,
        }
        f = job.future
        if not f.done():
            view["status"] = "running" if f.running() else "queued"
        elif f.cancelled():
            view |= {"status": "error", "error": "cancelled"}
        elif (exc := f.exception()) is not None:
            view |= {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        else:
            view["status"], solution = f.result()
            if solution is not None:
                view["solution"] = solution
        return view
