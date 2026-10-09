"""AI Model Gateway: the only path from Aurevia code to a language model.

It owns model selection, deadlines, and the record of what happened on every request
(requested vs. served model, tokens, time to first token, whether the caller cut it off).
Fallback is explicit configuration passed to the provider, never a silent switch here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

from aurevia.providers.model import (
    ModelMessage,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ToolSpec,
)


@dataclass(frozen=True)
class GatewayEvent:
    """A text delta, or (once, last) the final response, including any tool calls."""

    delta: str = ""
    final: ModelResponse | None = None


class GatewayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        # "timeout" | "provider_error" | a normalized provider kind ("auth_failed",
        # "rate_limited", "invalid_request", "unavailable").
        self.code = code


@dataclass
class GenerationRecord:
    """Filled in while a reply streams; read afterwards to record usage."""

    requested_model: str
    provider: str
    served_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    first_token_ms: int | None = None
    stop_reason: str | None = None
    provider_request_id: str | None = None
    completed: bool = False
    # The model produced output (text or a tool call): no more fallback for this reply.
    output_started: bool = False
    error: str | None = None
    # Every model tried, in order; more than one means the fallback policy was used.
    attempted_models: list[str] = field(default_factory=list)
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def interrupted(self) -> bool:
        """The consumer stopped reading before the reply finished (e.g. barge-in)."""
        return not self.completed and self.error is None


# Failures that justify trying the next configured model: the model never started answering.
_FALLBACK_CODES = frozenset({"timeout", "unavailable", "rate_limited"})


class CircuitBreaker:
    """Skips a model for ``cooldown_seconds`` after ``threshold`` consecutive failures, so an
    outage costs one first-token timeout per cooldown instead of one per turn. The last
    configured model is never skipped: with everything open there is still something to try.
    """

    def __init__(self, *, threshold: int = 2, cooldown_seconds: float = 60.0) -> None:
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, model: str, now: float) -> bool:
        return self._open_until.get(model, 0.0) > now

    def failure(self, model: str, now: float) -> None:
        self._failures[model] = self._failures.get(model, 0) + 1
        # After a cooldown the next request is a probe: one failure reopens the breaker.
        if self._failures[model] >= self._threshold or model in self._open_until:
            self._open_until[model] = now + self._cooldown

    def success(self, model: str) -> None:
        self._failures.pop(model, None)
        self._open_until.pop(model, None)


class ModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        model: str,
        max_tokens: int,
        first_token_timeout_seconds: float,
        total_timeout_seconds: float,
        fallback_models: Sequence[str] = (),
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._provider = provider
        self._breaker = breaker or CircuitBreaker()
        self._model = model
        self._fallback_models = tuple(m for m in fallback_models if m != model)
        self._max_tokens = max_tokens
        self._first_token_timeout = first_token_timeout_seconds
        self._total_timeout = total_timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    @property
    def fallback_models(self) -> tuple[str, ...]:
        return self._fallback_models

    def new_record(self, metadata: Mapping[str, str] | None = None) -> GenerationRecord:
        return GenerationRecord(
            requested_model=self._model,
            provider=self._provider.name,
            metadata=dict(metadata or {}),
        )

    async def stream_text(
        self,
        *,
        system: str,
        messages: tuple[ModelMessage, ...],
        record: GenerationRecord,
    ) -> AsyncIterator[str]:
        """Text-only convenience over :meth:`stream` (no tools)."""
        async for event in self.stream(system=system, messages=messages, record=record):
            if event.delta:
                yield event.delta

    async def stream(
        self,
        *,
        system: str,
        messages: tuple[ModelMessage, ...],
        record: GenerationRecord,
        tools: tuple[ToolSpec, ...] = (),
    ) -> AsyncIterator[GatewayEvent]:
        """Yield text deltas. Raises ``GatewayError`` on timeout or provider failure.

        Explicit fallback: if a model times out, is unavailable or is rate limited *before its
        first word*, the next configured fallback model is tried within the same overall
        deadline. A reply that has started is never switched to another model. The record
        keeps the requested model, every model attempted, and the model that answered.

        If the consumer stops early, closing this generator closes the provider stream, so
        the model stops generating (and billing) as soon as possible.
        """
        started = time.monotonic()
        deadline = started + self._total_timeout
        candidates = (self._model, *self._fallback_models)
        for index, model in enumerate(candidates):
            is_last = index == len(candidates) - 1
            if not is_last and self._breaker.is_open(model, time.monotonic()):
                continue  # failing recently: go straight to the next model
            record.attempted_models.append(model)
            record.error = None
            try:
                async for event in self._attempt(
                    model, system, messages, tools, record, started=started, deadline=deadline
                ):
                    yield event
            except GatewayError as exc:
                if not record.output_started and exc.code in _FALLBACK_CODES:
                    self._breaker.failure(model, time.monotonic())
                if is_last or record.output_started or exc.code not in _FALLBACK_CODES:
                    raise
                if time.monotonic() >= deadline:
                    raise
            else:
                self._breaker.success(model)
                return

    async def _attempt(
        self,
        model: str,
        system: str,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSpec, ...],
        record: GenerationRecord,
        *,
        started: float,
        deadline: float,
    ) -> AsyncIterator[GatewayEvent]:
        request = ModelRequest(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=self._max_tokens,
            timeout_seconds=max(deadline - time.monotonic(), 0.1),
            metadata=record.metadata,
        )
        first_token_deadline = min(time.monotonic() + self._first_token_timeout, deadline)
        events = aiter(self._provider.stream(request))
        try:
            while True:
                limit = deadline if record.output_started else first_token_deadline
                try:
                    event = await asyncio.wait_for(
                        anext(events), timeout=max(limit - time.monotonic(), 0)
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    record.error = "timeout"
                    raise GatewayError("timeout") from None
                except ModelProviderError as exc:
                    record.error = exc.kind
                    raise GatewayError(exc.kind) from exc
                except Exception as exc:
                    record.error = "provider_error"
                    raise GatewayError("provider_error") from exc

                if event.usage is not None:
                    record.input_tokens = event.usage.input_tokens
                    record.output_tokens = event.usage.output_tokens
                if event.started:
                    record.output_started = True
                if event.delta:
                    record.output_started = True
                    if record.first_token_ms is None:
                        record.first_token_ms = round((time.monotonic() - started) * 1000)
                    yield GatewayEvent(delta=event.delta)
                if event.final is not None:
                    final = event.final
                    record.served_model = final.model
                    record.input_tokens = final.usage.input_tokens
                    record.output_tokens = final.usage.output_tokens
                    record.stop_reason = final.stop_reason
                    record.provider_request_id = final.provider_request_id
                    record.completed = True
                    yield GatewayEvent(final=final)
        finally:
            await events.aclose()  # type: ignore[attr-defined]

    async def health(self) -> bool:
        return await self._provider.health()
