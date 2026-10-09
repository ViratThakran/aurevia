"""Authentication flows: signup, login, refresh-token rotation, logout.

Tenant identity is always derived here, on the server, from an active membership. It is never
taken from a client-supplied ``tenant_id`` without checking that membership.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.config import Settings
from aurevia.db.session import set_tenant_context, set_user_context
from aurevia.errors import (
    AureviaError,
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
)
from aurevia.identity.audit import record_audit_event
from aurevia.identity.models import (
    Invitation,
    Membership,
    MembershipStatus,
    RefreshToken,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
)
from aurevia.identity.security import (
    AccessClaims,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)

INVALID_CREDENTIALS = "Invalid email or password"
INVALID_INVITATION = "This invitation is invalid, expired or already used"
MIN_NEW_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "tenant"
    return f"{base}-{secrets.token_hex(3)}"


def _now() -> datetime:
    return datetime.now(UTC)


class IdentityService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        if settings.jwt_secret is None:
            raise RuntimeError("jwt_secret is not configured")
        self._session = session
        self._settings = settings
        self._jwt_secret = settings.jwt_secret.get_secret_value()

    async def signup(
        self, *, email: str, password: str, full_name: str | None, tenant_name: str
    ) -> TokenPair:
        email = normalize_email(email)
        if await self._find_user(email) is not None:
            raise ConflictError("An account with this email already exists", code="email_taken")

        tenant_id = uuid.uuid4()
        await set_tenant_context(self._session, tenant_id)
        tenant = Tenant(id=tenant_id, name=tenant_name, slug=_slugify(tenant_name))
        user = User(email=email, password_hash=hash_password(password), full_name=full_name)
        self._session.add_all([tenant, user])
        await self._session.flush()
        membership = Membership(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER)
        self._session.add(membership)
        await self._session.flush()

        record_audit_event(
            self._session,
            tenant_id=tenant.id,
            actor_user_id=user.id,
            action="tenant.created",
            target_type="tenant",
            target_id=tenant.id,
        )
        tokens = await self._issue(user.id, tenant.id, membership.id, family_id=None)
        try:
            await self._session.commit()
        except IntegrityError as exc:  # concurrent signup with the same email
            await self._session.rollback()
            raise ConflictError(
                "An account with this email already exists", code="email_taken"
            ) from exc
        return tokens

    async def login(self, *, email: str, password: str, tenant_id: uuid.UUID | None) -> TokenPair:
        user = await self._find_user(normalize_email(email))
        if not verify_password(user.password_hash if user else None, password):
            raise AuthenticationError(INVALID_CREDENTIALS)
        assert user is not None  # noqa: S101 - verify_password is False for a missing user
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError(INVALID_CREDENTIALS)

        await set_user_context(self._session, user.id)
        rows = (
            await self._session.execute(
                select(Membership, Tenant)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(
                    Membership.user_id == user.id,
                    Membership.status == MembershipStatus.ACTIVE,
                    Tenant.status == TenantStatus.ACTIVE,
                )
                .order_by(Tenant.name)
            )
        ).all()
        if tenant_id is not None:
            rows = [row for row in rows if row.Membership.tenant_id == tenant_id]
        if not rows:
            raise PermissionDeniedError("No active membership for this account")
        if len(rows) > 1:
            raise ConflictError(
                "Choose a tenant to sign in to",
                code="tenant_selection_required",
                details=[{"tenant_id": str(t.id), "name": t.name} for _, t in rows],
            )
        membership = rows[0].Membership

        await set_tenant_context(self._session, membership.tenant_id)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = _now()
        record_audit_event(
            self._session,
            tenant_id=membership.tenant_id,
            actor_user_id=user.id,
            action="user.logged_in",
            target_type="user",
            target_id=user.id,
        )
        tokens = await self._issue(user.id, membership.tenant_id, membership.id, family_id=None)
        await self._session.commit()
        return tokens

    async def accept_invitation(
        self, *, token: str, password: str, full_name: str | None
    ) -> TokenPair:
        """Join a tenant with an invitation. A new account is created for a new email; an
        existing account must prove itself with its password."""
        row = (
            await self._session.execute(
                text("SELECT invitation_id, tenant_id FROM resolve_invitation(:hash)"),
                {"hash": hash_refresh_token(token)},
            )
        ).first()
        await self._session.commit()  # ends the lookup transaction
        if row is None:
            raise AuthenticationError(INVALID_INVITATION)
        invitation_id, tenant_id = row[0], row[1]
        await set_tenant_context(self._session, tenant_id)
        invitation = await self._session.scalar(
            select(Invitation).where(Invitation.id == invitation_id).with_for_update()
        )
        now = _now()
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
        ):
            raise AuthenticationError(INVALID_INVITATION)

        user = await self._find_user(invitation.email)
        if user is None:
            if len(password) < MIN_NEW_PASSWORD_LENGTH:
                raise AureviaError(
                    f"Choose a password of at least {MIN_NEW_PASSWORD_LENGTH} characters",
                    status_code=422,
                    code="weak_password",
                )
            user = User(
                email=invitation.email, password_hash=hash_password(password), full_name=full_name
            )
            self._session.add(user)
            await self._session.flush()
        elif user.status != UserStatus.ACTIVE or not verify_password(user.password_hash, password):
            raise AuthenticationError(INVALID_CREDENTIALS)

        membership = await self._session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id, Membership.user_id == user.id
            )
        )
        if membership is not None and membership.status == MembershipStatus.ACTIVE:
            raise ConflictError("You are already a member of this tenant", code="already_member")
        if membership is None:
            membership = Membership(tenant_id=tenant_id, user_id=user.id, role=invitation.role)
            self._session.add(membership)
        membership.role = invitation.role
        membership.custom_role_id = invitation.custom_role_id
        membership.status = MembershipStatus.ACTIVE
        invitation.accepted_at = now
        await self._session.flush()
        record_audit_event(
            self._session,
            tenant_id=tenant_id,
            actor_user_id=user.id,
            action="invitation.accepted",
            target_type="membership",
            target_id=membership.id,
            details={"invitation_id": str(invitation.id), "role": invitation.role},
        )
        tokens = await self._issue(user.id, tenant_id, membership.id, family_id=None)
        await self._session.commit()
        return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        stored = await self._find_refresh_token(refresh_token)
        if stored is None:
            raise AuthenticationError("Invalid or expired token")
        if stored.revoked_at is not None:
            # A rotated token was presented again: assume theft and end the whole session.
            await self._revoke_family(stored.family_id)
            await self._session.commit()
            raise AuthenticationError("Invalid or expired token")
        if stored.expires_at <= _now():
            raise AuthenticationError("Invalid or expired token")

        await set_tenant_context(self._session, stored.tenant_id)
        membership = await self._active_membership(stored.user_id, stored.tenant_id)
        if membership is None:
            await self._revoke_family(stored.family_id)
            await self._session.commit()
            raise AuthenticationError("Invalid or expired token")

        stored.revoked_at = _now()
        tokens = await self._issue(
            stored.user_id, stored.tenant_id, membership.id, family_id=stored.family_id
        )
        await self._session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        """Revoke the session this token belongs to. Unknown tokens are ignored silently."""
        stored = await self._find_refresh_token(refresh_token)
        if stored is not None:
            await self._revoke_family(stored.family_id)
            await self._session.commit()

    async def _find_user(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def _find_refresh_token(self, token: str) -> RefreshToken | None:
        return await self._session.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(token))
            .with_for_update()
        )

    async def _active_membership(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Membership | None:
        return await self._session.scalar(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
                User.status == UserStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
        )

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )

    async def _issue(
        self,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        membership_id: uuid.UUID,
        *,
        family_id: uuid.UUID | None,
    ) -> TokenPair:
        token, token_hash = new_refresh_token()
        self._session.add(
            RefreshToken(
                user_id=user_id,
                tenant_id=tenant_id,
                family_id=family_id or uuid.uuid4(),
                token_hash=token_hash,
                expires_at=_now() + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
            )
        )
        access = create_access_token(
            AccessClaims(user_id=user_id, tenant_id=tenant_id, membership_id=membership_id),
            secret=self._jwt_secret,
            ttl_seconds=self._settings.access_token_ttl_seconds,
        )
        return TokenPair(
            access_token=access,
            refresh_token=token,
            expires_in=self._settings.access_token_ttl_seconds,
        )
