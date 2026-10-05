from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from aurevia.gateway import GatewayError, GenerationRecord, ModelGateway
from aurevia.providers.fakes import FakeModelProvider
from aurevia.providers.model import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
)

MESSAGES = (ModelMessage(role="user", content="hello"),)


def _gateway(provider: object, *, first: float = 1.0, total: float = 2.0) -> ModelGateway:
    return ModelGateway(
        provider,  # type: ignore[arg-type]
        model="test-model",
        max_tokens=100,
        first_token_timeout_seconds=first,
        total_timeout_seconds=total,
    )


async def _collect(gateway: ModelGateway, record: GenerationRecord) -> str:
    return "".join(
        [d async for d in gateway.stream_text(system="s", messages=MESSAGES, record=record)]
    )


def test_streams_text_and_fills_the_record() -> None:
    gateway = _gateway(FakeModelProvider(replies=["Hello from the agent"]))
    record = gateway.new_record({"call_id": "c1"})
    text = asyncio.run(_collect(gateway, record))
    assert text.strip() == "Hello from the agent"
    assert record.completed and not record.interrupted and record.error is None
    assert record.served_model == "test-model"
    assert record.output_tokens == 4 and record.input_tokens == 1
    assert record.first_token_ms is not None


@dataclass
class SlowProvider:
    """Waits ``delay`` seconds before the first token, then streams ``words``."""

    delay: float
    words: list[str] = field(default_factory=lambda: ["one", "two"])
    gap: float = 0.0
    name: str = "slow"
    closed: bool = False

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        try:
            yield ModelStreamEvent(usage=ModelUsage(input_tokens=5, output_tokens=0))
            await asyncio.sleep(self.delay)
            for word in self.words:
                yield ModelStreamEvent(delta=word)
                await asyncio.sleep(self.gap)
            yield ModelStreamEvent(
                final=ModelResponse(
                    text=" ".join(self.words),
                    model=request.model,
                    usage=ModelUsage(input_tokens=5, output_tokens=len(self.words)),
                    stop_reason="end_turn",
                )
            )
        finally:
            self.closed = True

    async def health(self) -> bool:
        return True


def test_first_token_timeout() -> None:
    gateway = _gateway(SlowProvider(delay=0.5), first=0.05)
    record = gateway.new_record()
    with pytest.raises(GatewayError) as exc:
        asyncio.run(_collect(gateway, record))
    assert exc.value.code == "timeout"
    assert record.error == "timeout" and not record.interrupted
    assert record.input_tokens == 5  # usage known before the timeout is kept


def test_total_timeout_after_first_token() -> None:
    gateway = _gateway(SlowProvider(delay=0, words=["a"] * 10, gap=0.05), first=1, total=0.12)
    with pytest.raises(GatewayError):
        asyncio.run(_collect(gateway, gateway.new_record()))


@dataclass
class BrokenProvider:
    name: str = "broken"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        raise ConnectionError("upstream reset")
        yield  # pragma: no cover - makes this an async generator

    async def health(self) -> bool:
        return False


def test_provider_failure_becomes_gateway_error() -> None:
    gateway = _gateway(BrokenProvider())
    record = gateway.new_record()
    with pytest.raises(GatewayError) as exc:
        asyncio.run(_collect(gateway, record))
    assert exc.value.code == "provider_error"
    assert record.error == "provider_error"


def test_consumer_stopping_early_closes_the_provider_stream() -> None:
    """Barge-in: the reader stops after the first words; generation must stop too."""
    provider = SlowProvider(delay=0, words=["a", "b", "c", "d"], gap=0.01)
    gateway = _gateway(provider)
    record = gateway.new_record()

    async def run() -> list[str]:
        stream = gateway.stream_text(system="s", messages=MESSAGES, record=record)
        got = [await anext(stream)]
        await stream.aclose()  # type: ignore[attr-defined]
        return got

    assert asyncio.run(run()) == ["a"]
    assert provider.closed
    assert record.interrupted and not record.completed
    assert record.input_tokens == 5
