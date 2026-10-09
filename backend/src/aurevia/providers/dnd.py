"""National Do-Not-Disturb registry lookups (India: NCPR scrubbing), behind an interface.

No registry is integrated yet. ``UnconfiguredDndRegistry`` answers "unknown" for every number,
and the India policy pack blocks numbers whose status is unknown, so the absence of a real
registry can only ever prevent calls, never allow them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class DndStatus(StrEnum):
    REGISTERED = "registered"
    NOT_REGISTERED = "not_registered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DndLookup:
    status: DndStatus
    source: str
    checked_at: datetime


@runtime_checkable
class DndRegistry(Protocol):
    name: str

    async def lookup(self, e164: str, *, now: datetime) -> DndLookup: ...


class UnconfiguredDndRegistry:
    name = "none"

    async def lookup(self, e164: str, *, now: datetime) -> DndLookup:
        return DndLookup(status=DndStatus.UNKNOWN, source=self.name, checked_at=now)
