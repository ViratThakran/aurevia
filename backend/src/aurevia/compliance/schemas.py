"""API shapes for consent, the do-not-call list and gate decisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aurevia.compliance.phone import normalize_e164
from aurevia.compliance.policy import CallPurpose, ConsentKind


def e164_or_error(value: str) -> str:
    normalized = normalize_e164(value)
    if normalized is None:
        raise ValueError("not a valid phone number")
    return normalized


class ConsentIn(BaseModel):
    kind: ConsentKind
    purpose: CallPurpose
    source: str = Field(min_length=1, max_length=200)
    evidence: str | None = Field(default=None, max_length=1000)
    obtained_at: datetime | None = None  # defaults to now
    expires_at: datetime | None = None


class ConsentResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    phone: str
    kind: str
    purpose: str
    source: str
    evidence: str | None
    obtained_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class DoNotCallIn(BaseModel):
    phone: str = Field(min_length=6, max_length=25)
    reason: Literal["manual", "complaint"] = "manual"
    note: str | None = Field(default=None, max_length=500)

    _normalize = field_validator("phone")(e164_or_error)


class DoNotCallResponse(BaseModel):
    id: uuid.UUID
    phone: str
    reason: str
    note: str | None
    source_call_id: uuid.UUID | None
    created_at: datetime


class DecisionResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None
    action: str
    purpose: str
    to_number: str | None
    from_number: str | None
    mode: str
    policy_pack: str
    policy_version: str
    checks: list[dict[str, Any]]
    decision: str
    reason_code: str
    created_at: datetime
