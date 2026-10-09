from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from livekit.agents import llm

from aurevia_voice.backend_client import BackendClient
from aurevia_voice.config import WorkerSettings
from aurevia_voice.turn_metrics import TurnMetricsCollector


def _message(role: str, metrics: dict[str, float], *, interrupted: bool = False) -> llm.ChatMessage:
    return llm.ChatMessage(
        role=role,  # type: ignore[arg-type]
        content=["what was said is never collected"],
        interrupted=interrupted,
        metrics=metrics,  # type: ignore[arg-type]
    )


def test_collects_timings_only() -> None:
    collector = TurnMetricsCollector()
    collector.add(_message("user", {"transcription_delay": 0.21, "end_of_turn_delay": 0.55}))
    collector.add(
        _message(
            "assistant",
            {"e2e_latency": 0.912, "llm_node_ttft": 0.4, "tts_node_ttfb": 0.18},
            interrupted=True,
        )
    )
    collector.add(_message("system", {}))  # ignored
    collector.add(object())  # non-message items (handoffs, tool calls) are ignored
    assert collector.turns == [
        {
            "seq": 0,
            "role": "prospect",
            "interrupted": False,
            "transcription_delay_ms": 210,
            "end_of_turn_delay_ms": 550,
        },
        {
            "seq": 1,
            "role": "agent",
            "interrupted": True,
            "e2e_latency_ms": 912,
            "llm_ttft_ms": 400,
            "tts_ttfb_ms": 180,
        },
    ]
    assert "never collected" not in json.dumps(collector.turns)


def test_missing_or_invalid_timings_become_none() -> None:
    collector = TurnMetricsCollector()
    collector.add(_message("assistant", {"e2e_latency": -1.0}))
    assert collector.turns[0]["e2e_latency_ms"] is None
    assert collector.turns[0]["llm_ttft_ms"] is None


def test_turn_metrics_upload_in_batches() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/calls/c1/turn-metrics"
        sizes.append(len(json.loads(request.content)["turns"]))
        return httpx.Response(204)

    client = BackendClient(
        base_url="http://backend.test",
        call_id="c1",
        call_token="t",
        http=httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ),
    )
    turns = [{"seq": i, "role": "agent"} for i in range(2500)]
    asyncio.run(client.report_turn_metrics(turns))
    assert sizes == [1000, 1000, 500]


# aurevia_voice.main reads its settings at import time.
def test_turn_handling_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUREVIA_BACKEND_URL", "http://backend.invalid")
    from aurevia_voice.main import turn_handling

    defaults = turn_handling(WorkerSettings(backend_url="http://x"))
    assert defaults["endpointing"] == {"mode": "fixed", "min_delay": 0.5, "max_delay": 1.5}
    assert defaults["preemptive_generation"] == {"enabled": True}
    tuned = turn_handling(
        WorkerSettings(
            backend_url="http://x",
            endpointing_min_delay=0.7,
            endpointing_mode="dynamic",
            preemptive_generation=False,
        )
    )
    assert tuned["endpointing"]["min_delay"] == 0.7
    assert tuned["endpointing"]["mode"] == "dynamic"
    assert tuned["preemptive_generation"] == {"enabled": False}


def test_silence_reprompts_then_hangs_up_and_speech_resets() -> None:
    from aurevia_voice.silence import SilenceTracker

    tracker = SilenceTracker(reprompts_before_hang_up=1)
    assert tracker.on_user_state("listening") is None
    assert tracker.on_user_state("away") == "reprompt"
    assert tracker.on_user_state("speaking") is None  # they answered: start over
    assert tracker.on_user_state("away") == "reprompt"
    assert tracker.on_user_state("away") == "hang_up"

    immediate = SilenceTracker(reprompts_before_hang_up=0)
    assert immediate.on_user_state("away") == "hang_up"


def test_transcript_collects_spoken_text_in_order() -> None:
    from aurevia_voice.transcript import TranscriptCollector

    collector = TranscriptCollector()
    collector.add(_message("assistant", {}))  # "what was said is never collected" content
    collector.add(llm.ChatMessage(role="user", content=["  hello there  "]))
    collector.add(llm.ChatMessage(role="user", content=[""]))  # empty: skipped
    collector.add(llm.ChatMessage(role="system", content=["instructions"]))  # skipped
    assert collector.lines == [
        {"seq": 0, "speaker": "agent", "text": "what was said is never collected"},
        {"seq": 1, "speaker": "prospect", "text": "hello there"},
    ]
