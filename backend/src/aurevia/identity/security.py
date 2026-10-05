"""Password hashing and token primitives. No database access here."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from aurevia.errors import AuthenticationError

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a token type label, not a secret

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost the same time.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID


def create_access_token(
    claims: AccessClaims, *, secret: str, ttl_seconds: int, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "typ": ACCESS_TOKEN_TYPE,
        "sub": str(claims.user_id),
        "tid": str(claims.tenant_id),
        "mid": str(claims.membership_id),
        "iat": issued,
        "exp": issued + timedelta(seconds=ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> AccessClaims:
    """Return the claims or raise ``AuthenticationError``. Never reveals why it failed."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "tid", "mid", "typ"]},
        )
        if payload["typ"] != ACCESS_TOKEN_TYPE:
            raise AuthenticationError("Invalid or expired token")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            membership_id=uuid.UUID(payload["mid"]),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc


def new_refresh_token() -> tuple[str, str]:
    """Return ``(token, sha256_hex)``. Only the hash is ever stored."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
