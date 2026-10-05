"""Telephony contract (Phase 6).

``place_call`` must only ever be reached through the compliance-gated call service. Nothing
else may hold a ``TelephonyProvider``: the import-boundary test enforces that business code
does not import vendor SDKs, and code review enforces that the gate is never skipped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class CallStatus(StrEnum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


@dataclass(frozen=True)
class OutboundCallRequest:
    tenant_id: uuid.UUID
    call_id: uuid.UUID
    to_number: str  # E.164
    from_number: str  # the tenant's registered caller id
    compliance_decision_id: uuid.UUID  # proof the pre-call gate allowed this call


@dataclass(frozen=True)
class CallHandle:
    provider_call_id: str
    status: CallStatus


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str

    async def place_call(self, request: OutboundCallRequest) -> CallHandle: ...

    async def hang_up(self, provider_call_id: str) -> None: ...
