"""The gate's rules on their own (docs/06-testing/compliance-tests.md): allowed, blocked,
missing data, time boundaries and conflicting policies, for every check."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, time, timedelta

import pytest

from aurevia.compliance.checks import (
    CallerIdFact,
    CampaignFact,
    ConsentFact,
    GateFacts,
    evaluate,
    missing_disclosures,
)
from aurevia.compliance.phone import lookup_variants, mask, normalize_e164
from aurevia.compliance.policy import (
    INDIA_DRAFT,
    INDIA_DRAFT_FILE,
    CallPurpose,
    ConsentKind,
    PolicyPack,
    PolicyStatus,
    TelephonyMode,
    load_builtin,
)
from aurevia.providers.dnd import DndStatus

# 12:00 in India (UTC+5:30), inside the 09:00-21:00 window.
NOON_IST = datetime(2026, 10, 9, 6, 30, tzinfo=UTC)
REVIEWED = dataclasses.replace(INDIA_DRAFT, status=PolicyStatus.REVIEWED)
PROSPECT = "+919876543210"
PROMO_LINE = CallerIdFact("+911401234567", CallPurpose.PROMOTIONAL, True, True)
# Pinned: changing a published policy file must fail this test (publish a new version).
INDIA_DRAFT_SHA256 = "c10ff64e9d19357c5d9276ac750de78bcbb83d1ad3e57b75fa642946c86a45fd"
INDIA_DRAFT_RULES: dict[str, object] = json.loads(
    load_builtin(INDIA_DRAFT_FILE).rules.model_dump_json()
)
CAMPAIGN = CampaignFact(
    status="active",
    purpose=CallPurpose.PROMOTIONAL,
    starts_on=NOON_IST.date() - timedelta(days=1),
    ends_on=None,
    window_start=None,
    window_end=None,
    max_attempts_per_lead=3,
    attempts_for_lead=0,
    daily_call_cap=None,
    calls_today=0,
)


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
        campaign=CAMPAIGN,
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
        "disclosure",
        "campaign",
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


# --- Phase 7: campaigns ------------------------------------------------------------------


def test_live_calls_need_a_campaign_but_test_calls_do_not() -> None:
    assert _reasons(_live(campaign=None)) == ["campaign_required"]
    outcome = evaluate(INDIA_DRAFT, _test_call(campaign=None), NOON_IST)
    assert outcome.allowed
    assert {c.name: c.reason for c in outcome.checks}["campaign"] == "no_campaign"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"status": "paused"}, "campaign_not_active"),
        ({"status": "draft"}, "campaign_not_active"),
        ({"purpose": CallPurpose.SERVICE}, "campaign_purpose_mismatch"),
        ({"starts_on": NOON_IST.date() + timedelta(days=1)}, "campaign_not_running"),
        ({"ends_on": NOON_IST.date() - timedelta(days=1)}, "campaign_not_running"),
        ({"window_start": time(13, 0)}, "outside_campaign_hours"),
        ({"window_end": time(12, 0)}, "outside_campaign_hours"),  # end is exclusive
        ({"attempts_for_lead": 3}, "campaign_attempts_reached"),
        ({"daily_call_cap": 50, "calls_today": 50}, "campaign_daily_cap_reached"),
    ],
)
def test_campaign_limits(changes: dict[str, object], reason: str) -> None:
    campaign = dataclasses.replace(CAMPAIGN, **changes)  # type: ignore[arg-type]
    assert _reasons(_live(campaign=campaign)) == [reason]


def test_campaign_hours_narrow_but_never_widen_the_policy_window() -> None:
    wide = dataclasses.replace(CAMPAIGN, window_start=time(6, 0), window_end=time(23, 0))
    late = datetime(2026, 10, 9, 22, 0, tzinfo=UTC) - timedelta(hours=5, minutes=30)
    assert _reasons(_live(campaign=wide), now=late) == ["outside_calling_window"]
    ends_on_today = dataclasses.replace(CAMPAIGN, ends_on=NOON_IST.date())  # inclusive
    assert _reasons(_live(campaign=ends_on_today)) == []


# --- Phase 7: mandatory disclosures ------------------------------------------------------

REQUIRED = ("ai_identity", "agent_name", "company_name")


@pytest.mark.parametrize(
    ("greeting", "missing"),
    [
        ("Hi, this is Aria, an AI assistant calling from Acme Insurance.", ()),
        ("Hello, Aria here from ACME INSURANCE, an artificial intelligence agent.", ()),
        ("Hi, this is Aria from Acme Insurance.", ("ai_identity",)),
        ("Hi, I'm an AI assistant from Acme Insurance.", ("agent_name",)),
        ("Hi, this is Aria, an AI assistant.", ("company_name",)),
        ("Hi, this is Kaira calling.", REQUIRED),  # "ai" inside a word is not a disclosure
    ],
)
def test_missing_disclosures(greeting: str, missing: tuple[str, ...]) -> None:
    found = missing_disclosures(
        REQUIRED, greeting=greeting, agent_name="Aria", company_name="Acme Insurance"
    )
    assert found == missing


def test_a_greeting_without_disclosures_blocks_the_call() -> None:
    assert _reasons(_live(missing_disclosures=("ai_identity",))) == ["missing_disclosure"]


# --- Phase 7: versioned policies and tenant tightening -----------------------------------


def test_builtin_policy_files_never_change() -> None:
    """Published versions are immutable: edit nothing, publish a new file instead."""
    import hashlib

    raw = load_builtin(INDIA_DRAFT_FILE).raw
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == INDIA_DRAFT_SHA256


def test_rules_are_validated() -> None:
    from pydantic import ValidationError

    from aurevia.compliance.policy import PolicyRules

    rules = INDIA_DRAFT_RULES | {"window_start": "21:00:00", "window_end": "09:00:00"}
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(rules)
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(INDIA_DRAFT_RULES | {"surprise": True})


def test_overrides_only_ever_tighten() -> None:
    from aurevia.compliance.policy import PolicyOverrides, apply_overrides, looser_overrides

    strict = PolicyOverrides(
        window_start=time(10, 0),
        window_end=time(18, 0),
        max_calls_per_number_per_day=1,
        express_consent_overrides_dnd=False,
    )
    assert looser_overrides(INDIA_DRAFT, strict) == []
    tightened = apply_overrides(INDIA_DRAFT, strict)
    assert (tightened.window_start, tightened.window_end) == (time(10, 0), time(18, 0))
    assert tightened.max_calls_per_number_per_day == 1
    assert tightened.express_consent_overrides_dnd is False

    loose = PolicyOverrides(
        window_start=time(8, 0), window_end=time(22, 0), max_calls_per_number_per_week=50
    )
    assert looser_overrides(INDIA_DRAFT, loose) == [
        "window_start",
        "window_end",
        "max_calls_per_number_per_week",
    ]
    # Even if a looser value got stored, applying it changes nothing.
    unchanged = apply_overrides(INDIA_DRAFT, loose)
    assert (unchanged.window_start, unchanged.window_end) == (time(9, 0), time(21, 0))
    assert unchanged.max_calls_per_number_per_week == 6
