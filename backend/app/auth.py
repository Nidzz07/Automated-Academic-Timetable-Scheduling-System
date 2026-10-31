"""Authentication (S13b): scrypt password hashes and signed HS256 access tokens.

Passwords use ``hashlib.scrypt`` from the standard library: ``passlib[bcrypt]`` 1.7.4
fails against the bcrypt 5 that pip installs with it (dropped from requirements, S13d).
Tokens are PyJWT JWTs (S14r: python-jose had advisories no release fixes). A token
carries the username and role, so checking one needs no database round trip.

S14c (ROADMAP D50): it also carries the account's faculty or cohort link, if any, so
the UI can open on that timetable. Nothing is filtered by it: timetables are not secret.

S14r: failed logins are limited per username (:class:`LoginLimiter`), in this process.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from dotenv import load_dotenv

from backend.app.store import REPO
from db.models import UserRole

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 30.0
MIN_EXPIRE_MINUTES, MAX_EXPIRE_MINUTES = 5.0, 1440.0  # 5 minutes to one day
MIN_SECRET_LENGTH = 32  # an HS256 key shorter than its 256-bit output weakens it
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_S = 300.0


def hash_password(password: str) -> str:
    """``scrypt$n$r$p$salt$digest``, hex; a fresh random salt each call."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    n, r, p = _SCRYPT.values()
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


@cache
def _dummy_hash() -> str:
    return hash_password("")


def verify_password(password: str, stored: str | None) -> bool:
    """True when *password* matches *stored*. With no stored hash (an unknown user) it
    still spends one scrypt, so the response time does not reveal which usernames exist."""
    try:
        scheme, n, r, p, salt, digest = (stored or _dummy_hash()).split("$")
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(digest) // 2,
        )
    except ValueError:
        return False
    return stored is not None and scheme == "scrypt" and hmac.compare_digest(
        candidate.hex(), digest
    )


@dataclass(frozen=True)
class Actor:
    """Who is calling, as their token says."""

    username: str
    role: UserRole
    faculty_id: str | None = None
    cohort_id: str | None = None


@dataclass(frozen=True)
class AuthSettings:
    secret_key: str
    expire_minutes: float = DEFAULT_EXPIRE_MINUTES

    @classmethod
    def from_env(cls) -> AuthSettings:
        """``SECRET_KEY`` and ``ACCESS_TOKEN_EXPIRE_MINUTES`` from the environment, else
        from ``backend/.env``."""
        load_dotenv(REPO / "backend" / ".env")  # never overrides a variable already set
        secret = os.environ.get("SECRET_KEY", "")
        if len(secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"SECRET_KEY must be set (backend/.env) and at least {MIN_SECRET_LENGTH} "
                "characters long"
            )
        expire = os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES")
        if not expire:
            return cls(secret)
        try:
            minutes = float(expire)
        except ValueError:
            minutes = math.nan
        if not MIN_EXPIRE_MINUTES <= minutes <= MAX_EXPIRE_MINUTES:  # also refuses nan
            raise RuntimeError(
                f"ACCESS_TOKEN_EXPIRE_MINUTES must be a number from {MIN_EXPIRE_MINUTES:g} to "
                f"{MAX_EXPIRE_MINUTES:g}, not {expire!r}"
            )
        return cls(secret, minutes)


class TooManyAttempts(Exception):
    """Too many failed logins for this username (HTTP 429)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many failed sign-in attempts. Try again in a few minutes.")
        self.retry_after = retry_after


class LoginLimiter:
    """At most *limit* failed logins per username in any *window_s* seconds; a success
    clears the username's failures. Per username only: behind Render's proxy the client
    address uvicorn sees is the proxy's, and X-Forwarded-For can be forged by a client.

    shortcut: kept in this process's memory (one API process, D55); a restart forgets it.
    """

    def __init__(self, limit: int = MAX_FAILED_LOGINS, window_s: float = FAILED_LOGIN_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, username: str, now: float) -> list[float]:
        return [t for t in self._failures.get(username, []) if now - t < self.window_s]

    def check(self, username: str) -> None:
        """Raise :class:`TooManyAttempts` while *username* is over its limit."""
        with self._lock:
            now = self.clock()
            recent = self._recent(username, now)
            if len(recent) >= self.limit:
                raise TooManyAttempts(math.ceil(recent[-self.limit] + self.window_s - now))

    def failed(self, username: str) -> None:
        with self._lock:
            now = self.clock()
            # drop usernames whose failures all expired, so the table stays small
            self._failures = {u: kept for u in self._failures
                              if (kept := self._recent(u, now))}
            self._failures.setdefault(username, []).append(now)

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)


def issue_token(actor: Actor, settings: AuthSettings) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.expire_minutes)
    claims = {"sub": actor.username, "role": actor.role.value, "exp": expires,
              "faculty_id": actor.faculty_id, "cohort_id": actor.cohort_id}
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)


def read_token(token: str, settings: AuthSettings) -> Actor:
    """The token's actor. Raises ``jwt.InvalidTokenError`` (expired, bad signature,
    malformed), ``KeyError`` or ``ValueError`` (claims missing or not a role)."""
    claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    return Actor(claims["sub"], UserRole(claims["role"]), claims.get("faculty_id"),
                 claims.get("cohort_id"))
