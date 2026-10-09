"""HTTP client for the backend's per-call worker API (``/internal/v1/calls/{id}``).

The worker never talks to a language model directly: each turn is sent to the backend, which
builds the prompt, applies the sales rules, calls the Model Gateway and records usage.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

Role = Literal["prospect", "agent"]


class BackendError(Exception):
    def __init__(self, code: str, *, status: int = -1, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class CallOpening:
    agent_name: str
    greeting: str
    language: str
    voice: str | None


@dataclass(frozen=True)
class Utterance:
    role: Role
    text: str


class BackendClient:
    def __init__(
        self,
        *,
        base_url: str,
        call_id: str,
        call_token: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._call_path = f"/internal/v1/calls/{call_id}"
        self._http = http or httpx.AsyncClient(
            base_url=base_url,
            # The backend enforces the model deadlines; this only guards a dead connection.
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
        self._headers = {"Authorization": f"Bearer {call_token}"}

    async def start(self) -> CallOpening:
        response = await self._http.post(f"{self._call_path}/start", headers=self._headers)
        _raise_for(response)
        body = response.json()
        return CallOpening(
            agent_name=body["agent_name"],
            greeting=body["greeting"],
            language=body["language"],
            voice=body.get("voice"),
        )

    async def stream_turn(self, history: Sequence[Utterance]) -> AsyncIterator[str]:
        """Yield the agent's reply as it is generated.

        Stopping iteration early (the prospect interrupted) closes the HTTP stream, which
        tells the backend to stop generating.
        """
        payload = {"history": [{"role": u.role, "text": u.text} for u in history]}
        async with self._http.stream(
            "POST", f"{self._call_path}/turns", json=payload, headers=self._headers
        ) as response:
            if response.status_code != 200:
                await response.aread()
                _raise_for(response)
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event["type"] == "delta":
                    yield event["text"]
                elif event["type"] == "error":
                    raise BackendError(event["code"], status=502, retryable=False)
                elif event["type"] == "done":
                    return
        raise BackendError("stream_ended_early", status=502, retryable=False)

    async def report_usage(
        self,
        *,
        kind: Literal["stt", "tts"],
        provider: str,
        model: str,
        audio_seconds: float = 0.0,
        characters: int = 0,
    ) -> None:
        response = await self._http.post(
            f"{self._call_path}/usage",
            headers=self._headers,
            json={
                "kind": kind,
                "provider": provider[:50] or "unknown",
                "model": model[:100] or "unknown",
                "audio_seconds": audio_seconds,
                "characters": characters,
            },
        )
        _raise_for(response)

    async def report_turn_metrics(self, turns: Sequence[Mapping[str, Any]]) -> None:
        for start in range(0, len(turns), 1000):  # the backend accepts up to 1000 per request
            response = await self._http.post(
                f"{self._call_path}/turn-metrics",
                headers=self._headers,
                json={"turns": list(turns[start : start + 1000])},
            )
            _raise_for(response)

    async def save_transcript(self, lines: Sequence[Mapping[str, Any]]) -> None:
        response = await self._http.post(
            f"{self._call_path}/transcript",
            headers=self._headers,
            json={"lines": list(lines[:2000])},
        )
        _raise_for(response)

    async def end(self, reason: str, *, failed: bool = False) -> None:
        response = await self._http.post(
            f"{self._call_path}/end",
            headers=self._headers,
            json={"reason": reason, "failed": failed},
        )
        _raise_for(response)

    async def aclose(self) -> None:
        await self._http.aclose()


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        code = str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        code = f"http_{response.status_code}"
    retryable = response.status_code >= 500 or response.status_code == 429
    raise BackendError(code, status=response.status_code, retryable=retryable)
