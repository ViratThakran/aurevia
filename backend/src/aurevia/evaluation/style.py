"""Conversation-style metrics for spoken replies (Phase 10 voice-quality baseline).

Measured on the agent's replies in the sales scenarios, so prompt changes can be compared:
- words per reply (spoken length: ~150 words a minute, so 30 words is ~12 s of speech)
- share of replies longer than ``LONG_REPLY_WORDS``
- questions per reply (the prompt asks for at most one)
- share of replies opening with a stock acknowledgement ("I understand", "Great", ...)
- share of replies whose first two words repeat an earlier reply's in the same call
- filler phrases ("great question", "absolutely", "to be honest", ...)
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

LONG_REPLY_WORDS = 30
STOCK_OPENERS = re.compile(
    r"^(?:i (?:completely |totally )?understand|i hear you|got it|great|perfect|absolutely|"
    r"thanks? (?:you )?for|that'?s (?:great|a great|completely)|i appreciate)",
    re.IGNORECASE,
)
FILLERS = re.compile(
    r"\b(?:great question|absolutely|to be honest|i completely understand|no worries at all|"
    r"just to let you know|as i mentioned)\b",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", text.lower())


@dataclass(frozen=True)
class StyleMetrics:
    replies: int
    avg_words: float
    long_reply_rate: float
    avg_questions: float
    multi_question_rate: float
    stock_opener_rate: float
    repeated_opener_rate: float
    fillers_per_reply: float

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in self.__dict__.items()}


def measure(calls: Sequence[Sequence[str]]) -> StyleMetrics:
    """``calls``: the agent's replies of each conversation, in order."""
    replies = [r for call in calls for r in call if r.strip()]
    n = len(replies) or 1
    words = [len(_words(r)) for r in replies]
    questions = [r.count("?") for r in replies]
    repeated = 0
    for call in calls:
        seen: set[tuple[str, ...]] = set()
        for reply in call:
            opener = tuple(_words(reply)[:2])
            if opener and opener in seen:
                repeated += 1
            seen.add(opener)
    return StyleMetrics(
        replies=len(replies),
        avg_words=sum(words) / n,
        long_reply_rate=sum(w > LONG_REPLY_WORDS for w in words) / n,
        avg_questions=sum(questions) / n,
        multi_question_rate=sum(q > 1 for q in questions) / n,
        stock_opener_rate=sum(bool(STOCK_OPENERS.match(r.strip())) for r in replies) / n,
        repeated_opener_rate=repeated / n,
        fillers_per_reply=sum(len(FILLERS.findall(r)) for r in replies) / n,
    )
