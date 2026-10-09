from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest

from aurevia.providers import (
    AudioChunk,
    DialError,
    DialFailure,
    ModelMessage,
    ModelProvider,
    ModelRequest,
    OutboundCallRequest,
    STTConfig,
    STTProvider,
    TelephonyProvider,
    TTSConfig,
    TTSProvider,
)
from aurevia.providers.fakes import (
    FakeModelProvider,
    FakeSTTProvider,
    FakeTelephonyProvider,
    FakeTTSProvider,
)
from aurevia.providers.telephony import failure_for_sip_status

REQUEST = ModelRequest(
    model="test-model",
    system="You are a test.",
    messages=(ModelMessage(role="user", content="hello there"),),
    max_tokens=50,
)


async def _aiter[T](*items: T) -> AsyncIterator[T]:
    for item in items:
        yield item


def test_fakes_satisfy_their_protocols() -> None:
    assert isinstance(FakeModelProvider(replies=[]), ModelProvider)
    assert isinstance(FakeSTTProvider(transcripts=[]), STTProvider)
    assert isinstance(FakeTTSProvider(), TTSProvider)
    assert isinstance(FakeTelephonyProvider(), TelephonyProvider)


def test_fake_model_generate_and_stream() -> None:
    provider = FakeModelProvider(replies=["first reply", "second reply here"])

    async def run() -> tuple[str, list[str], int]:
        generated = await provider.generate(REQUEST)
        events = [event async for event in provider.stream(REQUEST)]
        deltas = [e.delta for e in events if e.final is None]
        final = events[-1].final
        assert final is not None
        return generated.text, deltas, final.usage.output_tokens

    text, deltas, output_tokens = asyncio.run(run())
    assert text == "first reply"
    assert "".join(deltas).strip() == "second reply here"
    assert output_tokens == 3
    assert provider.requests == [REQUEST, REQUEST]


def test_fake_stt_emits_partial_then_final() -> None:
    provider = FakeSTTProvider(transcripts=["hello world"])
    config = STTConfig(language="en-IN", sample_rate=16000)

    async def run() -> list[tuple[str, bool]]:
        audio = _aiter(AudioChunk(data=b"\x00\x00", sample_rate=16000))
        return [(e.text, e.is_final) async for e in provider.transcribe(audio, config)]

    assert asyncio.run(run()) == [("hello", False), ("hello world", True)]


def test_fake_tts_streams_one_chunk_per_fragment() -> None:
    config = TTSConfig(voice="test", language="en-IN", sample_rate=24000)

    async def run() -> list[bytes]:
        return [c.data async for c in FakeTTSProvider().synthesize(_aiter("Hi ", "there"), config)]

    assert asyncio.run(run()) == [b"Hi ", b"there"]


def test_fake_telephony_records_calls() -> None:
    provider = FakeTelephonyProvider(failures=[DialError(DialFailure.BUSY, sip_status=486)])
    request = OutboundCallRequest(
        tenant_id=uuid.uuid4(),
        call_id=uuid.uuid4(),
        room="room-1",
        to_number="+919876543210",
        from_number="+911400000000",
        compliance_decision_id=uuid.uuid4(),
        ring_timeout_seconds=30,
    )
    with pytest.raises(DialError) as busy:
        asyncio.run(provider.place_call(request))
    assert busy.value.failure == DialFailure.BUSY
    answered = asyncio.run(provider.place_call(request))
    assert answered.provider_call_id.startswith("fake-call-")
    assert provider.placed == [request, request]


def test_sip_status_mapping_is_conservative() -> None:
    assert failure_for_sip_status(486) == DialFailure.BUSY
    assert failure_for_sip_status(480) == DialFailure.NO_ANSWER
    assert failure_for_sip_status(503) == DialFailure.FAILED
    assert failure_for_sip_status(None) == DialFailure.FAILED
