"""Team management (Phase 8): custom roles and invitations, in the tenant's RLS scope.

Invitations are not emailed (there is no email provider yet): the inviter gets the token once
and shares the link. Only its SHA-256 hash is stored, and accepting is in ``IdentityService``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import ConflictError, NotFoundError, PermissionDeniedError
from aurevia.identity.audit import record_audit_event
from aurevia.identity.dependencies import Principal
from aurevia.identity.models import CustomRole, Invitation, Membership, MembershipStatus, Role
from aurevia.identity.permissions import Permission, parse_permissions, permissions_for
from aurevia.identity.security import new_refresh_token
from aurevia.identity.service import normalize_email

INVITATION_TTL = timedelta(days=7)


class TeamService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal
        self._tenant_id = principal.tenant_id

    # --- Custom roles ---------------------------------------------------------------

    async def list_roles(self) -> list[CustomRole]:
        rows = await self._session.scalars(
            select(CustomRole)
            .where(CustomRole.tenant_id == self._tenant_id)
            .order_by(CustomRole.name)
        )
        return list(rows)

    async def create_role(self, name: str, permissions: set[Permission]) -> CustomRole:
        self._check_may_grant(frozenset(permissions))
        role = CustomRole(
            tenant_id=self._tenant_id,
            name=name,
            permissions=sorted(p.value for p in permissions),
        )
        self._session.add(role)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A role with this name exists", code="role_name_taken") from exc
        self._audit("custom_role.created", role.id, {"name": name, "permissions": role.permissions})
        await self._session.commit()
        return role

    async def update_role(
        self, role_id: uuid.UUID, *, name: str | None, permissions: set[Permission] | None
    ) -> CustomRole:
        role = await self._get_role(role_id)
        # Changing a role changes everyone who holds it: the same no-escalation rule applies
        # to what it grants now and what it will grant.
        self._check_may_grant(parse_permissions(role.permissions))
        if permissions is not None:
            self._check_may_grant(frozenset(permissions))
            role.permissions = sorted(p.value for p in permissions)
        if name is not None:
            role.name = name
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A role with this name exists", code="role_name_taken") from exc
        self._audit(
            "custom_role.updated", role.id, {"name": role.name, "permissions": role.permissions}
        )
        await self._session.commit()
        return role

    async def delete_role(self, role_id: uuid.UUID) -> None:
        role = await self._get_role(role_id)
        self._check_may_grant(parse_permissions(role.permissions))
        holders = await self._session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == self._tenant_id,
                Membership.custom_role_id == role_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
        if holders:
            raise ConflictError("Members still hold this role", code="role_in_use")
        # Removed members may still point at the role; clear that before deleting it.
        await self._session.execute(
            update(Membership)
            .where(
                Membership.tenant_id == self._tenant_id,
                Membership.custom_role_id == role_id,
            )
            .values(custom_role_id=None)
        )
        await self._session.delete(role)
        self._audit("custom_role.deleted", role_id, {"name": role.name})
        await self._session.commit()

    # --- Invitations ----------------------------------------------------------------

    async def invite(
        self, email: str, role: Role, custom_role_id: uuid.UUID | None
    ) -> tuple[Invitation, str]:
        if custom_role_id is not None and role != Role.MEMBER:
            raise ConflictError(
                "Custom roles are given to members only", code="custom_role_needs_member"
            )
        if role == Role.OWNER and self._principal.role != Role.OWNER:
            raise PermissionDeniedError("Only an owner can invite an owner")
        custom = None
        if custom_role_id is not None:
            custom = parse_permissions((await self._get_role(custom_role_id)).permissions)
        self._check_may_grant(permissions_for(role, custom))
        token, token_hash = new_refresh_token()  # random URL-safe token and its SHA-256
        invitation = Invitation(
            tenant_id=self._tenant_id,
            email=normalize_email(email),
            role=role,
            custom_role_id=custom_role_id,
            token_hash=token_hash,
            invited_by_user_id=self._principal.user_id,
            expires_at=datetime.now(UTC) + INVITATION_TTL,
        )
        self._session.add(invitation)
        await self._session.flush()
        self._audit("invitation.created", invitation.id, {"role": role.value})
        await self._session.commit()
        return invitation, token

    async def list_invitations(self) -> list[Invitation]:
        rows = await self._session.scalars(
            select(Invitation)
            .where(
                Invitation.tenant_id == self._tenant_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
            .order_by(Invitation.created_at.desc())
        )
        return list(rows)

    async def revoke_invitation(self, invitation_id: uuid.UUID) -> None:
        invitation = await self._session.scalar(
            select(Invitation).where(
                Invitation.id == invitation_id, Invitation.tenant_id == self._tenant_id
            )
        )
        if invitation is None:
            raise NotFoundError("Invitation not found")
        if invitation.accepted_at is None and invitation.revoked_at is None:
            invitation.revoked_at = datetime.now(UTC)
            self._audit("invitation.revoked", invitation.id, None)
            await self._session.commit()

    # --- Helpers --------------------------------------------------------------------

    async def _get_role(self, role_id: uuid.UUID) -> CustomRole:
        role = await self._session.scalar(
            select(CustomRole).where(
                CustomRole.id == role_id, CustomRole.tenant_id == self._tenant_id
            )
        )
        if role is None:
            raise NotFoundError("Role not found")
        return role

    def _check_may_grant(self, permissions: frozenset[Permission]) -> None:
        if not permissions <= self._principal.permissions:
            raise PermissionDeniedError("You cannot grant permissions you do not have")

    def _audit(self, action: str, target_id: uuid.UUID, details: dict[str, object] | None) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=self._principal.user_id,
            action=action,
            target_type=action.split(".")[0],
            target_id=target_id,
            details=details,
        )
