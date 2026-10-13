"""Voice-service failures: classified, reported to the browser, safely retryable."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from livekit.agents import APIConnectionError, APIError, APIStatusError, APITimeoutError

from aurevia_voice.language import LanguageSwitch
from aurevia_voice.voice_status import VoiceStatusReporter, classify

SECRET = "sk-secret-0123456789"


def _status(code: int, message: str = "Invalid response status") -> APIStatusError:
    return APIStatusError(message, status_code=code, retryable=False)


# --- classification ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "category", "status"),
    [
        (_status(402), "credits_exhausted", 402),
        (_status(429), "rate_limited", 429),
        (_status(503), "provider_unavailable", 503),
        (_status(500), "provider_unavailable", 500),
        (_status(408), "timeout", 408),
        (_status(400), "unknown", 400),
        (APITimeoutError(), "timeout", None),
        (TimeoutError(), "timeout", None),
        (APIConnectionError("ClientConnectorError"), "provider_unavailable", None),
        (APIError("no audio frames were pushed for text: Hello"), "unknown", None),
        (ValueError("anything else"), "unknown", None),
    ],
)
def test_classification(error: BaseException, category: str, status: int | None) -> None:
    assert classify(error) == (category, status)


def test_a_provider_error_carried_as_text_is_still_classified() -> None:
    error = APIError("Cartesia returned error: {'type': 'error', 'status_code': 402}")
    assert classify(error) == ("credits_exhausted", 402)


def test_the_cause_chain_is_followed() -> None:
    try:
        try:
            raise _status(402)
        except APIStatusError as inner:
            raise APIError("no audio frames were pushed for text: Hi") from inner
    except APIError as outer:
        assert classify(outer) == ("credits_exhausted", 402)


def test_backend_model_failures_are_mapped_from_our_own_codes() -> None:
    error = APIStatusError("backend turn failed: rate_limited", status_code=502, retryable=False)
    assert classify(error) == ("rate_limited", 502)
    error = APIStatusError("backend turn failed: timeout", status_code=502, retryable=False)
    assert classify(error) == ("timeout", 502)
    error = APIStatusError("backend turn failed: provider_error", status_code=502, retryable=False)
    assert classify(error) == ("provider_unavailable", 502)


# --- reporter ------------------------------------------------------------------------------


class Harness:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self.destinations: list[str | None] = []
        self.spoken: list[str] = []
        self.say_error: BaseException | None = None
        self.reporter = VoiceStatusReporter(
            call_id="call-1", provider="Cartesia", publish=self._publish, say=self._say
        )

    async def _publish(self, payload: dict[str, Any], destination: str | None) -> None:
        self.published.append(payload)
        self.destinations.append(destination)

    async def _say(self, words: str) -> None:
        self.spoken.append(words)
        if self.say_error is not None:
            # A failing retry goes through the speaking agent, which reports it.
            self.reporter.report(self.say_error, source="voice", text=words)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _settle() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_a_failed_reply_is_published_with_its_words_and_no_provider_text() -> None:
    harness = Harness()

    async def go() -> None:
        failure = _status(402, f"Bearer {SECRET} credits limit reached for acct 42")
        harness.reporter.report(failure, source="voice", text="Forty staff, got it.")
        await _settle()

    _run(go())
    [event] = harness.published
    assert event["type"] == "voice_issue"
    assert (event["source"], event["category"]) == ("voice", "credits_exhausted")
    assert event["text"] == "Forty staff, got it." and event["retryable"] is True
    assert SECRET not in json.dumps(event) and "acct" not in json.dumps(event)


def test_the_failure_log_has_provider_category_and_call_but_no_words_or_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Harness()

    async def go() -> None:
        failure = _status(402, f"Bearer {SECRET} credits limit reached")
        harness.reporter.report(failure, source="voice", text="Please book Tuesday at ten.")
        await _settle()

    with caplog.at_level(logging.INFO):
        _run(go())
    record = next(r for r in caplog.records if r.getMessage() == "Voice service failure")
    assert record.__dict__["provider"] == "Cartesia"
    assert record.__dict__["category"] == "credits_exhausted"
    assert record.__dict__["call_id"] == "call-1"
    assert record.__dict__["http_status"] == 402
    everything = " ".join(str(v) for r in caplog.records for v in r.__dict__.values())
    assert SECRET not in everything and "book Tuesday" not in everything


def test_listening_and_model_failures_are_reported_without_a_retry() -> None:
    harness = Harness()

    async def go() -> None:
        harness.reporter.report(_status(429), source="listening")
        harness.reporter.report(APITimeoutError(), source="model")
        await _settle()

    _run(go())
    assert [(e["source"], e["category"], e["retryable"]) for e in harness.published] == [
        ("listening", "rate_limited", False),
        ("model", "timeout", False),
    ]
    assert all(e["text"] is None for e in harness.published)


def test_retry_speaks_the_stored_words_once_and_reports_recovery() -> None:
    harness = Harness()

    async def go() -> dict[str, Any]:
        failure_id = harness.reporter.report(
            _status(402), source="voice", text="Booked: Monday 10."
        )
        await _settle()
        first = await harness.reporter.retry(failure_id)
        second = await harness.reporter.retry(failure_id)  # a double click
        await _settle()
        return {"first": first, "second": second}

    result = _run(go())
    assert result["first"] == {"ok": True}
    assert result["second"] == {"ok": False, "reason": "not_available"}
    assert harness.spoken == ["Booked: Monday 10."]  # spoken exactly once
    assert harness.published[-1]["type"] == "speech_recovered"


def test_retry_that_fails_again_is_reported_not_called_a_success() -> None:
    harness = Harness()
    harness.say_error = _status(402)

    async def go() -> dict[str, Any]:
        failure_id = harness.reporter.report(_status(402), source="voice", text="Hello there.")
        await _settle()
        result = await harness.reporter.retry(failure_id)
        await _settle()
        return result

    assert _run(go()) == {"ok": False, "reason": "failed"}
    types = [e["type"] for e in harness.published]
    assert types == ["voice_issue", "voice_issue"]  # no "speech_recovered"
    assert harness.published[-1]["text"] == "Hello there."  # can be retried again


def test_retry_cannot_be_used_to_speak_arbitrary_text() -> None:
    harness = Harness()

    async def go() -> str:
        return await harness.reporter.handle_rpc(json.dumps({"id": "nope", "text": "Pay me."}))

    assert json.loads(_run(go())) == {"ok": False, "reason": "not_available"}
    assert harness.spoken == []
    assert json.loads(_run(harness.reporter.handle_rpc("not json"))) == {
        "ok": False,
        "reason": "bad_request",
    }


def test_retrying_audio_never_calls_the_model_or_runs_tools() -> None:
    """Speech retry has no path to the backend: only ``say`` is injected into the reporter."""

    class BackendThatMustNotBeCalled:
        calls = 0

        async def stream_turn(self, *_: Any) -> AsyncIterator[str]:
            type(self).calls += 1
            yield "never"

    backend = BackendThatMustNotBeCalled()
    harness = Harness()
    assert not hasattr(harness.reporter, "_backend")

    async def go() -> None:
        failure_id = harness.reporter.report(
            _status(402), source="voice", text="I have booked you for Monday at ten."
        )
        await _settle()
        await harness.reporter.retry(failure_id)

    _run(go())
    assert BackendThatMustNotBeCalled.calls == 0 and backend is not None
    assert harness.spoken == ["I have booked you for Monday at ten."]


def test_only_the_latest_failures_are_kept() -> None:
    harness = Harness()

    async def go() -> list[str]:
        ids = [
            harness.reporter.report(_status(402), source="voice", text=f"reply {i}")
            for i in range(8)
        ]
        await _settle()
        return ids

    ids = _run(go())
    assert _run(harness.reporter.retry(ids[0])) == {"ok": False, "reason": "not_available"}
    assert _run(harness.reporter.retry(ids[-1])) == {"ok": True}


def test_a_publish_failure_never_raises() -> None:
    async def broken(_: dict[str, Any], __: str | None) -> None:
        raise RuntimeError("room closed")

    reporter = VoiceStatusReporter(
        call_id="c", provider="Cartesia", publish=broken, say=lambda _: asyncio.sleep(0)
    )

    async def go() -> None:
        reporter.report(_status(402), source="voice", text="Hi")
        await _settle()

    _run(go())  # must not raise


# --- the speaking agent's TTS node ---------------------------------------------------------


async def _chunks(*parts: str) -> AsyncIterator[str]:
    for part in parts:
        yield part


def _agent(
    monkeypatch: pytest.MonkeyPatch, node: Any, failures: list[tuple[BaseException, str]]
) -> Any:
    monkeypatch.setenv("AUREVIA_BACKEND_URL", "http://backend.invalid")
    from livekit.agents import Agent

    from aurevia_voice.main import SpeakingAgent

    monkeypatch.setattr(Agent.default, "tts_node", staticmethod(node))
    return SpeakingAgent(
        LanguageSwitch("en", lambda _: None), on_failure=lambda e, t: failures.append((e, t))
    )


def test_successful_audio_flows_and_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    failures: list[tuple[BaseException, str]] = []

    async def node(agent: Any, text: AsyncIterator[str], settings: Any) -> Any:
        async for _ in text:
            pass
        yield "frame-1"
        yield "frame-2"

    agent = _agent(monkeypatch, node, failures)

    async def go() -> list[Any]:
        return [f async for f in agent.tts_node(_chunks("Hello ", "there."), None)]

    assert _run(go()) == ["frame-1", "frame-2"]
    assert failures == []


def test_tts_failure_keeps_the_whole_reply_and_does_not_end_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[tuple[BaseException, str]] = []

    async def node(agent: Any, text: AsyncIterator[str], settings: Any) -> Any:
        async for _ in text:
            break  # reads only the first chunk, then the provider fails
        raise _status(402)
        yield  # pragma: no cover - makes this an async generator

    agent = _agent(monkeypatch, node, failures)

    async def go() -> list[Any]:
        # The reply is still streaming in when the provider fails.
        return [
            f
            async for f in agent.tts_node(
                _chunks("Forty staff. ", "Renewal in March. ", "Okay?"), None
            )
        ]

    assert _run(go()) == []  # no exception escapes: the session is not torn down
    [(error, words)] = failures
    assert classify(error) == ("credits_exhausted", 402)
    assert words == "Forty staff. Renewal in March. Okay?"


def test_an_interruption_is_not_reported_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failures: list[tuple[BaseException, str]] = []

    async def node(agent: Any, text: AsyncIterator[str], settings: Any) -> Any:
        async for _ in text:
            pass
        yield "frame"

    agent = _agent(monkeypatch, node, failures)

    async def go() -> None:
        async def slow() -> AsyncIterator[str]:
            yield "Haan, "
            await asyncio.sleep(10)
            yield "bilkul."

        async def consume() -> None:
            async for _ in agent.tts_node(slow(), None):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(go())
    assert failures == []


def test_a_browser_that_joins_after_the_failure_is_told() -> None:
    """The greeting can fail before the caller's browser is in the room."""
    harness = Harness()

    async def go() -> None:
        harness.reporter.report(_status(402), source="voice", text="Hi, this is Aria.")
        await _settle()
        harness.published.clear()
        harness.destinations.clear()
        harness.reporter.replay_to("user-1")  # the browser joins
        await _settle()

    _run(go())
    [event] = harness.published
    assert (event["type"], event["category"], event["text"]) == (
        "voice_issue",
        "credits_exhausted",
        "Hi, this is Aria.",
    )
    assert harness.destinations == ["user-1"]  # only to the participant that just joined


def test_a_handled_failure_is_not_replayed() -> None:
    harness = Harness()

    async def go() -> None:
        failure_id = harness.reporter.report(_status(402), source="voice", text="Hello.")
        await _settle()
        await harness.reporter.retry(failure_id)
        harness.published.clear()
        harness.reporter.replay_to("user-2")
        await _settle()

    _run(go())
    assert harness.published == []


def test_browser_calls_survive_provider_outages_but_phone_calls_do_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUREVIA_BACKEND_URL", "http://backend.invalid")
    from aurevia_voice.main import BROWSER_MAX_UNRECOVERABLE_ERRORS, connect_options

    assert connect_options(is_phone=False).max_unrecoverable_errors == (
        BROWSER_MAX_UNRECOVERABLE_ERRORS
    )
    # A prospect on a phone line is not left in silence: the SDK default ends the call.
    assert connect_options(is_phone=True).max_unrecoverable_errors == 3
