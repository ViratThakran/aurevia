import asyncio
from collections.abc import AsyncIterator

from aurevia_voice.language import LanguageSwitch, detect_language


def test_english_replies() -> None:
    assert detect_language("Would Monday at ten thirty work for a quick call?") == "en"
    # English words that look like Hindi ones do not flip the language.
    assert detect_language("The main point is the renewal date for your team.") == "en"


def test_hindi_and_hinglish_replies() -> None:
    assert detect_language("नमस्ते, क्या अभी बात करने का सही समय है?") == "hi"
    assert detect_language("Haan, bilkul. Main Hindi mein baat kar sakti hoon.") == "hi"
    assert detect_language("Aapki team mein kitne log hain?") == "hi"


def test_too_short_to_tell_keeps_the_current_language() -> None:
    assert detect_language("Okay.") is None
    assert detect_language("") is None


async def _chunks(*parts: str) -> AsyncIterator[str]:
    for part in parts:
        yield part


def test_language_is_set_before_the_text_reaches_the_tts() -> None:
    applied: list[str] = []
    switch = LanguageSwitch("en", applied.append)

    async def run() -> list[str]:
        primed = await switch.ready(
            _chunks("Haan, bilkul. ", "Main Hindi ", "mein baat karti hoon.")
        )
        assert applied == ["hi"]  # decided before the TTS reads a single chunk
        return [chunk async for chunk in primed]

    text = asyncio.run(run())
    assert "".join(text) == "Haan, bilkul. Main Hindi mein baat karti hoon."
    assert switch.current == "hi"


def test_switches_back_and_ignores_short_replies() -> None:
    applied: list[str] = []
    switch = LanguageSwitch("hi", applied.append)

    async def say(*parts: str) -> None:
        primed = await switch.ready(_chunks(*parts))
        _ = [chunk async for chunk in primed]

    asyncio.run(say("Okay."))
    assert applied == []
    asyncio.run(say("Sure, Monday at ten works. ", "I will send the invite."))
    assert applied == ["en"]
    asyncio.run(say("Monday at ten works for me too, thanks."))
    assert applied == ["en"]  # no repeated switch when the language is unchanged
