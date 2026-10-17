"""Deterministic in-memory providers for tests and local development. No network access."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aurevia.providers.dnd import DndLookup, DndStatus
from aurevia.providers.model import (
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
    ProviderErrorKind,
    ToolCall,
)
from aurevia.providers.speech import AudioChunk, STTConfig, TranscriptEvent, TTSConfig
from aurevia.providers.telephony import AnsweredCall, DialError, OutboundCallRequest
from aurevia.providers.transcription import (
    TranscribedSegment,
    Transcription,
    TranscriptionError,
)
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
    # Failure kinds the next bookkeeping calls raise, in order (e.g. "rate_limited").
    bookkeeping_errors: list[ProviderErrorKind] = field(default_factory=list)
    # Seconds each bookkeeping call takes (to test turns that overlap a slow pass).
    bookkeeping_delay: float = 0.0
    # Input tokens each request reports as read from / written to a prompt cache.
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0

    def _next(self, request: ModelRequest) -> ModelResponse:
        if "# Bookkeeping pass" in request.system:
            self.bookkeeping_requests.append(request)
            if self.bookkeeping_errors:
                raise ModelProviderError(self.name, self.bookkeeping_errors.pop(0))
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
                input_tokens=sum(len(m.content.split()) for m in request.messages)
                + self.cached_input_tokens
                + self.cache_write_input_tokens,
                output_tokens=len(text.split()),
                cached_input_tokens=self.cached_input_tokens,
                cache_write_input_tokens=self.cache_write_input_tokens,
            ),
            stop_reason="end_turn",
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return self._next(request)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self.bookkeeping_delay and "# Bookkeeping pass" in request.system:
            await asyncio.sleep(self.bookkeeping_delay)
        response = self._next(request)
        yield ModelStreamEvent(
            usage=ModelUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=0,
                cached_input_tokens=response.usage.cached_input_tokens,
                cache_write_input_tokens=response.usage.cache_write_input_tokens,
            )
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
class FakeBatchTranscriber:
    """Returns scripted segments for any recording (WP-12.1). Records which files it read."""

    segments: list[TranscribedSegment]
    fail: bool = False
    name: str = "fake-batch-stt"
    seen: list[Path] = field(default_factory=list)

    async def transcribe(self, audio: Path, *, language: str) -> Transcription:
        self.seen.append(audio)
        await asyncio.to_thread(audio.read_bytes)  # the recording must exist
        if self.fail:
            raise TranscriptionError("scripted failure")
        return Transcription(language=language, segments=tuple(self.segments))


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


CANNED_REPLIES: tuple[str, ...] = (
    "Got it, thank you. How many people are on your team right now?",
    "That makes sense. What matters most to you in a plan like this?",
    "Understood. Would a short call with our specialist next week help?",
    "Thanks for telling me. Is there anything you would like to ask me?",
)


@dataclass
class CannedModelProvider:
    """Benchmarks only (``AUREVIA_AI_PROVIDER=canned``): short fixed replies, no network.

    Waits ``first_token_ms`` before the first word, like a real model's first token, so the
    speech path (speech-to-text, turn handling, text-to-speech) can be measured without
    spending model quota. Never says it is human; never calls tools.
    """

    first_token_ms: int = 1200
    name: str = "canned"
    _turn: itertools.count[int] = field(default_factory=itertools.count)

    def _reply(self, request: ModelRequest) -> str:
        if "# Bookkeeping pass" in request.system:
            return ""
        return CANNED_REPLIES[next(self._turn) % len(CANNED_REPLIES)]

    def _response(self, request: ModelRequest, text: str) -> ModelResponse:
        return ModelResponse(
            text=text,
            model="canned-v1",
            usage=ModelUsage(input_tokens=0, output_tokens=len(text.split())),
            stop_reason="end_turn",
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return self._response(request, self._reply(request))

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        text = self._reply(request)
        yield ModelStreamEvent(usage=ModelUsage(input_tokens=0, output_tokens=0))
        if text:
            await asyncio.sleep(self.first_token_ms / 1000)
            for index, word in enumerate(text.split(" ")):
                yield ModelStreamEvent(delta=word if index == 0 else f" {word}")
        yield ModelStreamEvent(final=self._response(request, text))

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
