"""Request and response bodies for the identity API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from aurevia.identity.models import Role

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


class MemberResponse(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime


class ChangeRoleRequest(_Body):
    role: Role
