"""The Claude adapter against the real SDK, with the HTTP layer replaced by a canned stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
from anthropic import DefaultAsyncHttpxClient

from aurevia.providers.anthropic_model import FALLBACK_BETA, AnthropicModelProvider
from aurevia.providers.model import ModelMessage, ModelRequest

REQUEST = ModelRequest(
    model="claude-opus-5-5",
    system="You are a test agent.",
    messages=(ModelMessage(role="user", content="Hello?"),),
    max_tokens=512,
)


def _sse(served_model: str) -> bytes:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": served_model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 42, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hi "},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "there."},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _provider(
    seen: list[httpx2.Request], *, fallback: bool, served_model: str
) -> AnthropicModelProvider:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream", "request-id": "req_test_123"},
            content=_sse(served_model),
        )

    return AnthropicModelProvider(
        api_key="sk-ant-test-not-real",
        effort="low",
        server_fallback=fallback,
        max_retries=0,
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def test_streams_text_usage_and_final_message() -> None:
    seen: list[httpx2.Request] = []
    provider = _provider(seen, fallback=True, served_model="claude-opus-5-5")

    async def run() -> list[Any]:
        return [event async for event in provider.stream(REQUEST)]

    events = asyncio.run(run())
    assert events[0].usage is not None and events[0].usage.input_tokens == 42
    assert "".join(e.delta for e in events) == "Hi there."
    final = events[-1].final
    assert final is not None
    assert (final.text, final.model, final.stop_reason) == (
        "Hi there.",
        "claude-opus-5-5",
        "end_turn",
    )
    assert (final.usage.input_tokens, final.usage.output_tokens) == (42, 7)
    assert final.provider_request_id == "req_test_123"


def test_request_carries_explicit_fallback_effort_and_no_sampling_params() -> None:
    seen: list[httpx2.Request] = []
    provider = _provider(seen, fallback=True, served_model="claude-opus-5-5")
    asyncio.run(provider.generate(REQUEST))

    body = json.loads(seen[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "low"}
    assert body["system"] == "You are a test agent."
    assert body["messages"] == [{"role": "user", "content": "Hello?"}]
    assert "temperature" not in body and "thinking" not in body
    assert FALLBACK_BETA in seen[0].headers["anthropic-beta"]


def test_fallback_policy_none_sends_no_fallback() -> None:
    seen: list[httpx2.Request] = []
    provider = _provider(seen, fallback=False, served_model="claude-opus-5-5")
    asyncio.run(provider.generate(REQUEST))
    body = json.loads(seen[0].content)
    assert "fallbacks" not in body
    assert "server-side-fallback" not in seen[0].headers.get("anthropic-beta", "")


def test_reports_the_model_that_actually_answered() -> None:
    seen: list[httpx2.Request] = []
    provider = _provider(seen, fallback=True, served_model="claude-opus-4-8")
    final = asyncio.run(provider.generate(REQUEST))
    assert final.model == "claude-opus-4-8"
