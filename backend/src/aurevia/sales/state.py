"""The sales state machine: deterministic, owned by the server, never by the LLM.

Phase 2 uses the states to steer each turn (the goal the prompt gives the model) and moves
only through the opening: NEW -> OPENING when the call starts, OPENING -> DISCOVERY after the
prospect first speaks. In Phase 5 the LLM may *propose* further transitions through tools;
``transition`` stays the only way a state changes, and it rejects anything not listed here.
"""

from __future__ import annotations

from enum import StrEnum


class SalesState(StrEnum):
    NEW = "new"
    OPENING = "opening"
    DISCOVERY = "discovery"
    QUALIFICATION = "qualification"
    PITCH = "pitch"
    OBJECTION = "objection"
    NEXT_STEP = "next_step"
    FOLLOW_UP = "follow_up"
    MEETING_BOOKED = "meeting_booked"
    HUMAN_HANDOFF = "human_handoff"
    COMPLETED = "completed"


_ACTIVE = {
    SalesState.DISCOVERY,
    SalesState.QUALIFICATION,
    SalesState.PITCH,
    SalesState.OBJECTION,
    SalesState.NEXT_STEP,
}

TRANSITIONS: dict[SalesState, frozenset[SalesState]] = {
    SalesState.NEW: frozenset({SalesState.OPENING, SalesState.COMPLETED}),
    SalesState.OPENING: frozenset(
        {SalesState.DISCOVERY, SalesState.HUMAN_HANDOFF, SalesState.COMPLETED}
    ),
    SalesState.DISCOVERY: frozenset(_ACTIVE | {SalesState.HUMAN_HANDOFF, SalesState.COMPLETED}),
    SalesState.QUALIFICATION: frozenset(_ACTIVE | {SalesState.HUMAN_HANDOFF, SalesState.COMPLETED}),
    SalesState.PITCH: frozenset(_ACTIVE | {SalesState.HUMAN_HANDOFF, SalesState.COMPLETED}),
    SalesState.OBJECTION: frozenset(_ACTIVE | {SalesState.HUMAN_HANDOFF, SalesState.COMPLETED}),
    SalesState.NEXT_STEP: frozenset(
        {
            SalesState.FOLLOW_UP,
            SalesState.MEETING_BOOKED,
            SalesState.OBJECTION,
            SalesState.HUMAN_HANDOFF,
            SalesState.COMPLETED,
        }
    ),
    SalesState.FOLLOW_UP: frozenset({SalesState.COMPLETED}),
    SalesState.MEETING_BOOKED: frozenset({SalesState.COMPLETED}),
    SalesState.HUMAN_HANDOFF: frozenset({SalesState.COMPLETED}),
    SalesState.COMPLETED: frozenset(),
}

# What the agent is trying to achieve in each state; rendered into the turn's prompt.
STATE_GOALS: dict[SalesState, str] = {
    SalesState.NEW: "The call has not started.",
    SalesState.OPENING: (
        "You have just greeted the prospect. Confirm it is a good moment to talk and say "
        "briefly why you are calling."
    ),
    SalesState.DISCOVERY: (
        "Understand the prospect's situation and needs. Ask one open question at a time and "
        "listen; do not pitch yet."
    ),
    SalesState.QUALIFICATION: (
        "Find out whether the prospect is a fit: need, timing, who decides, and budget range."
    ),
    SalesState.PITCH: (
        "Explain only the parts of the offering that match what the prospect told you."
    ),
    SalesState.OBJECTION: "Acknowledge the concern, ask what is behind it, then address it.",
    SalesState.NEXT_STEP: "Agree a concrete next step the prospect is comfortable with.",
    SalesState.FOLLOW_UP: "Confirm the follow-up and close the call politely.",
    SalesState.MEETING_BOOKED: "Confirm the meeting details and close the call politely.",
    SalesState.HUMAN_HANDOFF: "Tell the prospect a colleague will continue with them.",
    SalesState.COMPLETED: "The call is over.",
}


class InvalidTransitionError(ValueError):
    pass


def transition(current: SalesState, target: SalesState) -> SalesState:
    if target not in TRANSITIONS[current]:
        raise InvalidTransitionError(f"{current.value} -> {target.value} is not allowed")
    return target


def after_prospect_turn(current: SalesState) -> SalesState:
    """The Phase 2 rule: the first thing the prospect says moves the call into discovery."""
    if current == SalesState.OPENING:
        return transition(current, SalesState.DISCOVERY)
    return current
