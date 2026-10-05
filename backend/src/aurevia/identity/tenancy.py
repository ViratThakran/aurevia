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
    Membership,
    MembershipStatus,
    RefreshToken,
    Role,
    Tenant,
    User,
)


@dataclass(frozen=True)
class MemberView:
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime


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
            )
            for m, u in rows.tuples()
        ]

    async def change_role(self, membership_id: uuid.UUID, new_role: Role) -> None:
        target = await self._load_target(membership_id)
        old_role = Role(target.role)
        if old_role == new_role:
            return
        self._check_may_manage(target_role=old_role, new_role=new_role)
        if old_role == Role.OWNER:
            await self._ensure_another_owner(target.id)

        target.role = new_role
        record_audit_event(
            self._session,
            tenant_id=self._principal.tenant_id,
            actor_user_id=self._principal.user_id,
            action="membership.role_changed",
            target_type="membership",
            target_id=target.id,
            details={"from": old_role.value, "to": new_role.value},
        )
        await self._session.commit()

    async def remove_member(self, membership_id: uuid.UUID) -> None:
        target = await self._load_target(membership_id)
        role = Role(target.role)
        self._check_may_manage(target_role=role, new_role=None)
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
