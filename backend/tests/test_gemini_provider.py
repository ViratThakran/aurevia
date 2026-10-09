"""The Gemini adapter against the real google-genai SDK, with HTTP replaced by canned responses."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from aurevia.providers.gemini_model import GeminiModelProvider, thinking_config
from aurevia.providers.model import (
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    ModelStreamEvent,
)

FAKE_KEY = "gemini-test-key-not-real-000"  # test-only
REQUEST = ModelRequest(
    model="gemini-3.5-flash-lite",
    system="You are a test agent.",
    messages=(
        ModelMessage(role="user", content="(The call has connected.)"),
        ModelMessage(role="assistant", content="Hi, this is Aria."),
        ModelMessage(role="user", content="Who is this?"),
    ),
    max_tokens=512,
)


def _sse(*chunks: dict[str, Any]) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\r\n\r\n".encode() for c in chunks)


def _chunk(parts: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    candidate: dict[str, Any] = {"content": {"role": "model", "parts": parts}}
    if "finishReason" in extra:
        candidate["finishReason"] = extra.pop("finishReason")
    return {
        "candidates": [candidate],
        "modelVersion": "gemini-3.5-flash-lite",
        "responseId": "resp-test-1",
        **extra,
    }


STREAM = _sse(
    _chunk(
        [{"text": "planning the reply", "thought": True}], usageMetadata={"promptTokenCount": 40}
    ),
    _chunk([{"text": "Hi, I'm "}], usageMetadata={"promptTokenCount": 40}),
    _chunk(
        [{"text": "Aria."}],
        finishReason="STOP",
        usageMetadata={
            "promptTokenCount": 40,
            "candidatesTokenCount": 5,
            "thoughtsTokenCount": 3,
        },
    ),
)


def _provider(handler: Any) -> GeminiModelProvider:
    return GeminiModelProvider(
        api_key=FAKE_KEY,
        effort="low",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _run(provider: GeminiModelProvider) -> list[ModelStreamEvent]:
    async def collect() -> list[ModelStreamEvent]:
        return [event async for event in provider.stream(REQUEST)]

    return asyncio.run(collect())


def test_streams_text_skips_thoughts_and_reports_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=STREAM)

    events = _run(_provider(handler))
    assert events[0].usage is not None and events[0].usage.input_tokens == 40
    assert "".join(e.delta for e in events) == "Hi, I'm Aria."  # the thought is never spoken
    final = events[-1].final
    assert final is not None
    assert (final.text, final.model, final.stop_reason) == (
        "Hi, I'm Aria.",
        "gemini-3.5-flash-lite",
        "stop",
    )
    assert (final.usage.input_tokens, final.usage.output_tokens) == (40, 8)  # thinking billed
    assert final.provider_request_id == "resp-test-1"


def test_request_shape_and_key_handling() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=STREAM)

    _run(_provider(handler))
    request = seen[0]
    assert "gemini-3.5-flash-lite:streamGenerateContent" in request.url.path
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    assert FAKE_KEY not in str(request.url)  # never in the URL, so never in access logs
    body = json.loads(request.content)
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["systemInstruction"]["parts"][0]["text"] == "You are a test agent."
    assert body["generationConfig"]["maxOutputTokens"] == 512
    # The SDK sends proto field names, which the API accepts in either case style.
    thinking = body["generationConfig"]["thinkingConfig"]
    assert thinking.get("thinkingLevel", thinking.get("thinking_level")) == "MINIMAL"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, "invalid_request"),
        (401, "auth_failed"),
        (403, "auth_failed"),
        (404, "invalid_request"),
        (429, "rate_limited"),
        (500, "unavailable"),
        (503, "unavailable"),
        (504, "timeout"),
    ],
)
def test_errors_are_normalized_without_vendor_text(status: int, kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        error = {"code": status, "message": f"details mentioning {FAKE_KEY}", "status": "ERR"}
        return httpx.Response(status, json={"error": error})

    with pytest.raises(ModelProviderError) as exc:
        _run(_provider(handler))
    assert exc.value.kind == kind
    assert str(exc.value) == f"gemini: {kind}"
    assert exc.value.__cause__ is None  # the vendor exception (and its text) is not chained
    assert exc.value.retryable == (kind in ("rate_limited", "unavailable", "timeout"))


def test_network_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ModelProviderError) as exc:
        _run(_provider(handler))
    assert exc.value.kind == "unavailable"


def test_thinking_config_per_model_family() -> None:
    assert thinking_config("gemini-3.5-flash-lite", "low").thinking_level == "MINIMAL"
    assert thinking_config("gemini-3.1-pro-preview", "low").thinking_level == "LOW"
    assert thinking_config("gemini-3.5-flash", "medium").thinking_level == "MEDIUM"
    assert thinking_config("gemini-2.5-flash", "low").thinking_budget == 0
    assert thinking_config("gemini-2.5-pro", "low").thinking_budget == 128
    assert thinking_config("gemini-2.5-flash", "high").thinking_budget == -1
