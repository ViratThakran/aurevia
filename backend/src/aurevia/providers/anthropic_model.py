"""Claude adapter for the Model Gateway. The only module that imports the Anthropic SDK."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Literal

import anthropic
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient, omit
from anthropic.types.beta import BetaMessageParam, BetaToolParam

from aurevia.providers.model import (
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
    ToolCall,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicModelProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        effort: Literal["low", "medium", "high"],
        server_fallback: bool,
        max_retries: int = 1,
        http_client: DefaultAsyncHttpxClient | None = None,  # tests inject a mock transport
    ) -> None:
        # One retry: a voice turn cannot wait through the SDK's default backoff.
        self._client = AsyncAnthropic(
            api_key=api_key, max_retries=max_retries, http_client=http_client
        )
        self._effort: Literal["low", "medium", "high"] = effort
        self._server_fallback = server_fallback

    async def generate(self, request: ModelRequest) -> ModelResponse:
        final: ModelResponse | None = None
        async for event in self.stream(request):
            if event.final is not None:
                final = event.final
        if final is None:
            raise ModelProviderError(self.name, "unavailable")
        return final

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        try:
            async for event in self._stream(request):
                yield event
        except anthropic.APIError as exc:
            raise _normalize(exc) from None  # vendor text is dropped: it may echo the request

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        messages = to_messages(request.messages)
        tools: list[BetaToolParam] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.parameters),
                # Stream tool inputs as generated; they are validated server-side anyway.
                "eager_input_streaming": True,
            }
            for tool in request.tools
        ]
        async with self._client.beta.messages.stream(
            model=request.model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=messages,
            # Thinking stays adaptive (the model default); effort bounds it for latency.
            output_config={"effort": self._effort},
            betas=[FALLBACK_BETA] if self._server_fallback else omit,
            fallbacks="default" if self._server_fallback else omit,
            tools=tools or omit,
            timeout=request.timeout_seconds,
        ) as stream:
            async for event in stream:
                if event.type == "message_start":
                    yield ModelStreamEvent(
                        usage=ModelUsage(
                            input_tokens=event.message.usage.input_tokens, output_tokens=0
                        )
                    )
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield ModelStreamEvent(delta=event.delta.text)
                elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                    yield ModelStreamEvent(started=True)
            message = await stream.get_final_message()
            request_id = stream.request_id

        text = "".join(block.text for block in message.content if block.type == "text")
        calls = tuple(
            ToolCall(
                id=block.id,
                name=block.name,
                arguments=block.input if isinstance(block.input, dict) else {},
            )
            for block in message.content
            if block.type == "tool_use"
        )
        yield ModelStreamEvent(
            final=ModelResponse(
                text=text,
                model=message.model,  # differs from request.model if a fallback answered
                usage=ModelUsage(
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                ),
                stop_reason=message.stop_reason,
                provider_request_id=request_id,
                tool_calls=calls,
                # The whole assistant turn (thinking blocks included) is sent back unchanged.
                provider_state=([block.to_dict() for block in message.content] if calls else None),
            )
        )

    async def health(self) -> bool:
        return True  # no cheap health endpoint; failures surface per request

    async def aclose(self) -> None:
        await self._client.close()


def to_messages(messages: tuple[ModelMessage, ...]) -> list[BetaMessageParam]:
    out: list[BetaMessageParam] = []
    for message in messages:
        if message.role == "assistant" and isinstance(message.provider_state, list):
            out.append({"role": "assistant", "content": message.provider_state})
        elif message.tool_results:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.call_id,
                            "content": json.dumps(dict(result.content)),
                            "is_error": result.is_error,
                        }
                        for result in message.tool_results
                    ],
                }
            )
        else:
            out.append({"role": message.role, "content": message.content})
    return out


def _normalize(exc: anthropic.APIError) -> ModelProviderError:
    if isinstance(exc, anthropic.APITimeoutError):
        return ModelProviderError("anthropic", "timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ModelProviderError("anthropic", "unavailable")
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ModelProviderError("anthropic", "auth_failed")
    if isinstance(exc, anthropic.RateLimitError):
        return ModelProviderError("anthropic", "rate_limited")
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code < 500:
        return ModelProviderError("anthropic", "invalid_request")
    return ModelProviderError("anthropic", "unavailable")
