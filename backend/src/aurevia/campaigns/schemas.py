"""API shapes for campaigns."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aurevia.compliance.policy import CallPurpose


class _Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    starts_on: date | None = None
    ends_on: date | None = None
    window_start: time | None = None
    window_end: time | None = None
    max_attempts_per_lead: int | None = Field(default=None, ge=1, le=10)
    daily_call_cap: int | None = Field(default=None, ge=1, le=100_000)
    retry_delay_minutes: int | None = Field(default=None, ge=5, le=10_080)
    auto_dial: bool | None = None  # the automatic dialer (also needs the server switch)
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _ranges(self) -> _Limits:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must not be before starts_on")
        if self.window_start and self.window_end and self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        return self


class CampaignIn(_Limits):
    name: str = Field(min_length=1, max_length=200)
    purpose: CallPurpose
    starts_on: date  # required here
    max_attempts_per_lead: int = Field(default=3, ge=1, le=10)
    retry_delay_minutes: int = Field(default=60, ge=5, le=10_080)
    auto_dial: bool = False
    max_concurrent_calls: int = Field(default=1, ge=1, le=5)


class CampaignUpdate(_Limits):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class CampaignStatusIn(BaseModel):
    status: Literal["active", "paused", "ended"]


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    purpose: str
    status: str
    starts_on: date
    ends_on: date | None
    window_start: time | None
    window_end: time | None
    max_attempts_per_lead: int
    daily_call_cap: int | None
    retry_delay_minutes: int
    auto_dial: bool
    max_concurrent_calls: int
    created_at: datetime


class CampaignLeadsIn(BaseModel):
    lead_ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)


class CampaignLeadsAdded(BaseModel):
    added: int


class CampaignLeadResponse(BaseModel):
    lead_id: uuid.UUID
    lead_name: str
    status: str
    attempts: int
    next_attempt_at: datetime
    last_result: str | None
    last_call_id: uuid.UUID | None


class CallNextResponse(BaseModel):
    status: str  # placed | empty | blocked
    lead_id: uuid.UUID | None
    call_id: uuid.UUID | None
    reasons: list[str]
