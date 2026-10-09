from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from aurevia.gateway import GatewayError, GenerationRecord, ModelGateway
from aurevia.providers.fakes import FakeModelProvider
from aurevia.providers.model import (
    ModelMessage,
    ModelProviderError,
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


@dataclass
class RateLimitedProvider:
    name: str = "limited"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        raise ModelProviderError("limited", "rate_limited")
        yield  # pragma: no cover - makes this an async generator

    async def health(self) -> bool:
        return True


def test_normalized_provider_errors_keep_their_kind() -> None:
    gateway = _gateway(RateLimitedProvider())
    record = gateway.new_record()
    with pytest.raises(GatewayError) as exc:
        asyncio.run(_collect(gateway, record))
    assert exc.value.code == "rate_limited" and record.error == "rate_limited"


@dataclass
class PerModelProvider:
    """Behaves per model: 'fail:<kind>', 'hang', 'midstream', or a reply text."""

    behaviour: dict[str, str]
    name: str = "per-model"
    seen: list[str] = field(default_factory=list)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.seen.append(request.model)
        plan = self.behaviour[request.model]
        if plan.startswith("fail:"):
            raise ModelProviderError(self.name, plan.removeprefix("fail:"))  # type: ignore[arg-type]
        if plan == "hang":
            await asyncio.sleep(5)
        if plan == "midstream":
            yield ModelStreamEvent(delta="partial ")
            raise ModelProviderError(self.name, "unavailable")
        yield ModelStreamEvent(delta=plan)
        yield ModelStreamEvent(
            final=ModelResponse(
                text=plan,
                model=request.model,
                usage=ModelUsage(input_tokens=3, output_tokens=1),
                stop_reason="stop",
            )
        )

    async def health(self) -> bool:
        return True


def _fallback_gateway(provider: PerModelProvider, first: float = 1.0) -> ModelGateway:
    return ModelGateway(
        provider,
        model="primary",
        max_tokens=100,
        first_token_timeout_seconds=first,
        total_timeout_seconds=3.0,
        fallback_models=["backup", "last"],
    )


@pytest.mark.parametrize("failure", ["fail:unavailable", "fail:rate_limited", "hang"])
def test_falls_back_before_the_first_word(failure: str) -> None:
    provider = PerModelProvider({"primary": failure, "backup": "from backup", "last": "x"})
    gateway = _fallback_gateway(provider, first=0.2)
    record = gateway.new_record()
    assert asyncio.run(_collect(gateway, record)) == "from backup"
    assert record.attempted_models == ["primary", "backup"]
    assert (record.requested_model, record.served_model) == ("primary", "backup")
    assert record.completed and record.error is None


def test_no_fallback_for_bad_requests_or_after_speech_started() -> None:
    bad = PerModelProvider({"primary": "fail:invalid_request", "backup": "ok", "last": "ok"})
    with pytest.raises(GatewayError) as exc:
        asyncio.run(_collect(_fallback_gateway(bad), _fallback_gateway(bad).new_record()))
    assert exc.value.code == "invalid_request" and bad.seen == ["primary"]

    midway = PerModelProvider({"primary": "midstream", "backup": "ok", "last": "ok"})
    gateway = _fallback_gateway(midway)
    record = gateway.new_record()
    with pytest.raises(GatewayError):
        asyncio.run(_collect(gateway, record))
    assert midway.seen == ["primary"]  # a started reply is never switched to another model


def test_all_models_failing_raises_the_last_error() -> None:
    provider = PerModelProvider(
        {"primary": "fail:unavailable", "backup": "fail:unavailable", "last": "fail:timeout"}
    )
    gateway = _fallback_gateway(provider)
    record = gateway.new_record()
    with pytest.raises(GatewayError) as exc:
        asyncio.run(_collect(gateway, record))
    assert exc.value.code == "timeout"
    assert record.attempted_models == ["primary", "backup", "last"]
    assert record.served_model is None


def test_circuit_breaker_skips_a_failing_model_then_retries_it() -> None:
    from aurevia.gateway import CircuitBreaker

    provider = PerModelProvider({"primary": "fail:unavailable", "backup": "ok", "last": "x"})
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=60)
    gateway = ModelGateway(
        provider,
        model="primary",
        max_tokens=100,
        first_token_timeout_seconds=1,
        total_timeout_seconds=3,
        fallback_models=["backup"],
        breaker=breaker,
    )
    for _ in range(3):
        asyncio.run(_collect(gateway, gateway.new_record()))
    # Two failures open the breaker; the third turn goes straight to the backup.
    assert provider.seen == ["primary", "backup", "primary", "backup", "backup"]

    breaker._open_until["primary"] = 0.0  # cooldown over: one probe request
    asyncio.run(_collect(gateway, gateway.new_record()))
    assert provider.seen[-2:] == ["primary", "backup"]  # probe failed...
    assert breaker.is_open("primary", now=0.0 + 1e12) is False  # (reopened for a cooldown)
    assert breaker.is_open("primary", __import__("time").monotonic())  # ...reopened at once

    breaker._open_until["primary"] = 0.0
    provider.behaviour["primary"] = "recovered"
    record = gateway.new_record()
    assert asyncio.run(_collect(gateway, record)) == "recovered"
    assert record.served_model == "primary"
