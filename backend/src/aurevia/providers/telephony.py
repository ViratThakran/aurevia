"""Telephony contract (Phase 6).

``place_call`` is reached only from ``telephony/service.py``, which demands a compliance-gate
``Approval`` for every dial; ``tests/test_architecture.py`` enforces that nothing else calls it.
The carrier itself (Exotel first) is configuration of the SIP trunk, not code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class DialFailure(StrEnum):
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"


class DialError(Exception):
    """The phone was not answered. ``sip_status`` is the carrier's SIP code when known."""

    def __init__(self, failure: DialFailure, *, sip_status: int | None = None) -> None:
        super().__init__(f"dial failed: {failure.value} (sip {sip_status})")
        self.failure = failure
        self.sip_status = sip_status


@dataclass(frozen=True)
class OutboundCallRequest:
    tenant_id: uuid.UUID
    call_id: uuid.UUID
    room: str
    to_number: str  # E.164
    from_number: str  # the tenant's caller id, E.164
    compliance_decision_id: uuid.UUID  # the gate decision that allowed this call
    ring_timeout_seconds: int


@dataclass(frozen=True)
class AnsweredCall:
    provider_call_id: str


@runtime_checkable
class TelephonyProvider(Protocol):
    name: str

    async def place_call(self, request: OutboundCallRequest) -> AnsweredCall:
        """Dial and wait until the phone is answered; raise ``DialError`` if it is not.

        The callee joins ``request.room`` as a participant, where the agent is waiting.
        """
        ...


def failure_for_sip_status(status: int | None) -> DialFailure:
    """Map a final SIP response to what happened, conservatively."""
    if status in (486, 600):  # busy here / busy everywhere
        return DialFailure.BUSY
    if status in (408, 480, 487, 603):  # timeout / unavailable / cancelled / declined
        return DialFailure.NO_ANSWER
    return DialFailure.FAILED
