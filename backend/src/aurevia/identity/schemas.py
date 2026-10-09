"""Request and response bodies for the identity API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from aurevia.identity.models import Role
from aurevia.identity.permissions import Permission

# Length, not composition rules: long passphrases beat forced symbols. The upper bound keeps
# hashing cost bounded.
Password = Field(min_length=12, max_length=128)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignupRequest(_Body):
    email: EmailStr
    password: str = Password
    full_name: str | None = Field(default=None, max_length=200)
    tenant_name: str = Field(min_length=2, max_length=200)


class LoginRequest(_Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Only needed when the account belongs to several tenants. Membership is always checked.
    tenant_id: uuid.UUID | None = None


class RefreshRequest(_Body):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type label
    expires_in: int


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    tenant: TenantResponse
    permissions: list[str] = []
    is_platform_admin: bool = False


class MemberResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime
    custom_role_id: uuid.UUID | None = None


class ChangeRoleRequest(_Body):
    role: Role
    custom_role_id: uuid.UUID | None = None  # members only


# --- Team (Phase 8) ------------------------------------------------------------------------


class CustomRoleIn(_Body):
    name: str = Field(min_length=1, max_length=80)
    permissions: set[Permission] = Field(min_length=1)


class CustomRoleUpdate(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    permissions: set[Permission] | None = Field(default=None, min_length=1)


class CustomRoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    permissions: list[str]


class InvitationIn(_Body):
    email: EmailStr
    role: Role = Role.MEMBER
    custom_role_id: uuid.UUID | None = None


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    custom_role_id: uuid.UUID | None
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationResponse):
    token: str  # shown once; share it as an invitation link


class AcceptInvitationRequest(_Body):
    token: str = Field(min_length=20, max_length=200)
    # A new account's password (12+ characters), or an existing account's own password.
    password: str = Field(min_length=1, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
