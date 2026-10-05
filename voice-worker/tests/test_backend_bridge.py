from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from livekit.agents import APIStatusError, llm

from aurevia_voice.backend_client import BackendClient, BackendError, Utterance
from aurevia_voice.llm_bridge import BackendLLM, history_from

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> BackendClient:
    return BackendClient(
        base_url="http://backend.test",
        call_id="call-1",
        call_token="call-token-test",
        http=httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ),
    )


def _ndjson(*events: dict[str, object]) -> bytes:
    return b"".join(json.dumps(e).encode() + b"\n" for e in events)


def test_start_sends_the_call_token_and_parses_the_opening() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"agent_name": "Aria", "greeting": "Hi!", "language": "en-IN", "voice": None},
        )

    opening = asyncio.run(_client(handler).start())
    assert (opening.agent_name, opening.greeting, opening.voice) == ("Aria", "Hi!", None)
    assert seen[0].url.path == "/internal/v1/calls/call-1/start"
    assert seen[0].headers["authorization"] == "Bearer call-token-test"


def test_stream_turn_yields_deltas_until_done() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"history": [{"role": "prospect", "text": "hello"}]}
        return httpx.Response(
            200,
            content=_ndjson(
                {"type": "delta", "text": "Hi "},
                {"type": "delta", "text": "there."},
                {"type": "done", "sales_state": "discovery"},
            ),
        )

    async def run() -> list[str]:
        client = _client(handler)
        return [t async for t in client.stream_turn([Utterance("prospect", "hello")])]

    assert asyncio.run(run()) == ["Hi ", "there."]


def test_stream_turn_raises_on_error_line() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_ndjson({"type": "error", "code": "timeout"}))

    async def run() -> None:
        async for _ in _client(handler).stream_turn([Utterance("prospect", "hi")]):
            pass

    with pytest.raises(BackendError) as exc:
        asyncio.run(run())
    assert exc.value.code == "timeout" and not exc.value.retryable


def test_http_errors_carry_the_backend_error_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "call_not_in_progress", "message": "x"}})

    async def run() -> None:
        async for _ in _client(handler).stream_turn([Utterance("prospect", "hi")]):
            pass

    with pytest.raises(BackendError) as exc:
        asyncio.run(run())
    assert (exc.value.code, exc.value.status, exc.value.retryable) == (
        "call_not_in_progress",
        409,
        False,
    )


def test_history_maps_roles_and_drops_instructions() -> None:
    ctx = llm.ChatContext.empty()
    ctx.add_message(role="system", content="placeholder instructions")
    ctx.add_message(role="assistant", content="Hi, this is Aria.")
    ctx.add_message(role="user", content="  Who is calling?  ")
    ctx.add_message(role="user", content="")
    assert history_from(ctx) == [
        Utterance("agent", "Hi, this is Aria."),
        Utterance("prospect", "Who is calling?"),
    ]


def test_backend_llm_streams_through_livekit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson(
                {"type": "delta", "text": "Sure, "},
                {"type": "delta", "text": "go ahead."},
                {"type": "done", "sales_state": "discovery"},
            ),
        )

    async def run() -> str:
        bridge = BackendLLM(_client(handler))
        ctx = llm.ChatContext.empty()
        ctx.add_message(role="user", content="Can I ask something?")
        text = ""
        async with bridge.chat(chat_ctx=ctx) as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    text += chunk.delta.content
        return text

    assert asyncio.run(run()) == "Sure, go ahead."


def test_backend_llm_surfaces_non_retryable_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": "call_not_in_progress"}})

    async def run() -> None:
        bridge = BackendLLM(_client(handler))
        ctx = llm.ChatContext.empty()
        ctx.add_message(role="user", content="hello")
        async with bridge.chat(chat_ctx=ctx) as stream:
            async for _ in stream:
                pass

    with pytest.raises(APIStatusError):
        asyncio.run(run())
