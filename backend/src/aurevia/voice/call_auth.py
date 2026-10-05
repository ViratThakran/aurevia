"""Per-call credentials for the voice worker.

When a browser call is set up, the backend mints a short-lived token bound to exactly one call
of one tenant and hands it to the voice worker through the LiveKit agent dispatch (server to
server; browsers never see it). The worker presents it on the internal call endpoints.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from aurevia.db.session import set_tenant_context
from aurevia.errors import AuthenticationError
from aurevia.identity.dependencies import SessionDep, SettingsDep
from aurevia.identity.security import JWT_ALGORITHM
from aurevia.logging import tenant_id_var

CALL_TOKEN_TYPE = "call"  # noqa: S105 - a token type label, not a secret
CALL_TOKEN_AUDIENCE = "aurevia-voice-worker"  # noqa: S105 - an audience label

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CallPrincipal:
    call_id: uuid.UUID
    tenant_id: uuid.UUID


def create_call_token(
    *, call_id: uuid.UUID, tenant_id: uuid.UUID, secret: str, ttl_seconds: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "typ": CALL_TOKEN_TYPE,
        "aud": CALL_TOKEN_AUDIENCE,
        "cid": str(call_id),
        "tid": str(tenant_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_call_token(token: str, *, secret: str) -> CallPrincipal:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=CALL_TOKEN_AUDIENCE,
            options={"require": ["exp", "iat", "aud", "cid", "tid", "typ"]},
        )
        if payload["typ"] != CALL_TOKEN_TYPE:
            raise AuthenticationError("Invalid or expired token")
        return CallPrincipal(call_id=uuid.UUID(payload["cid"]), tenant_id=uuid.UUID(payload["tid"]))
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc


async def get_call_principal(
    call_id: Annotated[uuid.UUID, Path()],
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CallPrincipal:
    if credentials is None or settings.jwt_secret is None:
        raise AuthenticationError()
    principal = decode_call_token(
        credentials.credentials, secret=settings.jwt_secret.get_secret_value()
    )
    if principal.call_id != call_id:
        # A token for one call never opens another, even within the same tenant.
        raise AuthenticationError("Invalid or expired token")
    await set_tenant_context(session, principal.tenant_id)
    tenant_id_var.set(str(principal.tenant_id))
    return principal


CallPrincipalDep = Annotated[CallPrincipal, Depends(get_call_principal)]
