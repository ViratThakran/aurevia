"""Policy packs: market rules as versioned data (Phase 7).

A pack version is an immutable set of rules stored in ``policy_versions``. New rules mean a new
version, never an edit. Versions start as ``draft``. Only the platform operator can mark one
``reviewed`` (``python -m aurevia.compliance.operator``), recording who reviewed it and the
reference of their opinion. Live calls are possible only under a reviewed version.

Built-in versions ship as JSON files in ``compliance/packs/``. Those files are as immutable as
the versions (a test pins their hashes).

Tenants may tighten a version's rules (``PolicyOverrides``), never loosen them:
``apply_overrides`` always keeps the stricter of the two values.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CallPurpose(StrEnum):
    PROMOTIONAL = "promotional"  # selling: in India, 140-series caller ids
    SERVICE = "service"  # service/transactional: in India, 160-series caller ids


class TelephonyMode(StrEnum):
    TEST = "test"  # only the tenant's own registered test numbers can be called
    LIVE = "live"  # real prospects; requires a counsel-reviewed policy version


class ConsentKind(StrEnum):
    EXPRESS = "express"  # the prospect explicitly agreed to be called
    INQUIRY = "inquiry"  # the prospect made an enquiry themselves (time-limited)


class PolicyStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"  # by counsel, recorded by the platform operator
    RETIRED = "retired"


Disclosure = Literal["ai_identity", "agent_name", "company_name"]


class PolicyRules(BaseModel):
    """The rules of one pack version, validated whenever they are loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timezone: str = Field(min_length=1, max_length=64)
    country_code: str = Field(pattern=r"^[1-9]\d{0,3}$")
    window_start: time
    window_end: time
    max_calls_per_number_per_day: int = Field(ge=0, le=20)
    max_calls_per_number_per_week: int = Field(ge=0, le=100)
    test_max_calls_per_number_per_day: int = Field(ge=0, le=100)
    inquiry_consent_valid_days: int = Field(ge=0, le=365)
    express_consent_overrides_dnd: bool
    block_when_dnd_unknown: bool
    caller_id_prefixes: dict[CallPurpose, tuple[str, ...]]
    required_disclosures: tuple[Disclosure, ...]
    require_campaign_for_live: bool

    @model_validator(mode="after")
    def _window_is_a_range(self) -> PolicyRules:
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        return self


class PolicyOverrides(BaseModel):
    """A tenant's own, stricter settings. ``None`` means "use the policy version's value"."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_start: time | None = None
    window_end: time | None = None
    max_calls_per_number_per_day: int | None = Field(default=None, ge=0, le=20)
    max_calls_per_number_per_week: int | None = Field(default=None, ge=0, le=100)
    inquiry_consent_valid_days: int | None = Field(default=None, ge=0, le=365)
    # Only ever False: a tenant may refuse to call DND-registered numbers even with consent.
    express_consent_overrides_dnd: Literal[False] | None = None


@dataclass(frozen=True)
class PolicyPack:
    """The effective rules for one decision: a version's rules plus the tenant's tightening."""

    name: str
    version: str
    status: PolicyStatus
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
    required_disclosures: tuple[Disclosure, ...]
    require_campaign_for_live: bool
    version_id: uuid.UUID | None = None

    @property
    def counsel_reviewed(self) -> bool:
        return self.status == PolicyStatus.REVIEWED

    @classmethod
    def from_rules(
        cls,
        *,
        name: str,
        version: str,
        status: PolicyStatus,
        rules: PolicyRules,
        version_id: uuid.UUID | None = None,
    ) -> PolicyPack:
        return cls(
            name=name,
            version=version,
            status=status,
            version_id=version_id,
            **{field: getattr(rules, field) for field in PolicyRules.model_fields},
        )


class LooserThanPolicyError(ValueError):
    """A tenant override would relax the policy version's rules."""


def looser_overrides(rules: PolicyPack, overrides: PolicyOverrides) -> list[str]:
    """Names of overrides that would relax ``rules`` (empty when all are stricter or equal)."""
    looser = []
    if overrides.window_start is not None and overrides.window_start < rules.window_start:
        looser.append("window_start")
    if overrides.window_end is not None and overrides.window_end > rules.window_end:
        looser.append("window_end")
    for name in (
        "max_calls_per_number_per_day",
        "max_calls_per_number_per_week",
        "inquiry_consent_valid_days",
    ):
        value = getattr(overrides, name)
        if value is not None and value > getattr(rules, name):
            looser.append(name)
    return looser


def apply_overrides(pack: PolicyPack, overrides: PolicyOverrides) -> PolicyPack:
    """The stricter of the version's rules and the tenant's overrides, field by field.

    Never loosens anything, even if an override saved under an older version is looser now.
    """

    def pick_min(name: str) -> Any:
        value = getattr(overrides, name)
        return getattr(pack, name) if value is None else min(value, getattr(pack, name))

    start = overrides.window_start
    end = overrides.window_end
    return dataclasses.replace(
        pack,
        window_start=max(start, pack.window_start) if start else pack.window_start,
        window_end=min(end, pack.window_end) if end else pack.window_end,
        max_calls_per_number_per_day=pick_min("max_calls_per_number_per_day"),
        max_calls_per_number_per_week=pick_min("max_calls_per_number_per_week"),
        inquiry_consent_valid_days=pick_min("inquiry_consent_valid_days"),
        express_consent_overrides_dnd=pack.express_consent_overrides_dnd
        and overrides.express_consent_overrides_dnd is not False,
    )


# --- Built-in versions (the JSON files that seed ``policy_versions``) -------------------------


@dataclass(frozen=True)
class BuiltinVersion:
    pack: str
    version: str
    notes: str
    rules: PolicyRules
    raw: str  # the file's exact text, as stored


def load_builtin(file_name: str) -> BuiltinVersion:
    text = resources.files("aurevia.compliance.packs").joinpath(file_name).read_text("utf-8")
    raw = text.replace("\r\n", "\n")  # same bytes (and hash) on every OS checkout
    data = json.loads(raw)
    return BuiltinVersion(
        pack=data["pack"],
        version=data["version"],
        notes=data["notes"],
        rules=PolicyRules.model_validate(data["rules"]),
        raw=raw,
    )


INDIA_DRAFT_FILE = "india-2026-10-draft-1.json"
_india = load_builtin(INDIA_DRAFT_FILE)
# The India draft as a pack, for tests and as a reference; the gate always reads versions from
# the database.
INDIA_DRAFT = PolicyPack.from_rules(
    name=_india.pack, version=_india.version, status=PolicyStatus.DRAFT, rules=_india.rules
)
