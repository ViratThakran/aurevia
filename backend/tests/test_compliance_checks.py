"""The gate's rules on their own (docs/06-testing/compliance-tests.md): allowed, blocked,
missing data, time boundaries and conflicting policies, for every check."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from aurevia.compliance.checks import CallerIdFact, ConsentFact, GateFacts, evaluate
from aurevia.compliance.phone import lookup_variants, mask, normalize_e164
from aurevia.compliance.policy import (
    INDIA_DRAFT,
    CallPurpose,
    ConsentKind,
    PolicyPack,
    TelephonyMode,
)
from aurevia.providers.dnd import DndStatus

# 12:00 in India (UTC+5:30), inside the 09:00-21:00 window.
NOON_IST = datetime(2026, 10, 9, 6, 30, tzinfo=UTC)
REVIEWED = dataclasses.replace(INDIA_DRAFT, counsel_reviewed=True)
PROSPECT = "+919876543210"
PROMO_LINE = CallerIdFact("+911401234567", CallPurpose.PROMOTIONAL, True, True)


def _consent(kind: ConsentKind = ConsentKind.EXPRESS, **changes: object) -> ConsentFact:
    base = ConsentFact(
        kind=kind,
        purpose=CallPurpose.PROMOTIONAL,
        obtained_at=NOON_IST - timedelta(days=1),
        expires_at=None,
        revoked=False,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _live(**changes: object) -> GateFacts:
    """Facts for a live call that passes every check."""
    base = GateFacts(
        mode=TelephonyMode.LIVE,
        purpose=CallPurpose.PROMOTIONAL,
        to_number=PROSPECT,
        is_test_number=False,
        lead_status="active",
        lead_interest="unknown",
        on_do_not_call=False,
        consents=(_consent(),),
        dnd=DndStatus.NOT_REGISTERED,
        calls_today=0,
        calls_this_week=0,
        caller_ids=(PROMO_LINE,),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _test_call(**changes: object) -> GateFacts:
    """A test-mode call to the tenant's own registered phone."""
    base = _live(
        mode=TelephonyMode.TEST,
        is_test_number=True,
        consents=(),
        dnd=DndStatus.UNKNOWN,
        caller_ids=(CallerIdFact("+918012345678", CallPurpose.PROMOTIONAL, False, True),),
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _reasons(
    facts: GateFacts, *, pack: PolicyPack = REVIEWED, now: datetime = NOON_IST
) -> list[str]:
    return evaluate(pack, facts, now).failed_reasons


# --- Allowed -----------------------------------------------------------------------------


def test_a_compliant_live_call_is_allowed_with_its_caller_id() -> None:
    outcome = evaluate(REVIEWED, _live(), NOON_IST)
    assert outcome.allowed and outcome.reason_code == "allowed"
    assert outcome.from_number == PROMO_LINE.e164
    assert [c.name for c in outcome.checks] == [
        "mode",
        "number",
        "lead",
        "do_not_call",
        "consent",
        "dnd",
        "calling_window",
        "attempts",
        "caller_id",
    ]


def test_a_test_call_to_an_own_number_needs_no_consent_dnd_or_dlt() -> None:
    outcome = evaluate(INDIA_DRAFT, _test_call(), NOON_IST)
    assert outcome.allowed
    by_name = {c.name: c.reason for c in outcome.checks}
    assert by_name["consent"] == by_name["dnd"] == "test_number"
    assert by_name["caller_id"] == "test_call"


# --- Mode: the safety rails of Phase 6 ---------------------------------------------------


def test_test_mode_blocks_every_number_that_is_not_a_registered_test_number() -> None:
    # Even a fully compliant prospect call is blocked in test mode.
    facts = _live(mode=TelephonyMode.TEST)
    assert _reasons(facts) == ["not_a_test_number"]


def test_live_mode_is_blocked_while_the_policy_pack_is_unreviewed() -> None:
    assert INDIA_DRAFT.counsel_reviewed is False
    assert _reasons(_live(), pack=INDIA_DRAFT) == ["policy_not_reviewed"]


# --- Missing data ------------------------------------------------------------------------


def test_missing_or_invalid_number_is_blocked() -> None:
    assert "invalid_or_missing_number" in _reasons(_live(to_number=None))


def test_missing_consent_is_blocked() -> None:
    assert _reasons(_live(consents=())) == ["no_valid_consent"]


def test_unknown_dnd_status_is_blocked() -> None:
    assert _reasons(_live(dnd=DndStatus.UNKNOWN)) == ["dnd_unverified"]


def test_no_caller_id_is_blocked() -> None:
    assert _reasons(_live(caller_ids=())) == ["no_registered_caller_id"]
    assert _reasons(_test_call(caller_ids=()), pack=INDIA_DRAFT) == ["no_caller_id"]


# --- Blocked -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"to_number": "+14155550100"}, "destination_not_allowed"),
        ({"lead_status": "archived"}, "lead_not_active"),
        ({"lead_interest": "not_interested"}, "lead_not_interested"),
        ({"on_do_not_call": True}, "on_do_not_call_list"),
        ({"calls_today": 2}, "attempt_limit_reached"),
        ({"calls_this_week": 6}, "attempt_limit_reached"),
    ],
)
def test_blocking_rules(changes: dict[str, object], reason: str) -> None:
    assert _reasons(_live(**changes)) == [reason]


@pytest.mark.parametrize(
    "consent",
    [
        _consent(revoked=True),
        _consent(expires_at=NOON_IST - timedelta(seconds=1)),
        _consent(purpose=CallPurpose.SERVICE),  # consent for service calls, not sales
        _consent(obtained_at=NOON_IST + timedelta(hours=1)),  # not yet given
        _consent(ConsentKind.INQUIRY, obtained_at=NOON_IST - timedelta(days=31)),
    ],
)
def test_consent_that_does_not_apply_is_ignored(consent: ConsentFact) -> None:
    assert _reasons(_live(consents=(consent,))) == ["no_valid_consent"]


def test_recent_inquiry_counts_as_consent() -> None:
    inquiry = _consent(ConsentKind.INQUIRY, obtained_at=NOON_IST - timedelta(days=29))
    assert _reasons(_live(consents=(inquiry,))) == []


@pytest.mark.parametrize(
    "line",
    [
        CallerIdFact("+911401234567", CallPurpose.PROMOTIONAL, False, True),  # not DLT
        CallerIdFact("+911401234567", CallPurpose.PROMOTIONAL, True, False),  # inactive
        CallerIdFact("+911601234567", CallPurpose.SERVICE, True, True),  # wrong purpose
        CallerIdFact("+918012345678", CallPurpose.PROMOTIONAL, True, True),  # not 140-series
    ],
)
def test_live_calls_need_a_registered_caller_id_of_the_right_series(line: CallerIdFact) -> None:
    assert _reasons(_live(caller_ids=(line,))) == ["no_registered_caller_id"]


def test_test_mode_has_its_own_attempt_limit() -> None:
    assert _reasons(_test_call(calls_today=19), pack=INDIA_DRAFT) == []
    assert _reasons(_test_call(calls_today=20), pack=INDIA_DRAFT) == ["attempt_limit_reached"]


# --- Time boundaries (09:00 inclusive, 21:00 exclusive, India time) -----------------------


@pytest.mark.parametrize(
    ("ist", "allowed"),
    [
        ((8, 59, 59), False),
        ((9, 0, 0), True),
        ((20, 59, 59), True),
        ((21, 0, 0), False),
        ((2, 0, 0), False),
    ],
)
def test_calling_window_boundaries(ist: tuple[int, int, int], allowed: bool) -> None:
    hour, minute, second = ist
    now = datetime(2026, 10, 9, hour, minute, second, tzinfo=UTC) - timedelta(hours=5, minutes=30)
    reasons = _reasons(_live(), now=now)
    assert reasons == ([] if allowed else ["outside_calling_window"])


def test_the_window_applies_to_test_calls_too() -> None:
    late = datetime(2026, 10, 9, 22, 0, tzinfo=UTC) - timedelta(hours=5, minutes=30)
    assert _reasons(_test_call(), pack=INDIA_DRAFT, now=late) == ["outside_calling_window"]


# --- Conflicting policies ----------------------------------------------------------------


def test_express_consent_overrides_national_dnd() -> None:
    assert _reasons(_live(dnd=DndStatus.REGISTERED)) == []
    outcome = evaluate(REVIEWED, _live(dnd=DndStatus.REGISTERED), NOON_IST)
    assert {c.name: c.reason for c in outcome.checks}["dnd"] == "express_consent_overrides_dnd"


def test_inquiry_consent_does_not_override_national_dnd() -> None:
    inquiry = _consent(ConsentKind.INQUIRY)
    assert _reasons(_live(dnd=DndStatus.REGISTERED, consents=(inquiry,))) == ["dnd_registered"]


def test_a_pack_that_does_not_allow_overrides_blocks_dnd_numbers() -> None:
    strict = dataclasses.replace(REVIEWED, express_consent_overrides_dnd=False)
    assert _reasons(_live(dnd=DndStatus.REGISTERED), pack=strict) == ["dnd_registered"]


def test_the_tenant_do_not_call_list_beats_express_consent() -> None:
    assert _reasons(_live(on_do_not_call=True)) == ["on_do_not_call_list"]


def test_a_do_not_call_test_number_is_still_blocked() -> None:
    assert _reasons(_test_call(on_do_not_call=True), pack=INDIA_DRAFT) == ["on_do_not_call_list"]


def test_every_failure_is_reported_not_just_the_first() -> None:
    late = datetime(2026, 10, 9, 23, 0, tzinfo=UTC)
    reasons = _reasons(_live(consents=(), on_do_not_call=True), now=late)
    assert reasons == ["on_do_not_call_list", "no_valid_consent", "outside_calling_window"]


# --- Phone numbers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("0091 98765 43210", "+919876543210"),
        ("+1 (415) 555-0100", "+14155550100"),
        ("12345", None),
        ("0987654321", None),  # nine digits after the trunk zero
        ("98765abc10", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_e164(raw: str | None, expected: str | None) -> None:
    assert normalize_e164(raw) == expected


def test_lookup_variants_and_masking() -> None:
    assert set(lookup_variants("+919876543210")) >= {"9876543210", "09876543210", "+919876543210"}
    assert mask("+919876543210") == "+91********10"
