"""API shapes for phone numbers, test numbers and outbound calls."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from aurevia.compliance.policy import CallPurpose
from aurevia.compliance.schemas import e164_or_error


class OutboundCallIn(BaseModel):
    lead_id: uuid.UUID
    purpose: CallPurpose = CallPurpose.PROMOTIONAL


class OutboundCallResponse(BaseModel):
    call_id: uuid.UUID
    decision_id: uuid.UUID
    dial_status: str


class PhoneNumberIn(BaseModel):
    e164: str = Field(min_length=6, max_length=25)
    carrier: Literal["exotel"] = "exotel"
    purpose: CallPurpose
    dlt_registered: bool = False
    inbound_enabled: bool = False

    _normalize = field_validator("e164")(e164_or_error)


class PhoneNumberUpdate(BaseModel):
    active: bool | None = None
    inbound_enabled: bool | None = None
    dlt_registered: bool | None = None


class PhoneNumberResponse(BaseModel):
    id: uuid.UUID
    e164: str
    carrier: str
    purpose: str
    dlt_registered: bool
    inbound_enabled: bool
    active: bool
    created_at: datetime


class TestNumberIn(BaseModel):
    __test__ = False  # not a pytest test class

    e164: str = Field(min_length=6, max_length=25)
    label: str = Field(min_length=1, max_length=100)

    _normalize = field_validator("e164")(e164_or_error)


class TestNumberResponse(BaseModel):
    __test__ = False  # not a pytest test class

    id: uuid.UUID
    e164: str
    label: str
    created_at: datetime
