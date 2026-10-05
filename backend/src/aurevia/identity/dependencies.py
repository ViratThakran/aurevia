"""FastAPI dependencies that turn a bearer token into a verified, tenant-scoped principal.

Every request re-checks the membership in the database, so removing a member or changing a
role takes effect immediately, not when the access token expires.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.config import Settings
from aurevia.db.session import get_session, set_tenant_context
from aurevia.errors import AuthenticationError, PermissionDeniedError
from aurevia.identity.models import (
    Membership,
    MembershipStatus,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)
from aurevia.identity.security import decode_access_token
from aurevia.logging import tenant_id_var, user_id_var

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    role: Role


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]


async def get_principal(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or settings.jwt_secret is None:
        raise AuthenticationError()
    claims = decode_access_token(
        credentials.credentials, secret=settings.jwt_secret.get_secret_value()
    )

    # The token is server-signed, but the membership is still verified against the database
    # inside the tenant's row-level-security scope before anything is trusted.
    await set_tenant_context(session, claims.tenant_id)
    role = await session.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.id == claims.membership_id,
            Membership.tenant_id == claims.tenant_id,
            Membership.user_id == claims.user_id,
            Membership.status == MembershipStatus.ACTIVE,
            User.status == UserStatus.ACTIVE,
            Tenant.status == TenantStatus.ACTIVE,
        )
    )
    if role is None:
        raise AuthenticationError("Invalid or expired token")

    tenant_id_var.set(str(claims.tenant_id))
    user_id_var.set(str(claims.user_id))
    return Principal(
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        membership_id=claims.membership_id,
        role=Role(role),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(*allowed: Role) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: PrincipalDep) -> Principal:
        if principal.role not in allowed:
            raise PermissionDeniedError("Your role does not allow this action")
        return principal

    return dependency


AdminDep = Annotated[Principal, Depends(require_role(Role.OWNER, Role.ADMIN))]
