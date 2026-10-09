"""Identity and tenancy tables.

``users`` and ``refresh_tokens`` are global (a person can belong to several tenants).
``tenants``, ``memberships`` and ``audit_events`` are protected by row-level security; the
policies live in the migration, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class Tenant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint(one_of("status", TenantStatus), name="status"),)

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=TenantStatus.ACTIVE)


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(one_of("status", UserStatus), name="status"),)

    # Stored lower-cased; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Aurevia staff (Phase 8). Set only by the platform operator command, never by an API.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Membership(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(one_of("role", Role), name="role"),
        CheckConstraint(one_of("status", MembershipStatus), name="status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=MembershipStatus.ACTIVE)
    # Phase 8: a member may hold a tenant-defined role instead of the built-in member rights.
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("custom_roles.id", ondelete="RESTRICT")
    )


class RefreshToken(UUIDPrimaryKey, Base):
    """One row per issued refresh token. Only a SHA-256 hash of the token is stored.

    Tokens of one login share a ``family_id``. Presenting an already-rotated token revokes the
    whole family (stolen-token detection).
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(UUIDPrimaryKey, Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Tamper evidence (Phase 7): a per-tenant hash chain computed by a database trigger on
    # insert. Each event's hash covers its content and the previous event's hash.
    seq: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    prev_hash: Mapped[str] = mapped_column(String(64), server_default=FetchedValue())
    hash: Mapped[str] = mapped_column(String(64), server_default=FetchedValue())


class CustomRole(UUIDPrimaryKey, Timestamps, Base):
    """A tenant-defined set of permissions (see ``identity/permissions.py``)."""

    __tablename__ = "custom_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(40)))


class Invitation(UUIDPrimaryKey, Base):
    """An invitation to join a tenant. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(one_of("role", Role), name="role"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    custom_role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("custom_roles.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
