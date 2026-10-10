"""Pick the TTS language for each reply from the reply's own words.

The agent answers in the language the prospect uses, so a call can move between English,
Hindi and Hinglish. Cartesia reads text with the phonemes of the language it is given: Hindi
read as English sounds wrong. Before a reply is synthesized we look at its first words and
switch the TTS language to match, keeping the previous language when the text is too short to
tell (e.g. "Okay.").
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import Literal

Language = Literal["en", "hi"]

_DEVANAGARI = re.compile("[" + chr(0x0900) + "-" + chr(0x097F) + "]")
_LATIN_WORD = re.compile(r"[a-zA-Z]+")
# Common Hindi words written in Latin script (Hinglish). Words that are also everyday English
# ("me", "to", "the", "main", "log", "so", "hi") are left out on purpose.
_HINDI_WORDS = frozenset(
    [
        "aap",
        "aapka",
        "aapke",
        "aapki",
        "aapko",
        "aapne",
        "hum",
        "hamara",
        "hamare",
        "hamari",
        "humein",
        "mein",
        "mera",
        "mere",
        "meri",
        "mujhe",
        "tum",
        "tumhara",
        "hai",
        "hain",
        "tha",
        "thi",
        "ho",
        "hoga",
        "hogi",
        "hoge",
        "raha",
        "rahe",
        "rahi",
        "kya",
        "kyun",
        "kaise",
        "kab",
        "kahan",
        "kaun",
        "kitna",
        "kitne",
        "kitni",
        "nahi",
        "nahin",
        "haan",
        "ji",
        "bilkul",
        "theek",
        "thik",
        "accha",
        "acha",
        "achha",
        "bahut",
        "zaroor",
        "zarur",
        "chahiye",
        "chahenge",
        "chahte",
        "chahti",
        "sakta",
        "sakti",
        "sakte",
        "karna",
        "karke",
        "karte",
        "karti",
        "kariye",
        "kijiye",
        "dijiye",
        "batayiye",
        "bataiye",
        "bata",
        "batao",
        "samajh",
        "aur",
        "lekin",
        "par",
        "phir",
        "abhi",
        "agar",
        "toh",
        "bhi",
        "wala",
        "wale",
        "wali",
        "yeh",
        "woh",
        "ye",
        "wo",
        "isme",
        "usme",
        "iske",
        "uske",
        "liye",
        "saath",
        "sabse",
        "dhanyavaad",
        "dhanyawad",
        "shukriya",
        "namaste",
        "mahina",
        "mahine",
        "saal",
        "din",
        "kal",
        "aaj",
        "logon",
        "kuch",
        "koi",
        "baat",
    ]
)
MIN_WORDS = 3  # below this the reply is too short to judge; keep the current language


def detect_language(text: str) -> Language | None:
    """ "hi" for Devanagari or Hinglish, "en" for English, None when it cannot tell."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    devanagari = sum(1 for c in letters if _DEVANAGARI.match(c))
    if devanagari / len(letters) >= 0.3:
        return "hi"
    words = [w.lower() for w in _LATIN_WORD.findall(text)]
    if len(words) < MIN_WORDS:
        return None
    hindi = sum(1 for w in words if w in _HINDI_WORDS)
    return "hi" if hindi >= 2 and hindi / len(words) >= 0.25 else "en"


# Enough text to judge: the first sentence that tells the language, or this many characters.
_SENTENCE_END = re.compile(r"[.!?।]\s")
PEEK_CHARS = 60


class LanguageSwitch:
    """Tracks the TTS language for a call and applies changes through ``apply``."""

    def __init__(self, initial: str, apply: Callable[[Language], None]) -> None:
        self.current = initial
        self._apply = apply

    def choose(self, text: str) -> None:
        language = detect_language(text)
        if language is not None and language != self.current:
            self._apply(language)
            self.current = language

    async def ready(self, text: AsyncIterable[str]) -> AsyncIterator[str]:
        """Read the first words and set the language *before* synthesis starts; return the
        whole text, unchanged, for the TTS. (A TTS stream copies its options when created.)"""
        iterator = aiter(text)
        buffered: list[str] = []
        async for chunk in iterator:
            buffered.append(chunk)
            seen = "".join(buffered)
            # A short first sentence ("Haan, bilkul.") may not be enough to tell: read on.
            if len(seen) >= PEEK_CHARS or (
                _SENTENCE_END.search(seen + " ") and detect_language(seen) is not None
            ):
                break
        self.choose("".join(buffered))
        return _replay(buffered, iterator)


async def _replay(buffered: list[str], rest: AsyncIterator[str]) -> AsyncIterator[str]:
    for chunk in buffered:
        yield chunk
    async for chunk in rest:
        yield chunk
