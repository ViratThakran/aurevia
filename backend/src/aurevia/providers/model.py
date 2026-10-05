"""LLM provider contract, used only by the AI Model Gateway (Phase 2).

Fallback between providers is the gateway's explicit policy, never an adapter's: an adapter
that cannot serve a request raises, it does not quietly call a different model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    messages: tuple[ModelMessage, ...]
    max_tokens: int
    timeout_seconds: float = 30.0
    # Correlation ids (tenant_id, call_id, request_id, prompt_version); never content.
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model: str  # the exact model that answered, as reported by the provider
    usage: ModelUsage
    stop_reason: str | None
    provider_request_id: str | None = None


@dataclass(frozen=True)
class ModelStreamEvent:
    """One of: a text delta; a usage update (usage known so far, e.g. input tokens as soon
    as the request is accepted); or, exactly once and last, the final response."""

    delta: str = ""
    usage: ModelUsage | None = None
    final: ModelResponse | None = None


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...

    async def health(self) -> bool: ...
