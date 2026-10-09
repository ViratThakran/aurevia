"""LLM provider contract, used only by the AI Model Gateway (Phase 2).

Fallback between providers is the gateway's explicit policy, never an adapter's: an adapter
that cannot serve a request raises, it does not quietly call a different model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

ProviderErrorKind = Literal[
    "auth_failed", "rate_limited", "invalid_request", "unavailable", "timeout"
]


class ModelProviderError(Exception):
    """A provider failure, normalized so callers never handle vendor SDK exceptions.

    The message is generic by construction: vendor error text (which can echo request
    details) is never copied into it, so it is safe to log.
    """

    def __init__(self, provider: str, kind: ProviderErrorKind) -> None:
        super().__init__(f"{provider}: {kind}")
        self.provider = provider
        self.kind: ProviderErrorKind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limited", "unavailable", "timeout")


@dataclass(frozen=True)
class ToolSpec:
    """A function the model may ask to call. ``parameters`` is a JSON Schema object."""

    name: str
    description: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model's *request* to run a tool. Nothing runs until the server validates it."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: Mapping[str, Any]
    is_error: bool = False


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["user", "assistant"]
    content: str = ""
    # Assistant turns that asked for tools, and the user turn that answers them.
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    # Opaque provider data that must be sent back unchanged with this assistant turn (e.g.
    # Gemini thought signatures, Anthropic thinking blocks). Only the adapter that produced
    # it reads it; other adapters ignore it.
    provider_state: Any = None


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    messages: tuple[ModelMessage, ...]
    max_tokens: int
    timeout_seconds: float = 30.0
    tools: tuple[ToolSpec, ...] = ()
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
    tool_calls: tuple[ToolCall, ...] = ()
    provider_state: Any = None  # see ModelMessage.provider_state


@dataclass(frozen=True)
class ModelStreamEvent:
    """One of: a text delta; a usage update (usage known so far, e.g. input tokens as soon
    as the request is accepted); ``started`` (the model produced output that is not text,
    such as a tool call); or, exactly once and last, the final response."""

    delta: str = ""
    usage: ModelUsage | None = None
    started: bool = False
    final: ModelResponse | None = None


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...

    async def health(self) -> bool: ...
