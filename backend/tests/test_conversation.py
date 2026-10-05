from __future__ import annotations

import uuid

import pytest

from aurevia.conversation.engine import (
    CALL_CONNECTED,
    InvalidHistoryError,
    Utterance,
    to_model_messages,
)
from aurevia.conversation.prompt import AgentProfile, build_system_prompt
from aurevia.errors import AuthenticationError
from aurevia.identity.security import AccessClaims, create_access_token
from aurevia.sales.state import (
    STATE_GOALS,
    TRANSITIONS,
    InvalidTransitionError,
    SalesState,
    after_prospect_turn,
    transition,
)
from aurevia.voice.call_auth import create_call_token, decode_call_token
from tests.conftest import TEST_JWT_SECRET

PROFILE = AgentProfile(
    name="Aria",
    company_name="Acme Brokers",
    company_description="Acme sells health insurance plans for small businesses.",
    objective="Book a call with an advisor.",
    language="en-IN",
)

# --- Sales state machine -----------------------------------------------------------------


def test_every_state_has_a_goal_and_transition_entry() -> None:
    assert set(STATE_GOALS) == set(SalesState) == set(TRANSITIONS)


def test_completed_is_terminal_and_every_state_can_end() -> None:
    assert TRANSITIONS[SalesState.COMPLETED] == frozenset()
    for state in SalesState:
        if state != SalesState.COMPLETED:
            assert SalesState.COMPLETED in TRANSITIONS[state]


def test_disallowed_transitions_are_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(SalesState.NEW, SalesState.MEETING_BOOKED)
    with pytest.raises(InvalidTransitionError):
        transition(SalesState.COMPLETED, SalesState.OPENING)
    assert transition(SalesState.NEW, SalesState.OPENING) == SalesState.OPENING


def test_prospect_turn_moves_opening_to_discovery_only() -> None:
    assert after_prospect_turn(SalesState.OPENING) == SalesState.DISCOVERY
    assert after_prospect_turn(SalesState.DISCOVERY) == SalesState.DISCOVERY
    assert after_prospect_turn(SalesState.PITCH) == SalesState.PITCH


# --- Prompt ------------------------------------------------------------------------------


def test_prompt_carries_honesty_rules_company_facts_and_state_goal() -> None:
    prompt = build_system_prompt(PROFILE, SalesState.DISCOVERY)
    assert "Never say or imply that you are human" in prompt
    assert "you are an AI assistant for Acme Brokers" in prompt
    assert "Never say you have done any of these" in prompt
    assert PROFILE.company_description in prompt
    assert PROFILE.objective in prompt
    assert STATE_GOALS[SalesState.DISCOVERY] in prompt


def test_prompt_is_deterministic() -> None:
    assert build_system_prompt(PROFILE, SalesState.PITCH) == build_system_prompt(
        PROFILE, SalesState.PITCH
    )


# --- Transcript to model messages --------------------------------------------------------


def test_call_opening_with_greeting_gets_a_connected_marker() -> None:
    messages = to_model_messages(
        [Utterance("agent", "Hi, this is Aria."), Utterance("prospect", "Who is this?")]
    )
    assert [(m.role, m.content) for m in messages] == [
        ("user", CALL_CONNECTED),
        ("assistant", "Hi, this is Aria."),
        ("user", "Who is this?"),
    ]


def test_turn_must_end_with_the_prospect() -> None:
    with pytest.raises(InvalidHistoryError):
        to_model_messages([Utterance("prospect", "hi"), Utterance("agent", "hello")])
    with pytest.raises(InvalidHistoryError):
        to_model_messages([Utterance("prospect", "   ")])


def test_blank_utterances_are_dropped() -> None:
    messages = to_model_messages(
        [
            Utterance("prospect", "hello"),
            Utterance("agent", " "),
            Utterance("prospect", "you there?"),
        ]
    )
    assert [m.content for m in messages] == ["hello", "you there?"]


# --- Call tokens -------------------------------------------------------------------------


def test_call_token_round_trip() -> None:
    call_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    token = create_call_token(
        call_id=call_id, tenant_id=tenant_id, secret=TEST_JWT_SECRET, ttl_seconds=300
    )
    principal = decode_call_token(token, secret=TEST_JWT_SECRET)
    assert (principal.call_id, principal.tenant_id) == (call_id, tenant_id)


def test_access_tokens_are_not_call_tokens() -> None:
    access = create_access_token(
        AccessClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), membership_id=uuid.uuid4()),
        secret=TEST_JWT_SECRET,
        ttl_seconds=300,
    )
    with pytest.raises(AuthenticationError):
        decode_call_token(access, secret=TEST_JWT_SECRET)


def test_call_token_with_wrong_secret_is_rejected() -> None:
    token = create_call_token(
        call_id=uuid.uuid4(), tenant_id=uuid.uuid4(), secret="x" * 40, ttl_seconds=300
    )
    with pytest.raises(AuthenticationError):
        decode_call_token(token, secret=TEST_JWT_SECRET)
