"""Request and response bodies for leads, memories and transcripts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LeadIn(_Body):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9][0-9 ()-]{5,18}[0-9]$")
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=200)


class LeadResponse(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    company: str | None
    status: str
    created_at: datetime
    interest: str = "unknown"
    interest_reason: str | None = None
    qualification: dict[str, Any] = Field(default_factory=dict)
    erased_at: datetime | None = None


class MemoryResponse(BaseModel):
    id: uuid.UUID
    kind: str
    fact: str
    confidence: float
    source_call_id: uuid.UUID | None
    extractor: str
    created_at: datetime


class TranscriptLine(_Body):
    seq: int = Field(ge=0, le=100_000)
    speaker: Literal["prospect", "agent"]
    text: str = Field(min_length=1, max_length=4000)


class TranscriptIn(_Body):
    lines: list[TranscriptLine] = Field(min_length=1, max_length=2000)


class TranscriptResponse(BaseModel):
    call_id: uuid.UUID
    lines: list[TranscriptLine]


class LeadImportIn(_Body):
    csv: str = Field(min_length=1, max_length=2_000_000)  # header row + up to 5000 rows
    campaign_id: uuid.UUID | None = None  # also queue the new leads in this campaign


class LeadImportResult(BaseModel):
    created: int
    added_to_campaign: int
    errors: list[dict[str, object]]
