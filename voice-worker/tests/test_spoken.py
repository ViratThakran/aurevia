"""WP-11.5 natural speech: off by default; amounts, phone numbers, dates, pronunciations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from aurevia_voice.config import WorkerSettings
from aurevia_voice.spoken import indian_words, natural_chunks, speak_naturally


def test_natural_speech_is_off_by_default() -> None:
    settings = WorkerSettings(backend_url="http://backend.invalid")
    assert settings.natural_speech is False and settings.pronunciations == {}


@pytest.mark.parametrize(
    ("number", "words"),
    [
        (0, "zero"),
        (15, "fifteen"),
        (45, "forty-five"),
        (999, "nine hundred ninety-nine"),
        (1500, "one thousand five hundred"),
        (150000, "one lakh fifty thousand"),
        (2500000, "twenty-five lakh"),
        (12345678, "one crore twenty-three lakh forty-five thousand six hundred seventy-eight"),
    ],
)
def test_indian_numbering(number: int, words: str) -> None:
    assert indian_words(number) == words


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("It costs ₹1,50,000 a year.", "It costs one lakh fifty thousand rupees a year."),
        ("About Rs. 2500 per person.", "About two thousand five hundred rupees per person."),
        ("Just ₹1.", "Just one rupee."),
        ("₹99.50 only.", "ninety-nine rupees and fifty paise only."),
        (
            "Call 98765 43210 today.",
            "Call nine eight seven six five, four three two one zero today.",
        ),
        (
            "Or +91 98765-43210.",
            "Or plus nine one, nine eight seven six five, four three two one zero.",
        ),
        ("On 17/10/2026 at noon.", "On 17 October 2026 at noon."),
        ("We have 40 staff and 3 offices.", "We have 40 staff and 3 offices."),  # unchanged
        ("Policy 123456789012 is active.", "Policy 123456789012 is active."),  # not a phone
        ("On 45/13/2026.", "On 45/13/2026."),  # not a real date: unchanged
    ],
)
def test_speak_naturally(written: str, spoken: str) -> None:
    assert speak_naturally(written) == spoken


def test_pronunciations_are_whole_word_and_case_insensitive() -> None:
    names = {"Aurevia": "Aw-REE-vee-uh"}
    assert speak_naturally("Welcome to Aurevia, aurevia!", names) == (
        "Welcome to Aw-REE-vee-uh, Aw-REE-vee-uh!"
    )
    assert speak_naturally("Aureviaxyz stays.", names) == "Aureviaxyz stays."


def test_streamed_chunks_never_cut_a_number_in_two() -> None:
    async def chunks() -> AsyncIterator[str]:
        for piece in ["It is ₹1,5", "0,000. Call 987", "65 43", "210 and ask for Aur", "evia."]:
            yield piece

    async def run() -> str:
        return "".join([c async for c in natural_chunks(chunks(), {"Aurevia": "Aw-REE-vee-uh"})])

    assert asyncio.run(run()) == (
        "It is one lakh fifty thousand rupees. Call nine eight seven six five, "
        "four three two one zero and ask for Aw-REE-vee-uh."
    )
