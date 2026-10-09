"""Policy packs: market rules as data, selected by configuration.

The values in the India pack are a DRAFT taken from the product brief. They have not been
reviewed by counsel (``counsel_reviewed=False``), and the gate refuses every live call under an
unreviewed pack: until review, only test calls to the tenant's own registered numbers can pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum


class CallPurpose(StrEnum):
    PROMOTIONAL = "promotional"  # selling: in India, 140-series caller ids
    SERVICE = "service"  # service/transactional: in India, 160-series caller ids


class TelephonyMode(StrEnum):
    TEST = "test"  # only the tenant's own registered test numbers can be called
    LIVE = "live"  # real prospects; requires a counsel-reviewed policy pack


class ConsentKind(StrEnum):
    EXPRESS = "express"  # the prospect explicitly agreed to be called
    INQUIRY = "inquiry"  # the prospect made an enquiry themselves (time-limited)


@dataclass(frozen=True)
class PolicyPack:
    name: str
    version: str
    counsel_reviewed: bool
    timezone: str
    country_code: str  # destinations allowed under this pack, without "+"
    window_start: time  # first moment a call may start (inclusive)
    window_end: time  # calls must start before this (exclusive)
    max_calls_per_number_per_day: int
    max_calls_per_number_per_week: int
    test_max_calls_per_number_per_day: int
    # Consent from an enquiry the prospect made themselves stays valid this long.
    inquiry_consent_valid_days: int
    # Whether express consent allows calling a number registered on the national DND list.
    express_consent_overrides_dnd: bool
    # A number whose DND status cannot be checked is treated as registered (blocked).
    block_when_dnd_unknown: bool
    caller_id_prefixes: dict[CallPurpose, tuple[str, ...]]


INDIA_DRAFT = PolicyPack(
    name="india",
    version="india-2026-10-draft-1",
    counsel_reviewed=False,
    timezone="Asia/Kolkata",
    country_code="91",
    window_start=time(9, 0),
    window_end=time(21, 0),
    max_calls_per_number_per_day=2,
    max_calls_per_number_per_week=6,
    test_max_calls_per_number_per_day=20,
    inquiry_consent_valid_days=30,
    express_consent_overrides_dnd=True,
    block_when_dnd_unknown=True,
    caller_id_prefixes={
        CallPurpose.PROMOTIONAL: ("+91140",),
        CallPurpose.SERVICE: ("+91160",),
    },
)

POLICY_PACKS: dict[str, PolicyPack] = {INDIA_DRAFT.name: INDIA_DRAFT}
