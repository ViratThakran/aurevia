"""Deterministic in-memory providers for tests and local development. No network access."""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

from aurevia.providers.dnd import DndLookup, DndStatus
from aurevia.providers.model import (
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
    ToolCall,
)
from aurevia.providers.speech import AudioChunk, STTConfig, TranscriptEvent, TTSConfig
from aurevia.providers.telephony import AnsweredCall, DialError, OutboundCallRequest
from aurevia.providers.voice_transport import InvalidWebhookError, TransportEvent


@dataclass(frozen=True)
class FakeTurn:
    """A scripted reply that asks for tools (and may say something first)."""

    tool_calls: tuple[ToolCall, ...]
    text: str = ""


@dataclass
class FakeModelProvider:
    """Replies with scripted texts (or FakeTurns) in order. Records every request."""

    replies: list[str | FakeTurn]
    name: str = "fake-model"
    requests: list[ModelRequest] = field(default_factory=list)
    # The bookkeeping pass (a second call per turn, after the reply) has its own script and
    # request log so it never consumes replies meant for the spoken turn. Unscripted: no tools.
    bookkeeping_replies: list[str | FakeTurn] = field(default_factory=list)
    bookkeeping_requests: list[ModelRequest] = field(default_factory=list)

    def _next(self, request: ModelRequest) -> ModelResponse:
        if "# Bookkeeping pass" in request.system:
            self.bookkeeping_requests.append(request)
            reply: str | FakeTurn = (
                self.bookkeeping_replies.pop(0) if self.bookkeeping_replies else ""
            )
        else:
            self.requests.append(request)
            if not self.replies:
                raise RuntimeError("FakeModelProvider has no scripted reply left")
            reply = self.replies.pop(0)
        text = reply.text if isinstance(reply, FakeTurn) else reply
        calls = reply.tool_calls if isinstance(reply, FakeTurn) else ()
        return ModelResponse(
            text=text,
            tool_calls=calls,
            model=request.model,
            usage=ModelUsage(
                input_tokens=sum(len(m.content.split()) for m in request.messages),
                output_tokens=len(text.split()),
            ),
            stop_reason="end_turn",
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return self._next(request)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        response = self._next(request)
        yield ModelStreamEvent(
            usage=ModelUsage(input_tokens=response.usage.input_tokens, output_tokens=0)
        )
        if response.text:
            for word in response.text.split(" "):
                yield ModelStreamEvent(delta=word + " ")
        if response.tool_calls:
            yield ModelStreamEvent(started=True)
        yield ModelStreamEvent(final=response)

    async def health(self) -> bool:
        return True


@dataclass
class FakeSTTProvider:
    """Emits one scripted final transcript per received audio chunk, with a partial before it."""

    transcripts: list[str]
    name: str = "fake-stt"

    async def transcribe(
        self, audio: AsyncIterator[AudioChunk], config: STTConfig
    ) -> AsyncIterator[TranscriptEvent]:
        scripted = iter(self.transcripts)
        async for _chunk in audio:
            text = next(scripted, None)
            if text is None:
                return
            yield TranscriptEvent(text=text.split(" ")[0], is_final=False)
            yield TranscriptEvent(text=text, is_final=True, confidence=1.0)


@dataclass
class FakeTTSProvider:
    """One audio chunk per text fragment; the bytes are the UTF-8 text, for easy asserts."""

    name: str = "fake-tts"

    async def synthesize(
        self, text: AsyncIterator[str], config: TTSConfig
    ) -> AsyncIterator[AudioChunk]:
        async for fragment in text:
            yield AudioChunk(
                data=fragment.encode(), sample_rate=config.sample_rate, format=config.format
            )


@dataclass
class FakeTelephonyProvider:
    """Answers every call unless a ``DialError`` is queued in ``failures``."""

    name: str = "fake-telephony"
    placed: list[OutboundCallRequest] = field(default_factory=list)
    failures: list[DialError] = field(default_factory=list)
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    async def place_call(self, request: OutboundCallRequest) -> AnsweredCall:
        self.placed.append(request)
        if self.failures:
            raise self.failures.pop(0)
        return AnsweredCall(provider_call_id=f"fake-call-{next(self._ids)}")


@dataclass
class FakeDndRegistry:
    """Numbers in ``registered`` are on the DND list; ``unknown`` ones cannot be checked."""

    name: str = "fake-dnd"
    registered: set[str] = field(default_factory=set)
    unknown: set[str] = field(default_factory=set)
    lookups: list[str] = field(default_factory=list)

    async def lookup(self, e164: str, *, now: datetime) -> DndLookup:
        self.lookups.append(e164)
        if e164 in self.unknown:
            status = DndStatus.UNKNOWN
        elif e164 in self.registered:
            status = DndStatus.REGISTERED
        else:
            status = DndStatus.NOT_REGISTERED
        return DndLookup(status=status, source=self.name, checked_at=now)


@dataclass
class FakeVoiceTransport:
    """Records rooms and dispatches; tokens are readable strings, not JWTs."""

    public_url: str = "ws://voice.test"
    rooms: list[tuple[str, str, str]] = field(default_factory=list)

    def participant_token(self, *, room: str, identity: str, name: str, ttl_seconds: int) -> str:
        return f"fake-token:{room}:{identity}"

    async def open_room_with_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        self.rooms.append((room, agent_name, metadata))

    dispatches: list[tuple[str, str, str]] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)

    async def dispatch_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        self.dispatches.append((room, agent_name, metadata))

    async def close_room(self, room: str) -> None:
        self.closed.append(room)

    def parse_webhook(self, body: str, authorization: str) -> TransportEvent:
        """Accepts JSON bodies authorized with the literal ``signed``."""
        if authorization != "signed":
            raise InvalidWebhookError("invalid webhook")
        data = json.loads(body)
        return TransportEvent(
            kind=data["kind"],
            room=data["room"],
            participant_identity=data.get("identity", ""),
            is_phone=data.get("is_phone", False),
            attributes=data.get("attributes", {}),
        )
