"""Claude adapter for the Model Gateway. The only module that imports the Anthropic SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient, omit
from anthropic.types.beta import BetaMessageParam

from aurevia.providers.model import (
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelProviderError(Exception):
    """The provider failed; the message is safe to log, never shown to a caller."""


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
            raise ModelProviderError("stream ended without a final message")
        return final

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        messages: list[BetaMessageParam] = [
            {"role": m.role, "content": m.content} for m in request.messages
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
            message = await stream.get_final_message()
            request_id = stream.request_id

        text = "".join(block.text for block in message.content if block.type == "text")
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
            )
        )

    async def health(self) -> bool:
        return True  # no cheap health endpoint; failures surface per request

    async def aclose(self) -> None:
        await self._client.close()
