"""WP-11.6 turn-taking: fixed replies for clear moments; everything else goes to the model."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from aurevia.config import Settings
from aurevia.conversation.turn_taking import Move, classify


@dataclass(frozen=True)
class U:
    role: str
    text: str
    interrupted: bool = False


AGENT_LINE = U("agent", "We cover forty people from day one.")


def _move(said: str, *, cut_off: bool = False) -> Move | None:
    history = [
        U("agent", "Hello, this is Meera."),
        U("prospect", "Hi."),
        U("agent", AGENT_LINE.text, interrupted=cut_off),
        U("prospect", said),
    ]
    reply = classify(history)
    return reply.move if reply else None


def test_turn_taking_is_off_by_default() -> None:
    assert Settings(_env_file=None).turn_taking is False


@pytest.mark.parametrize(
    ("said", "cut_off", "move"),
    [
        ("Oh, sorry.", True, Move.GO_AHEAD),
        ("Um", True, Move.GO_AHEAD),
        ("Hold on.", False, Move.HOLD),
        ("One second please", False, Move.HOLD),
        ("Ek minute", False, Move.HOLD),
        ("Sorry, can you repeat that?", False, Move.REPEAT),
        ("Pardon?", False, Move.REPEAT),
        ("I didn't catch that.", False, Move.REPEAT),
        ("I'm driving right now.", False, Move.DRIVING),
        ("Okay, bye.", False, Move.GOODBYE),
        ("Thanks, goodbye!", False, Move.GOODBYE),
    ],
)
def test_clear_moments_get_a_fixed_reply(said: str, cut_off: bool, move: Move) -> None:
    assert _move(said, cut_off=cut_off) == move


@pytest.mark.parametrize(
    "said",
    [
        "Please don't call this number again. Bye.",  # do-not-call must reach the model
        "Stop calling me, goodbye.",
        "Call me next week, bye.",
        "Oh, sorry.",  # not after being cut off: the model answers
        "Hold on, what does it cost?",
        "We are forty people and renewal is in March, so bye for now I guess we will see later",
        "Repeat the price please",
        "Yes, that sounds good.",
    ],
)
def test_everything_else_goes_to_the_model(said: str) -> None:
    assert _move(said) is None


def test_repeat_says_the_last_agent_line_exactly_and_goodbye_ends_the_call() -> None:
    repeat = classify([AGENT_LINE, U("prospect", "Sorry, say that again?")])
    assert repeat is not None and repeat.text == f"Sure. {AGENT_LINE.text}"
    assert repeat.end_call is False
    bye = classify([AGENT_LINE, U("prospect", "Okay thank you, bye.")])
    assert bye is not None and bye.end_call is True
    driving = classify([AGENT_LINE, U("prospect", "I am driving.")])
    assert driving is not None and driving.end_call is True
    assert "call back" not in driving.text  # a fixed reply cannot schedule a callback


def test_no_agent_line_yet_means_no_repeat() -> None:
    assert classify([U("prospect", "Pardon?")]) is None
