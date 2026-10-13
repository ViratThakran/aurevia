import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest

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


def test_hinglish_dates_times_and_numbers() -> None:
    assert detect_language("Somvaar ko 10 baje aapke saath call rakhte hain?") == "hi"
    assert detect_language("Kal subah 11 baje theek rahega?") == "hi"
    assert detect_language("सोमवार को 10:30 बजे मीटिंग रखें?") == "hi"  # digits inside Devanagari


def test_indian_english_stays_english() -> None:
    # Indian names and places do not make a reply Hindi.
    assert detect_language("Hi Ravi, this is Aria from Sunrise Insurance in Pune.") == "en"
    assert detect_language("Would Monday the 12th at 10:30 am work for Kumar Textiles?") == "en"
    assert detect_language("We cover teams from 10 to 200 people, Mr. Sharma.") == "en"


def test_english_to_hindi_and_back_in_one_call() -> None:
    applied: list[str] = []
    switch = LanguageSwitch("en", applied.append)

    async def say(text: str) -> None:
        primed = await switch.ready(_chunks(text))
        _ = [chunk async for chunk in primed]

    asyncio.run(say("Hi, this is Aria from Sunrise Insurance. Is now a good time?"))
    asyncio.run(say("Haan ji, main Hindi mein baat kar sakti hoon."))
    asyncio.run(say("Ji."))  # too short: stays Hindi
    asyncio.run(say("Sure, let me continue in English then."))
    assert applied == ["hi", "en"]


def test_interrupted_reply_while_choosing_the_language() -> None:
    """The prospect barges in before the first sentence is complete: the TTS stream is
    cancelled cleanly and the switch keeps a consistent language."""
    applied: list[str] = []
    switch = LanguageSwitch("en", applied.append)

    async def slow() -> AsyncIterator[str]:
        yield "Haan "
        await asyncio.sleep(10)  # the rest never arrives
        yield "bilkul."

    async def run() -> None:
        task = asyncio.create_task(switch.ready(slow()))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert applied == [] and switch.current == "en"


def test_reply_that_ends_before_a_sentence_still_gets_a_language() -> None:
    applied: list[str] = []
    switch = LanguageSwitch("en", applied.append)

    async def run() -> str:
        primed = await switch.ready(_chunks("Aapki ", "team ", "mein ", "kitne log hain"))
        return "".join([c async for c in primed])

    assert asyncio.run(run()) == "Aapki team mein kitne log hain"
    assert applied == ["hi"]


def test_speaking_agent_sets_the_tts_language_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real agent node: the TTS stream (created inside the default node) must see the
    language of the reply it is about to speak."""
    monkeypatch.setenv("AUREVIA_BACKEND_URL", "http://backend.invalid")
    from livekit.agents import Agent

    from aurevia_voice.main import SpeakingAgent

    language_seen: list[str] = []
    current = {"language": "en"}

    async def default_tts_node(agent: Any, text: AsyncIterator[str], settings: Any) -> Any:
        language_seen.append(current["language"])  # what a new TTS stream would copy
        async for _ in text:
            pass
        yield "frame"

    monkeypatch.setattr(Agent.default, "tts_node", staticmethod(default_tts_node))
    switch = LanguageSwitch("en", lambda lang: current.update(language=lang))
    agent = SpeakingAgent(switch)

    async def speak(text: str) -> list[Any]:
        return [f async for f in agent.tts_node(_chunks(text), None)]  # type: ignore[arg-type]

    assert asyncio.run(speak("Haan ji, main Hindi mein baat kar sakti hoon.")) == ["frame"]
    asyncio.run(speak("Sure, Monday at ten thirty works for me."))
    assert language_seen == ["hi", "en"]
