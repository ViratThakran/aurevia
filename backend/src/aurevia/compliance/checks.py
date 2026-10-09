"""The gate's rules, as a pure function of a policy pack, gathered facts and the time.

No database and no model: every rule can be tested on its own (docs/06-testing). Every check
runs on every request, so a decision record always shows the complete picture, and the call is
allowed only if all of them pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aurevia.compliance.policy import CallPurpose, ConsentKind, PolicyPack, TelephonyMode
from aurevia.providers.dnd import DndStatus

ACTIVE_LEAD_STATUS = "active"
NOT_INTERESTED = "not_interested"


@dataclass(frozen=True)
class ConsentFact:
    kind: ConsentKind
    purpose: CallPurpose
    obtained_at: datetime
    expires_at: datetime | None
    revoked: bool


@dataclass(frozen=True)
class CallerIdFact:
    e164: str
    purpose: CallPurpose
    dlt_registered: bool
    active: bool


@dataclass(frozen=True)
class GateFacts:
    mode: TelephonyMode
    purpose: CallPurpose
    to_number: str | None  # normalized E.164, or None if the lead's phone is unusable
    is_test_number: bool
    lead_status: str
    lead_interest: str
    on_do_not_call: bool
    consents: tuple[ConsentFact, ...]
    dnd: DndStatus
    calls_today: int
    calls_this_week: int
    caller_ids: tuple[CallerIdFact, ...]


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "reason": self.reason}


@dataclass(frozen=True)
class GateOutcome:
    checks: tuple[CheckResult, ...]
    from_number: str | None

    @property
    def allowed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def reason_code(self) -> str:
        failed = [c.reason for c in self.checks if not c.passed]
        return failed[0] if failed else "allowed"

    @property
    def failed_reasons(self) -> list[str]:
        return [c.reason for c in self.checks if not c.passed]


def _ok(name: str, reason: str = "ok") -> CheckResult:
    return CheckResult(name, True, reason)


def _fail(name: str, reason: str) -> CheckResult:
    return CheckResult(name, False, reason)


def _mode(pack: PolicyPack, facts: GateFacts) -> CheckResult:
    if facts.mode == TelephonyMode.TEST:
        return (
            _ok("mode", "test_number")
            if facts.is_test_number
            else _fail("mode", "not_a_test_number")
        )
    return _ok("mode", "live") if pack.counsel_reviewed else _fail("mode", "policy_not_reviewed")


def _number(pack: PolicyPack, facts: GateFacts) -> CheckResult:
    if facts.to_number is None:
        return _fail("number", "invalid_or_missing_number")
    if not facts.to_number.startswith("+" + pack.country_code):
        return _fail("number", "destination_not_allowed")
    return _ok("number")


def _lead(facts: GateFacts) -> CheckResult:
    if facts.lead_status != ACTIVE_LEAD_STATUS:
        return _fail("lead", "lead_not_active")
    if facts.lead_interest == NOT_INTERESTED:
        return _fail("lead", "lead_not_interested")
    return _ok("lead")


def _do_not_call(facts: GateFacts) -> CheckResult:
    return (
        _fail("do_not_call", "on_do_not_call_list") if facts.on_do_not_call else _ok("do_not_call")
    )


def _valid_consents(pack: PolicyPack, facts: GateFacts, now: datetime) -> list[ConsentFact]:
    valid = []
    for consent in facts.consents:
        if consent.revoked or consent.purpose != facts.purpose or consent.obtained_at > now:
            continue
        if consent.expires_at is not None and consent.expires_at <= now:
            continue
        if consent.kind == ConsentKind.INQUIRY and now - consent.obtained_at > timedelta(
            days=pack.inquiry_consent_valid_days
        ):
            continue
        valid.append(consent)
    return valid


def _consent(pack: PolicyPack, facts: GateFacts, now: datetime) -> CheckResult:
    if facts.mode == TelephonyMode.TEST and facts.is_test_number:
        return _ok("consent", "test_number")
    if not _valid_consents(pack, facts, now):
        return _fail("consent", "no_valid_consent")
    return _ok("consent")


def _dnd(pack: PolicyPack, facts: GateFacts, now: datetime) -> CheckResult:
    if facts.mode == TelephonyMode.TEST and facts.is_test_number:
        return _ok("dnd", "test_number")
    if facts.dnd == DndStatus.NOT_REGISTERED:
        return _ok("dnd")
    express = any(c.kind == ConsentKind.EXPRESS for c in _valid_consents(pack, facts, now))
    if facts.dnd == DndStatus.REGISTERED:
        if express and pack.express_consent_overrides_dnd:
            return _ok("dnd", "express_consent_overrides_dnd")
        return _fail("dnd", "dnd_registered")
    return (
        _fail("dnd", "dnd_unverified")
        if pack.block_when_dnd_unknown
        else _ok("dnd", "dnd_unknown_allowed")
    )


def _window(pack: PolicyPack, now: datetime) -> CheckResult:
    local = now.astimezone(ZoneInfo(pack.timezone)).time()
    if pack.window_start <= local < pack.window_end:
        return _ok("calling_window")
    return _fail("calling_window", "outside_calling_window")


def _attempts(pack: PolicyPack, facts: GateFacts) -> CheckResult:
    if facts.mode == TelephonyMode.TEST:
        within = facts.calls_today < pack.test_max_calls_per_number_per_day
    else:
        within = (
            facts.calls_today < pack.max_calls_per_number_per_day
            and facts.calls_this_week < pack.max_calls_per_number_per_week
        )
    return _ok("attempts") if within else _fail("attempts", "attempt_limit_reached")


def _caller_id(pack: PolicyPack, facts: GateFacts) -> tuple[CheckResult, str | None]:
    active = [c for c in facts.caller_ids if c.active]
    if facts.mode == TelephonyMode.TEST:
        # A test call to the tenant's own phone is not telemarketing: any active number will do.
        if active:
            return _ok("caller_id", "test_call"), active[0].e164
        return _fail("caller_id", "no_caller_id"), None
    prefixes = pack.caller_id_prefixes.get(facts.purpose, ())
    for number in active:
        if (
            number.purpose == facts.purpose
            and number.dlt_registered
            and number.e164.startswith(prefixes)
        ):
            return _ok("caller_id"), number.e164
    return _fail("caller_id", "no_registered_caller_id"), None


def evaluate(pack: PolicyPack, facts: GateFacts, now: datetime) -> GateOutcome:
    caller_id, from_number = _caller_id(pack, facts)
    checks = (
        _mode(pack, facts),
        _number(pack, facts),
        _lead(facts),
        _do_not_call(facts),
        _consent(pack, facts, now),
        _dnd(pack, facts, now),
        _window(pack, now),
        _attempts(pack, facts),
        caller_id,
    )
    return GateOutcome(checks=checks, from_number=from_number)
