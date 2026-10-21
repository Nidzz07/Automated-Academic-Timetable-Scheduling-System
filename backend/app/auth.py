"""Authentication (S13b): scrypt password hashes and signed HS256 access tokens.

Passwords use ``hashlib.scrypt`` from the standard library: ``passlib[bcrypt]`` 1.7.4
fails against the bcrypt 5 that pip installs with it (dropped from requirements, S13d).
Tokens are python-jose JWTs (already a dependency). A token carries the username
and role, so checking one needs no database round trip.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache

from dotenv import load_dotenv
from jose import jwt

from backend.app.store import REPO
from db.models import UserRole

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 30.0
MIN_SECRET_LENGTH = 32  # an HS256 key shorter than its 256-bit output weakens it
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


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
        return cls(secret, float(expire) if expire else DEFAULT_EXPIRE_MINUTES)


def issue_token(actor: Actor, settings: AuthSettings) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.expire_minutes)
    claims = {"sub": actor.username, "role": actor.role.value, "exp": expires}
    return jwt.encode(claims, settings.secret_key, algorithm=ALGORITHM)


def read_token(token: str, settings: AuthSettings) -> Actor:
    """The token's actor. Raises ``jose.JWTError`` (expired, bad signature, malformed),
    ``KeyError`` or ``ValueError`` (claims missing or not a role)."""
    claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    return Actor(claims["sub"], UserRole(claims["role"]))
