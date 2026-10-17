"""WP-11.4 mood and voice style: off by default, mocked voice provider, no network."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from livekit.agents import llm

from aurevia_voice.backend_client import BackendClient, Utterance
from aurevia_voice.config import WorkerSettings
from aurevia_voice.mood import DEFAULT_STYLE, MOOD_STYLES, style_for
from aurevia_voice.speech_providers import apply_voice_style
from aurevia_voice.turn_metrics import TurnMetricsCollector

MOODS = ("warm", "neutral", "rushed", "annoyed", "skeptical", "confused")


class FakeCartesia:
    label = "livekit.plugins.cartesia.TTS"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update_options(self, **options: Any) -> None:
        self.calls.append(options)


class FakeOtherVoice:
    label = "other.TTS"

    def update_options(self, **options: Any) -> None:
        raise AssertionError("only Cartesia gets speed and emotion")


def test_mood_voice_is_off_by_default() -> None:
    assert WorkerSettings(backend_url="http://backend.invalid").mood_voice is False


def test_every_mood_has_a_style_and_personas_differ() -> None:
    assert set(MOOD_STYLES) == set(MOODS)
    assert style_for("annoyed") == style_for("confused")  # both: softer and slower
    assert style_for("annoyed").speed == "slow" and style_for("rushed").speed == "fast"
    assert style_for("warm") != style_for("annoyed") != style_for("rushed")
    assert style_for("neutral") is DEFAULT_STYLE
    assert style_for(None) is DEFAULT_STYLE and style_for("sarcastic") is DEFAULT_STYLE
    assert style_for("annoyed").label == "slow/Calm" and DEFAULT_STYLE.label == "default"


def test_style_is_applied_only_to_cartesia() -> None:
    voice = FakeCartesia()
    assert apply_voice_style(voice, style_for("annoyed")) is True
    assert apply_voice_style(voice, DEFAULT_STYLE) is True  # back to the defaults
    assert voice.calls == [
        {"speed": "slow", "emotion": ["Calm"]},
        {"speed": "normal", "emotion": []},
    ]
    assert apply_voice_style(FakeOtherVoice(), style_for("annoyed")) is False


def test_backend_mood_event_reaches_the_callback_and_text_is_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        lines = [
            {"type": "mood", "mood": "annoyed"},
            {"type": "delta", "text": "I hear you."},
            {"type": "done", "sales_state": "objection"},
        ]
        return httpx.Response(200, content=b"".join(json.dumps(x).encode() + b"\n" for x in lines))

    seen: list[str] = []
    client = BackendClient(
        base_url="http://backend.test",
        call_id="call-1",
        call_token="call-token-test",
        http=httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ),
        on_mood=seen.append,
    )

    async def run() -> list[str]:
        return [t async for t in client.stream_turn([Utterance("prospect", "This is annoying.")])]

    assert asyncio.run(run()) == ["I hear you."]
    assert seen == ["annoyed"]


def test_voice_style_is_stored_on_agent_turns_only_when_on() -> None:
    off = TurnMetricsCollector()
    off.add(llm.ChatMessage(role="assistant", content=["Hi."]))
    assert "voice_style" not in off.turns[0]

    on = TurnMetricsCollector(voice_style="slow/Calm")
    on.add(llm.ChatMessage(role="user", content=["Ugh."]))
    on.add(llm.ChatMessage(role="assistant", content=["Sorry about that."]))
    assert "voice_style" not in on.turns[0]  # prospect turn
    assert on.turns[1]["voice_style"] == "slow/Calm"
