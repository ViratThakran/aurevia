"""The Claude adapter against the real SDK, with the HTTP layer replaced by a canned stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest
from anthropic import DefaultAsyncHttpxClient

from aurevia.providers.anthropic_model import FALLBACK_BETA, AnthropicModelProvider
from aurevia.providers.model import ModelMessage, ModelProviderError, ModelRequest

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


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, "invalid_request"), (401, "auth_failed"), (429, "rate_limited"), (529, "unavailable")],
)
def test_errors_are_normalized_without_vendor_text(status: int, kind: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status,
            json={"type": "error", "error": {"type": "x", "message": "vendor details"}},
        )

    provider = AnthropicModelProvider(
        api_key="sk-ant-test-not-real",
        effort="low",
        server_fallback=False,
        max_retries=0,
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(ModelProviderError) as exc:
        asyncio.run(provider.generate(REQUEST))
    assert exc.value.kind == kind and str(exc.value) == f"anthropic: {kind}"


def test_tool_use_round_trip() -> None:
    from aurevia.providers.model import ToolResult, ToolSpec

    seen: list[httpx2.Request] = []
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_t",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 20, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "add_note",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"text": "hi there"}'},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 12},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    stream = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=stream)

    provider = AnthropicModelProvider(
        api_key="sk-ant-test-not-real",
        effort="low",
        server_fallback=False,
        max_retries=0,
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    spec = ToolSpec(
        name="add_note",
        description="Save a note.",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    request = ModelRequest(
        model="claude-opus-5-5",
        system="s",
        messages=REQUEST.messages,
        max_tokens=256,
        tools=(spec,),
    )
    final = asyncio.run(provider.generate(request))
    assert [(c.id, c.name, dict(c.arguments)) for c in final.tool_calls] == [
        ("tu_1", "add_note", {"text": "hi there"})
    ]
    body = json.loads(seen[0].content)
    assert body["tools"][0]["name"] == "add_note"
    assert body["tools"][0]["eager_input_streaming"] is True

    follow_up = ModelRequest(
        model="claude-opus-5-5",
        system="s",
        messages=(
            *REQUEST.messages,
            ModelMessage(
                role="assistant",
                tool_calls=final.tool_calls,
                provider_state=final.provider_state,
            ),
            ModelMessage(
                role="user",
                tool_results=(
                    ToolResult(
                        call_id="tu_1", name="add_note", content={"ok": False}, is_error=True
                    ),
                ),
            ),
        ),
        max_tokens=256,
        tools=(spec,),
    )
    asyncio.run(provider.generate(follow_up))
    messages = json.loads(seen[1].content)["messages"]
    assert messages[-2]["content"][0]["type"] == "tool_use"
    assert messages[-1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": '{"ok": false}',
        "is_error": True,
    }
