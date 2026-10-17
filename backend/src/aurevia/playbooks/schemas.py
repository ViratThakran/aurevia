"""Playbook API bodies (WP-12.7, 12.A). The entry format is fixed by the plan."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from aurevia.playbooks.models import EntryStatus, PlaybookStatus
from aurevia.sales.state import SalesState


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EntryIn(_Body):
    stage: SalesState | None = None  # None: any stage
    situation: str = Field(min_length=1, max_length=300)
    says: str = Field(min_length=1, max_length=500)
    tone: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)


class VersionCreateIn(_Body):
    agent_id: uuid.UUID
    notes: str = Field(default="", max_length=500)
    # Start from the built-in seed entries (WP-12.A), all as proposed.
    seed: bool = False
    # Or copy the entries of an earlier version of the same agent, approved ones staying
    # approved (the way to change an active playbook: copy, edit the draft, activate).
    copy_from_version_id: uuid.UUID | None = None


class EntryOut(BaseModel):
    id: uuid.UUID
    position: int
    stage: SalesState | None
    situation: str
    says: str
    tone: str
    goal: str
    source: str
    status: EntryStatus
    approved_at: datetime | None


class VersionOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    status: PlaybookStatus
    notes: str
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


class VersionDetailOut(VersionOut):
    entries: list[EntryOut]
