from __future__ import annotations

import asyncio
import uuid

import pytest

from aurevia.conversation.engine import (
    CALL_CONNECTED,
    ConversationEngine,
    InvalidHistoryError,
    TurnRecords,
    Utterance,
    to_model_messages,
)
from aurevia.conversation.prompt import (
    AgentProfile,
    FreeSlot,
    PromptContext,
    build_system_prompt,
)
from aurevia.errors import AuthenticationError
from aurevia.gateway import ModelGateway
from aurevia.identity.security import AccessClaims, create_access_token
from aurevia.providers.fakes import FakeModelProvider
from aurevia.providers.model import ModelMessage
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


def _agent() -> AgentProfile:
    return AgentProfile(
        name="Meera",
        company_name="Acme",
        company_description="We sell term insurance.",
        objective="Book a call.",
        language="English",
    )


def test_listed_free_times_replace_the_lookup_instruction() -> None:
    slots = (FreeSlot(start="2026-10-20T05:30:00+00:00", spoken="Tuesday 20 October at 11 AM"),)
    prompt = build_system_prompt(
        _agent(), SalesState.NEXT_STEP, PromptContext(free_slots=slots), tools_enabled=True
    )
    assert "# Free meeting times (looked up just now)" in prompt
    assert "- Tuesday 20 October at 11 AM (start: 2026-10-20T05:30:00+00:00)" in prompt
    assert 'listed under "Free meeting times"' in prompt
    # The honesty rule about tool results is unchanged.
    assert "unless the tool result says ok is true" in prompt


def test_no_free_times_and_no_lookup_keep_the_old_behaviour() -> None:
    empty = build_system_prompt(
        _agent(), SalesState.NEXT_STEP, PromptContext(free_slots=()), tools_enabled=True
    )
    assert "None in the coming week" in empty
    plain = build_system_prompt(_agent(), SalesState.NEXT_STEP, tools_enabled=True)
    assert "# Free meeting times" not in plain
    # The rules part of the prompt does not depend on whether times were listed (cacheable).
    assert plain.split("# About the company")[0] == empty.split("# About the company")[0]


def test_free_times_are_not_listed_when_tools_are_off() -> None:
    slots = (FreeSlot(start="2026-10-20T05:30:00+00:00", spoken="Tuesday at 11"),)
    prompt = build_system_prompt(_agent(), SalesState.NEXT_STEP, PromptContext(free_slots=slots))
    assert "# Free meeting times" not in prompt
    assert "You cannot book meetings" in prompt


def test_engine_marks_the_stable_prompt_part_as_cacheable() -> None:
    """Two turns at different stages and times share a byte-identical cacheable prefix."""
    model = FakeModelProvider(replies=["Hello.", "Sure."])
    gateway = ModelGateway(
        model, model="m", max_tokens=64, first_token_timeout_seconds=2, total_timeout_seconds=4
    )
    engine = ConversationEngine(gateway)
    messages = (ModelMessage(role="user", content="Hi"),)

    async def turn(state: SalesState, now: str) -> None:
        async for _ in engine.stream_reply(
            agent=_agent(),
            state=state,
            messages=messages,
            new_record=lambda: gateway.new_record({}),
            records=TurnRecords(),
            context=PromptContext(prospect_name="Ravi", now_spoken=now),
        ):
            pass

    asyncio.run(turn(SalesState.DISCOVERY, "Friday 3:40 PM"))
    asyncio.run(turn(SalesState.NEXT_STEP, "Friday 3:42 PM"))
    first, second = model.requests
    assert first.system_cache_prefix > 0
    assert first.system_cache_prefix == second.system_cache_prefix
    prefix = first.system[: first.system_cache_prefix]
    assert prefix == second.system[: second.system_cache_prefix]
    assert "# Right now" not in prefix and "# Current time" not in prefix
    assert "Ravi" in prefix  # who is called stays fixed for the call
    assert first.system != second.system  # the per-turn part did change
