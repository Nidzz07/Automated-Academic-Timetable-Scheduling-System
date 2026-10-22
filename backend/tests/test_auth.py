"""S13b: login, tokens, roles on every route, the audit log, the user CLI and the
edge-list cache. Runs on a scratch LOCAL Postgres (conftest.py); test passwords only.
"""

from __future__ import annotations

import getpass
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from backend.app import create_user
from backend.app import service as service_module
from backend.app.auth import (
    Actor,
    AuthSettings,
    hash_password,
    issue_token,
    read_token,
    verify_password,
)
from backend.app.main import create_app
from backend.app.service import ChronosService
from backend.app.store import INSTANCES_DIR, InstanceStore
from backend.tests.conftest import AUTH, bearer
from db.models import AuditEntry, User, UserRole
from solver.benchmarks.synthetic import PRESETS, generate

REAL = "even-2025-26"
ROLES = [r.value for r in UserRole]
PASSWORD = "test-password-not-real"


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    with OrmSession(eng) as db:
        stored = hash_password(PASSWORD)
        db.add_all(
            User(username=f"auth-{role}", password_hash=stored, role=UserRole(role))
            for role in ROLES
        )
        db.commit()
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def client(database_url: str, engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(INSTANCES_DIR, database_url=database_url, auth=AUTH)) as c:
        yield c


def audit_rows(engine: Engine, actor: str, action: str) -> list[AuditEntry]:
    with OrmSession(engine) as db:
        return list(db.scalars(
            select(AuditEntry).where(AuditEntry.actor == actor, AuditEntry.action == action)
            .order_by(AuditEntry.id)
        ))


def solve(client: TestClient, username: str, role: str = "coordinator") -> dict:
    """Start a 1 ms solve of the real instance and wait for the job to end."""
    headers = bearer(role, username)
    accepted = client.post(f"/instances/{REAL}/solve", json={"time_limit_s": 0.001},
                           headers=headers)
    assert accepted.status_code == 202
    deadline = time.monotonic() + 120
    while (job := client.get(f"/jobs/{accepted.json()['job_id']}", headers=headers).json())[
        "status"
    ] in ("queued", "running"):
        assert time.monotonic() < deadline, job
        time.sleep(0.05)
    return job


class TestPasswords:
    def test_round_trip_and_salted(self) -> None:
        stored = hash_password(PASSWORD)
        assert verify_password(PASSWORD, stored)
        assert not verify_password(PASSWORD + "x", stored)
        assert PASSWORD not in stored
        assert hash_password(PASSWORD) != stored

    @pytest.mark.parametrize("stored", [None, "", "bcrypt$x", "scrypt$1$2$3$zz$zz"])
    def test_nothing_else_verifies(self, stored: str | None) -> None:
        assert not verify_password(PASSWORD, stored)


class TestLogin:
    def test_ok(self, client: TestClient, engine: Engine) -> None:
        response = client.post("/auth/login", json={"username": "auth-coordinator",
                                                    "password": PASSWORD})
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer" and body["role"] == "coordinator"
        claims = jwt.get_unverified_claims(body["access_token"])
        assert claims["sub"] == "auth-coordinator" and claims["role"] == "coordinator"
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        assert client.get("/instances", headers=headers).status_code == 200
        # D50: no faculty or cohort link on this account
        assert body["faculty_id"] is None and body["cohort_id"] is None
        assert claims["faculty_id"] is None and claims["cohort_id"] is None

    def test_a_linked_token_reads_back(self) -> None:
        actor = Actor("x", UserRole.STUDENT, cohort_id="coh-se-a")
        assert read_token(issue_token(actor, AUTH), AUTH) == actor

    @pytest.mark.parametrize("username", ["auth-student", "nobody"])
    def test_bad_password_or_unknown_user(self, client: TestClient, username: str) -> None:
        response = client.post("/auth/login", json={"username": username, "password": "wrong"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize("body", [{}, {"username": "", "password": "x"},
                                      {"username": "x" * 65, "password": "x"}])
    def test_malformed(self, client: TestClient, body: dict) -> None:
        assert client.post("/auth/login", json=body).status_code == 422

    def test_every_attempt_is_audited_without_the_password(
        self, client: TestClient, engine: Engine
    ) -> None:
        client.post("/auth/login", json={"username": "auth-faculty", "password": PASSWORD})
        client.post("/auth/login", json={"username": "auth-faculty", "password": "guess-1"})
        rows = audit_rows(engine, "auth-faculty", "login")
        assert [json.loads(r.detail) for r in rows] == [{"success": True}, {"success": False}]
        assert all(r.timestamp is not None for r in rows)
        assert not any(PASSWORD in r.detail or "guess-1" in r.detail for r in rows)


class TestTokens:
    def test_expired(self, client: TestClient) -> None:
        expired = issue_token(Actor("x", UserRole.ADMINISTRATOR),
                              AuthSettings(AUTH.secret_key, expire_minutes=-1))
        assert client.get("/instances", headers={"Authorization": f"Bearer {expired}"}
                          ).status_code == 401

    @pytest.mark.parametrize("header", [
        "Bearer not-a-jwt",
        "Basic " + "x" * 20,
        "Bearer " + issue_token(Actor("x", UserRole.ADMINISTRATOR),
                                AuthSettings("another-secret-" + "1" * 32)),
        "Bearer " + jwt.encode(
            {"sub": "x", "role": "dean", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            AUTH.secret_key, algorithm="HS256"),
        "Bearer " + jwt.encode(
            {"sub": "x", "role": "administrator",
             "exp": datetime.now(UTC) + timedelta(minutes=5)},
            AUTH.secret_key, algorithm="HS512"),
    ], ids=["malformed", "not-bearer", "wrong-secret", "unknown-role", "wrong-algorithm"])
    def test_invalid(self, client: TestClient, header: str) -> None:
        response = client.get("/instances", headers={"Authorization": header})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_settings_refuse_a_short_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "short")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            AuthSettings.from_env()

    def test_settings_read_the_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_KEY", "s" * 32)
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "7")
        assert AuthSettings.from_env() == AuthSettings("s" * 32, 7.0)


@pytest.fixture(scope="module")
def job_id(client: TestClient) -> str:
    return solve(client, "matrix-admin", "administrator")["id"]


READ = ["/instances", f"/instances/{REAL}/edge-list", f"/instances/{REAL}/display",
        f"/instances/{REAL}/anomalies", f"/instances/{REAL}/solution",
        f"/instances/{REAL}/changes", "/jobs/{job}"]
EXPECTED = {
    # route -> role -> status
    **{("GET", path): dict.fromkeys(ROLES, 200) for path in READ},
    ("POST", f"/instances/{REAL}/solve"): {
        "administrator": 202, "coordinator": 202, "faculty": 403, "student": 403},
    ("GET", "/audit"): {"administrator": 200, "coordinator": 403, "faculty": 403,
                        "student": 403},
    ("DELETE", f"/instances/{REAL}/changes"): {
        "administrator": 200, "coordinator": 403, "faculty": 403, "student": 403},
}


class TestRoles:
    @pytest.mark.parametrize("route", EXPECTED, ids=" ".join)
    @pytest.mark.parametrize("caller", [None, *ROLES])
    def test_every_role_on_every_route(
        self, client: TestClient, job_id: str, route: tuple[str, str], caller: str | None
    ) -> None:
        method, path = route
        response = client.request(
            method, path.format(job=job_id),
            headers=bearer(caller) if caller else {},
            json={"time_limit_s": 0.001} if method == "POST" else None,
        )
        assert response.status_code == (EXPECTED[route][caller] if caller else 401), (
            response.text
        )

    def test_public_routes_need_no_token(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200
        response = client.post("/auth/login", json={"username": "auth-student",
                                                    "password": PASSWORD})
        assert response.status_code == 200


class TestSolveAudit:
    def test_one_row_per_solve_with_its_outcome(self, client: TestClient, engine: Engine) -> None:
        job = solve(client, "audit-coordinator")
        deadline = time.monotonic() + 30  # the row is completed by the job's done callback
        while (detail := json.loads(audit_rows(engine, "audit-coordinator", "solve")[0].detail)
               )["status"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert len(audit_rows(engine, "audit-coordinator", "solve")) == 1
        assert detail.pop("started_at") <= detail.pop("ended_at")
        assert detail == {"instance_id": REAL, "time_limit_s": 0.001, "job_id": job["id"],
                          "status": job["status"]}

        listed = client.get("/audit", headers=bearer("administrator")).json()
        entry = next(e for e in listed if e["actor"] == "audit-coordinator")
        assert entry["action"] == "solve" and entry["detail"]["job_id"] == job["id"]

    def test_a_forbidden_solve_is_not_queued(self, client: TestClient, engine: Engine) -> None:
        client.post(f"/instances/{REAL}/solve", headers=bearer("student", "audit-student"))
        assert audit_rows(engine, "audit-student", "solve") == []

    def test_audit_limit(self, client: TestClient) -> None:
        headers = bearer("administrator")
        assert len(client.get("/audit?limit=1", headers=headers).json()) == 1
        assert client.get("/audit?limit=0", headers=headers).status_code == 422


class TestCreateUserCli:
    def answers(self, monkeypatch: pytest.MonkeyPatch, *typed: str) -> None:
        it = iter(typed)
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(it))

    def test_creates_a_user_who_can_log_in(
        self, client: TestClient, database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", database_url)
        self.answers(monkeypatch, "cli-pass-123", "cli-pass-123")
        assert create_user.main(["cli-faculty", "--role", "faculty"]) == 0
        response = client.post("/auth/login", json={"username": "cli-faculty",
                                                    "password": "cli-pass-123"})
        assert response.json()["role"] == "faculty"

        self.answers(monkeypatch, "cli-pass-123", "cli-pass-123")
        assert create_user.main(["cli-faculty", "--role", "student"]) == 1  # exists

    @pytest.mark.parametrize("typed", [("short", "short"), ("long-enough", "different")])
    def test_refuses_a_bad_password(
        self, database_url: str, monkeypatch: pytest.MonkeyPatch, typed: tuple[str, str]
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", database_url)
        self.answers(monkeypatch, *typed)
        assert create_user.main(["cli-nobody", "--role", "student"]) == 1

    @pytest.mark.parametrize("link, value, claim", [
        ("--faculty", "fac-kailas-devadkar", "faculty_id"),
        ("--cohort", "coh-se-a", "cohort_id"),
    ])
    def test_links_an_account(
        self, client: TestClient, database_url: str, monkeypatch: pytest.MonkeyPatch,
        link: str, value: str, claim: str,
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", database_url)
        self.answers(monkeypatch, "cli-pass-123", "cli-pass-123")
        username = f"cli-link{link}"
        assert create_user.main([username, "--role", "faculty", link, value]) == 0
        body = client.post("/auth/login", json={"username": username,
                                                "password": "cli-pass-123"}).json()
        assert body[claim] == value
        assert jwt.get_unverified_claims(body["access_token"])[claim] == value

    @pytest.mark.parametrize("args", [["--faculty", "fac-nobody"], ["--cohort", "coh-nobody"],
                                      ["--faculty", "coh-se-a"]])
    def test_refuses_an_id_not_in_the_real_instance(
        self, engine: Engine, database_url: str, monkeypatch: pytest.MonkeyPatch,
        args: list[str],
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", database_url)
        self.answers(monkeypatch, "cli-pass-123", "cli-pass-123")
        assert create_user.main(["cli-unlinked", "--role", "student", *args]) == 1
        with OrmSession(engine) as db:
            assert db.scalar(select(User).where(User.username == "cli-unlinked")) is None

    def test_one_link_at_most(self, engine: Engine) -> None:
        with pytest.raises(SystemExit):
            create_user.main(["cli-both", "--role", "student", "--faculty",
                              "fac-kailas-devadkar", "--cohort", "coh-se-a"])
        with OrmSession(engine) as db, pytest.raises(IntegrityError, match="ck_app_user_one_link"):
            db.add(User(username="db-both", password_hash="scrypt$h", role=UserRole.STUDENT,
                        faculty_ref="fac-kailas-devadkar", cohort_ref="coh-se-a"))
            db.commit()

    def test_refuses_a_remote_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@db.example.com/x")
        monkeypatch.delenv("CHRONOS_ALLOW_REMOTE_DB", raising=False)
        self.answers(monkeypatch, "long-enough", "long-enough")
        with pytest.raises(SystemExit, match="not local"):
            create_user.main(["cli-remote", "--role", "student"])


def test_edge_list_cache_refreshes_when_the_file_changes(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "x").mkdir()
    path = tmp_path / "x" / "edge_list.json"
    first, second = generate(PRESETS["small"], 1), generate(PRESETS["small"], 2)
    assert first != second
    path.write_text(json.dumps(first), encoding="utf-8")
    checked: list[str] = []
    check = service_module.check_contract
    monkeypatch.setattr(
        service_module, "check_contract",
        lambda contract, payload: (checked.append(contract), check(contract, payload)),
    )
    engine = create_engine(database_url)
    service = ChronosService(InstanceStore(tmp_path), engine)
    try:
        assert service.edge_list("x") == first
        assert service.edge_list("x") == first
        assert checked == ["edge_list_v1"]  # the second read came from the cache

        path.write_text(json.dumps(second), encoding="utf-8")
        mtime = path.stat().st_mtime_ns + 10**9  # a distinct mtime even on a coarse clock
        os.utime(path, ns=(mtime, mtime))
        assert service.edge_list("x") == second
        assert checked == ["edge_list_v1"] * 2
    finally:
        service.close()
        engine.dispose()
