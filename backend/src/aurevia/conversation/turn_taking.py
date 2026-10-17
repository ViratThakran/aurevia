"""WP-11.6 turn-taking polish: a few clear moments get a fixed, instant reply. Built early, off
by default (``AUREVIA_TURN_TAKING``).

When the prospect's latest words are clearly one of these, the agent answers without the
model (no tool can run, so nothing is claimed that did not happen):

- they cut the agent off and then only said "oh, sorry" or "um": "Sorry, go ahead."
- "hold on", "one second": "Sure, take your time."
- "can you repeat that?", "pardon?": the agent's last words again, exactly
- they are driving: "No problem, drive safely. Goodbye." and the call ends (no promise to
  call back: a fixed reply cannot schedule one)
- only a goodbye: "Thanks for your time. Goodbye." and the call ends

Anything that mentions calling, numbers or stopping calls ("don't call me again") always goes
to the model, so the do-not-call tool is never bypassed. Long silences keep the worker's
existing re-prompt and hang-up.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Move(StrEnum):
    GO_AHEAD = "go_ahead"
    HOLD = "hold"
    REPEAT = "repeat"
    DRIVING = "driving"
    GOODBYE = "goodbye"


@dataclass(frozen=True)
class Reply:
    move: Move
    text: str
    end_call: bool = False


class Spoken(Protocol):
    @property
    def role(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def interrupted(self) -> bool: ...


# Words that must reach the model: calls, numbers, opting out, or a question about the offer.
_NEVER = re.compile(
    r"\b(?:call(?:ing|ed)?|number|remove|stop|don'?t|do not|unsubscribe|dnd|price|cost)\b"
)
_FILLER = frozenset({"oh", "sorry", "um", "uh", "er", "ah", "hm", "hmm", "no", "go", "on", "ahead"})
_HOLD = re.compile(
    r"^(?:(?:please|sorry|okay|ok)\s+)?(?:hold on|wait|one (?:sec|second|moment|minute)|"
    r"just a (?:sec|second|moment|minute)|give me a (?:sec|second|moment|minute)|ek minute|"
    r"ruko|ruk(?:iye|o) zara)\b"
)
_REPEAT = re.compile(
    r"(?:(?:can|could) you (?:please )?(?:repeat|say) (?:that|it)(?: again)?|"
    r"say (?:that|it) again|repeat (?:that|please)|come again|pardon|"
    r"what did you say|(?:didn'?t|did not) (?:catch|hear) (?:that|you)|^sorry$|^what$)"
)
_DRIVING = re.compile(r"\b(?:i'?m|i am|im) (?:driving|on the road|behind the wheel)\b")
_FAREWELL = frozenset(
    {
        "bye",
        "goodbye",
        "ok",
        "okay",
        "thanks",
        "thank",
        "you",
        "then",
        "talk",
        "later",
        "see",
        "ya",
        "alright",
        "cheers",
        "take",
        "care",
        "have",
        "a",
        "good",
        "day",
        "nice",
        "one",
    }
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _normal(text: str) -> str:
    return " ".join(_words(text))


def classify(history: Sequence[Spoken]) -> Reply | None:
    """A fixed reply for the prospect's latest words, or None (the model answers)."""
    if not history or history[-1].role != "prospect":
        return None
    said = _normal(history[-1].text)
    words = said.split()
    if not words or _NEVER.search(said):
        return None
    agent_turns = [u for u in history[:-1] if u.role == "agent" and u.text.strip()]
    last_agent = agent_turns[-1] if agent_turns else None
    previous = history[-2] if len(history) > 1 else None
    if (
        previous is not None
        and previous.role == "agent"
        and previous.interrupted
        and len(words) <= 3
        and set(words) <= _FILLER
    ):
        return Reply(Move.GO_AHEAD, "Sorry, go ahead.")
    if len(words) <= 8 and _HOLD.search(said):
        return Reply(Move.HOLD, "Sure, take your time.")
    if last_agent is not None and len(words) <= 10 and _REPEAT.search(said):
        return Reply(Move.REPEAT, f"Sure. {last_agent.text.strip()}")
    if _DRIVING.search(said):
        return Reply(Move.DRIVING, "No problem, drive safely. Goodbye.", end_call=True)
    if len(words) <= 8 and set(words) <= _FAREWELL and {"bye", "goodbye"} & set(words):
        return Reply(Move.GOODBYE, "Thanks for your time. Goodbye.", end_call=True)
    return None
