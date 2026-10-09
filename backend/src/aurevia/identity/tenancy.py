"""Tenant and membership management for the signed-in principal's own tenant.

Every query here runs inside the principal's row-level-security scope *and* filters on
``tenant_id`` explicitly: either layer alone would keep tenants apart, together a bug in one is
caught by the other. Rows from another tenant are reported as not found, never as forbidden,
so their existence is not revealed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import ConflictError, NotFoundError, PermissionDeniedError
from aurevia.identity.audit import record_audit_event
from aurevia.identity.dependencies import Principal
from aurevia.identity.models import (
    CustomRole,
    Membership,
    MembershipStatus,
    RefreshToken,
    Role,
    Tenant,
    User,
)
from aurevia.identity.permissions import Permission, parse_permissions, permissions_for


@dataclass(frozen=True)
class MemberView:
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime
    custom_role_id: uuid.UUID | None = None


class TenancyService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    async def current_tenant(self) -> Tenant:
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == self._principal.tenant_id)
        )
        if tenant is None:  # unreachable while the principal's membership is active
            raise NotFoundError("Tenant not found")
        return tenant

    async def list_members(self) -> list[MemberView]:
        rows = await self._session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == self._principal.tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Membership.created_at)
        )
        return [
            MemberView(
                membership_id=m.id,
                user_id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=Role(m.role),
                joined_at=m.created_at,
                custom_role_id=m.custom_role_id,
            )
            for m, u in rows.tuples()
        ]

    async def change_role(
        self,
        membership_id: uuid.UUID,
        new_role: Role,
        custom_role_id: uuid.UUID | None = None,
    ) -> None:
        target = await self._load_target(membership_id)
        old_role = Role(target.role)
        if custom_role_id is not None and new_role != Role.MEMBER:
            raise ConflictError(
                "Custom roles are given to members only", code="custom_role_needs_member"
            )
        if old_role == new_role and target.custom_role_id == custom_role_id:
            return
        self._check_may_manage(target_role=old_role, new_role=new_role)
        await self._check_within_own_permissions(target)
        new_permissions = permissions_for(new_role, await self._custom_permissions(custom_role_id))
        self._check_may_grant(new_permissions)
        if old_role == Role.OWNER:
            await self._ensure_another_owner(target.id)

        target.role = new_role
        target.custom_role_id = custom_role_id
        record_audit_event(
            self._session,
            tenant_id=self._principal.tenant_id,
            actor_user_id=self._principal.user_id,
            action="membership.role_changed",
            target_type="membership",
            target_id=target.id,
            details={
                "from": old_role.value,
                "to": new_role.value,
                "custom_role_id": str(custom_role_id) if custom_role_id else None,
            },
        )
        await self._session.commit()

    async def remove_member(self, membership_id: uuid.UUID) -> None:
        target = await self._load_target(membership_id)
        role = Role(target.role)
        self._check_may_manage(target_role=role, new_role=None)
        await self._check_within_own_permissions(target)
        if role == Role.OWNER:
            await self._ensure_another_owner(target.id)

        target.status = MembershipStatus.REMOVED
        # End the removed member's sessions in this tenant straight away.
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == target.user_id,
                RefreshToken.tenant_id == self._principal.tenant_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        record_audit_event(
            self._session,
            tenant_id=self._principal.tenant_id,
            actor_user_id=self._principal.user_id,
            action="membership.removed",
            target_type="membership",
            target_id=target.id,
            details={"role": role.value},
        )
        await self._session.commit()

    async def _load_target(self, membership_id: uuid.UUID) -> Membership:
        target = await self._session.scalar(
            select(Membership)
            .where(
                Membership.id == membership_id,
                Membership.tenant_id == self._principal.tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .with_for_update()
        )
        if target is None:
            raise NotFoundError("Member not found")
        return target

    def _check_may_manage(self, *, target_role: Role, new_role: Role | None) -> None:
        # Only owners may touch an owner or create one; admins manage admins and members.
        touches_owner = Role.OWNER in (target_role, new_role)
        if touches_owner and self._principal.role != Role.OWNER:
            raise PermissionDeniedError("Only an owner can change owners")

    async def _custom_permissions(
        self, custom_role_id: uuid.UUID | None
    ) -> frozenset[Permission] | None:
        if custom_role_id is None:
            return None
        custom = await self._session.scalar(
            select(CustomRole).where(
                CustomRole.id == custom_role_id,
                CustomRole.tenant_id == self._principal.tenant_id,
            )
        )
        if custom is None:
            raise NotFoundError("Role not found")
        return parse_permissions(custom.permissions)

    def _check_may_grant(self, permissions: frozenset[Permission]) -> None:
        # Nobody hands out rights they do not hold themselves.
        if not permissions <= self._principal.permissions:
            raise PermissionDeniedError("You cannot grant permissions you do not have")

    async def _check_within_own_permissions(self, target: Membership) -> None:
        # Nor manage someone who can do more than they can.
        current = permissions_for(
            Role(target.role), await self._custom_permissions(target.custom_role_id)
        )
        if not current <= self._principal.permissions:
            raise PermissionDeniedError("You cannot manage a member with more permissions")

    async def _ensure_another_owner(self, excluding: uuid.UUID) -> None:
        owner_ids = await self._session.scalars(
            select(Membership.id)
            .where(
                Membership.tenant_id == self._principal.tenant_id,
                Membership.role == Role.OWNER,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .with_for_update()
        )
        if not any(owner_id != excluding for owner_id in owner_ids):
            raise ConflictError("A tenant must keep at least one owner", code="last_owner")
