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
    CustomRole,
    Membership,
    MembershipStatus,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)
from aurevia.identity.permissions import Permission, parse_permissions, permissions_for
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
    permissions: frozenset[Permission] = frozenset()
    is_platform_admin: bool = False

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


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
    row = (
        await session.execute(
            select(Membership.role, CustomRole.permissions, User.is_platform_admin)
            .join(User, User.id == Membership.user_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .outerjoin(CustomRole, CustomRole.id == Membership.custom_role_id)
            .where(
                Membership.id == claims.membership_id,
                Membership.tenant_id == claims.tenant_id,
                Membership.user_id == claims.user_id,
                Membership.status == MembershipStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )
    ).first()
    if row is None:
        raise AuthenticationError("Invalid or expired token")
    role = Role(row[0])
    custom = parse_permissions(row[1]) if row[1] is not None else None

    tenant_id_var.set(str(claims.tenant_id))
    user_id_var.set(str(claims.user_id))
    return Principal(
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        membership_id=claims.membership_id,
        role=role,
        permissions=permissions_for(role, custom),
        is_platform_admin=bool(row[2]),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(*allowed: Role) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: PrincipalDep) -> Principal:
        if principal.role not in allowed:
            raise PermissionDeniedError("Your role does not allow this action")
        return principal

    return dependency


AdminDep = Annotated[Principal, Depends(require_role(Role.OWNER, Role.ADMIN))]


def require_permission(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: PrincipalDep) -> Principal:
        if not principal.can(permission):
            raise PermissionDeniedError(
                "You do not have permission for this action",
                details={"permission": permission.value},
            )
        return principal

    return dependency


async def _platform_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_platform_admin:
        raise PermissionDeniedError("Aurevia platform administrators only")
    return principal


CallsDep = Annotated[Principal, Depends(require_permission(Permission.CALLS_PLACE))]
LeadsManageDep = Annotated[Principal, Depends(require_permission(Permission.LEADS_MANAGE))]
PrivacyDep = Annotated[Principal, Depends(require_permission(Permission.LEADS_PRIVACY))]
CampaignsDep = Annotated[Principal, Depends(require_permission(Permission.CAMPAIGNS_MANAGE))]
AgentsDep = Annotated[Principal, Depends(require_permission(Permission.AGENTS_MANAGE))]
NumbersDep = Annotated[Principal, Depends(require_permission(Permission.NUMBERS_MANAGE))]
ComplianceDep = Annotated[Principal, Depends(require_permission(Permission.COMPLIANCE_MANAGE))]
TeamDep = Annotated[Principal, Depends(require_permission(Permission.TEAM_MANAGE))]
AuditDep = Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))]
AnalyticsDep = Annotated[Principal, Depends(require_permission(Permission.ANALYTICS_READ))]
PlatformAdminDep = Annotated[Principal, Depends(_platform_admin)]
