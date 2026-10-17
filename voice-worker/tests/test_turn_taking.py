"""WP-11.6 on the worker: the cut-off flag reaches the backend; a fixed goodbye ends the call."""

from __future__ import annotations

import asyncio
import json

import httpx
from livekit.agents import llm

from aurevia_voice.backend_client import BackendClient, Utterance
from aurevia_voice.llm_bridge import history_from


def test_history_marks_agent_lines_the_prospect_cut_off() -> None:
    chat = llm.ChatContext()
    chat.add_message(role="assistant", content="We cover forty people", interrupted=True)
    chat.add_message(role="user", content="Oh, sorry.")
    assert history_from(chat) == [
        Utterance("agent", "We cover forty people", interrupted=True),
        Utterance("prospect", "Oh, sorry."),
    ]


def test_payload_sends_the_flag_only_when_set_and_end_call_is_reported() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        lines = [
            {"type": "delta", "text": "Thanks for your time. Goodbye."},
            {"type": "end_call", "reason": "goodbye"},
            {"type": "done", "sales_state": "opening"},
        ]
        return httpx.Response(200, content=b"".join(json.dumps(x).encode() + b"\n" for x in lines))

    ended: list[str] = []
    client = BackendClient(
        base_url="http://backend.test",
        call_id="call-1",
        call_token="call-token-test",
        http=httpx.AsyncClient(
            base_url="http://backend.test", transport=httpx.MockTransport(handler)
        ),
        on_end_call=ended.append,
    )
    history = [Utterance("agent", "Hi", interrupted=True), Utterance("prospect", "Okay, bye.")]

    async def run() -> list[str]:
        return [t async for t in client.stream_turn(history)]

    assert asyncio.run(run()) == ["Thanks for your time. Goodbye."]
    assert ended == ["goodbye"]
    assert bodies[0] == {
        "history": [
            {"role": "agent", "text": "Hi", "interrupted": True},
            {"role": "prospect", "text": "Okay, bye."},
        ]
    }
