"""AI Model Gateway: the only path from Aurevia code to a language model.

It owns model selection, deadlines, and the record of what happened on every request
(requested vs. served model, tokens, time to first token, whether the caller cut it off).
Fallback is explicit configuration passed to the provider, never a silent switch here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field

from aurevia.providers.model import ModelMessage, ModelProvider, ModelRequest


class GatewayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code  # "timeout" | "provider_error"


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
    error: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def interrupted(self) -> bool:
        """The consumer stopped reading before the reply finished (e.g. barge-in)."""
        return not self.completed and self.error is None


class ModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        model: str,
        max_tokens: int,
        first_token_timeout_seconds: float,
        total_timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._first_token_timeout = first_token_timeout_seconds
        self._total_timeout = total_timeout_seconds

    @property
    def model(self) -> str:
        return self._model

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
        """Yield text deltas. Raises ``GatewayError`` on timeout or provider failure.

        If the consumer stops early, closing this generator closes the provider stream, so
        the model stops generating (and billing) as soon as possible.
        """
        request = ModelRequest(
            model=self._model,
            system=system,
            messages=messages,
            max_tokens=self._max_tokens,
            timeout_seconds=self._total_timeout,
            metadata=record.metadata,
        )
        started = time.monotonic()
        deadline = started + self._total_timeout
        first_token_deadline = started + self._first_token_timeout
        events = aiter(self._provider.stream(request))
        try:
            while True:
                limit = deadline if record.first_token_ms is not None else first_token_deadline
                try:
                    event = await asyncio.wait_for(
                        anext(events), timeout=max(limit - time.monotonic(), 0)
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    record.error = "timeout"
                    raise GatewayError("timeout") from None
                except Exception as exc:
                    record.error = "provider_error"
                    raise GatewayError("provider_error") from exc

                if event.usage is not None:
                    record.input_tokens = event.usage.input_tokens
                    record.output_tokens = event.usage.output_tokens
                if event.delta:
                    if record.first_token_ms is None:
                        record.first_token_ms = round((time.monotonic() - started) * 1000)
                    yield event.delta
                if event.final is not None:
                    final = event.final
                    record.served_model = final.model
                    record.input_tokens = final.usage.input_tokens
                    record.output_tokens = final.usage.output_tokens
                    record.stop_reason = final.stop_reason
                    record.provider_request_id = final.provider_request_id
                    record.completed = True
        finally:
            await events.aclose()  # type: ignore[attr-defined]

    async def health(self) -> bool:
        return await self._provider.health()
