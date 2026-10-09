"""Gemini adapter for the Model Gateway. The only module that imports the Google GenAI SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

import httpx
from google import genai
from google.genai import errors, types

from aurevia.providers.model import (
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
)

Effort = Literal["low", "medium", "high"]

# Gemini 3+ models take a thinking level. For Flash models "low" effort means MINIMAL: in
# testing (2026-10-08) it cut time to first token from ~1.5-2.9 s to ~0.8-0.95 s with
# no thinking tokens and equally short replies. Pro models have no MINIMAL level.
_THINKING_LEVELS: dict[Effort, types.ThinkingLevel] = {
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}
# Gemini 2.5 models take a token budget instead (-1 = the model decides).
_THINKING_BUDGETS: dict[Effort, int] = {"low": 0, "medium": 1024, "high": -1}


def thinking_config(model: str, effort: Effort) -> types.ThinkingConfig:
    if model.startswith("gemini-2.5"):
        budget = _THINKING_BUDGETS[effort]
        if budget == 0 and "pro" in model:
            budget = 128  # Pro models cannot turn thinking off; this is their minimum
        return types.ThinkingConfig(thinking_budget=budget)
    if effort == "low" and "flash" in model:
        return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
    return types.ThinkingConfig(thinking_level=_THINKING_LEVELS[effort])


class GeminiModelProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        effort: Effort,
        http_client: httpx.AsyncClient | None = None,  # tests inject a mock transport
    ) -> None:
        options = types.HttpOptions(httpx_async_client=http_client) if http_client else None
        # The SDK sends the key in a request header, never in the URL.
        self._client = genai.Client(api_key=api_key, http_options=options)
        self._effort: Effort = effort

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
        except errors.APIError as exc:
            raise _normalize(exc) from None  # vendor text is dropped: it may echo the request
        except httpx.TimeoutException:
            raise ModelProviderError(self.name, "timeout") from None
        except httpx.HTTPError:
            raise ModelProviderError(self.name, "unavailable") from None

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            max_output_tokens=request.max_tokens,
            thinking_config=thinking_config(request.model, self._effort),
            http_options=types.HttpOptions(timeout=round(request.timeout_seconds * 1000)),
        )
        contents = [
            types.Content(
                role="user" if m.role == "user" else "model", parts=[types.Part(text=m.content)]
            )
            for m in request.messages
        ]
        stream = await self._client.aio.models.generate_content_stream(
            model=request.model, contents=contents, config=config
        )

        text: list[str] = []
        last: types.GenerateContentResponse | None = None
        usage_reported = False
        async for chunk in stream:
            last = chunk
            usage = chunk.usage_metadata
            if not usage_reported and usage is not None and usage.prompt_token_count:
                usage_reported = True
                yield ModelStreamEvent(
                    usage=ModelUsage(input_tokens=usage.prompt_token_count, output_tokens=0)
                )
            for part in _parts(chunk):
                if part.text and not part.thought:  # thought summaries are never spoken
                    text.append(part.text)
                    yield ModelStreamEvent(delta=part.text)

        if last is None:
            raise ModelProviderError(self.name, "unavailable")
        usage = last.usage_metadata
        candidate = last.candidates[0] if last.candidates else None
        yield ModelStreamEvent(
            final=ModelResponse(
                text="".join(text),
                model=last.model_version or request.model,
                usage=ModelUsage(
                    input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                    # Thinking tokens are billed as output.
                    output_tokens=(
                        (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
                        if usage
                        else 0
                    ),
                ),
                stop_reason=(
                    candidate.finish_reason.value.lower()
                    if candidate and candidate.finish_reason
                    else None
                ),
                provider_request_id=last.response_id,
            )
        )

    async def health(self) -> bool:
        return True  # failures surface per request

    async def aclose(self) -> None:
        await self._client.aio.aclose()


def _parts(chunk: types.GenerateContentResponse) -> list[types.Part]:
    if not chunk.candidates or chunk.candidates[0].content is None:
        return []
    return chunk.candidates[0].content.parts or []


def _normalize(exc: errors.APIError) -> ModelProviderError:
    code = exc.code or 0
    if code in (401, 403):
        return ModelProviderError("gemini", "auth_failed")
    if code == 429:
        return ModelProviderError("gemini", "rate_limited")
    if code in (408, 504):
        return ModelProviderError("gemini", "timeout")
    if 400 <= code < 500:
        return ModelProviderError("gemini", "invalid_request")
    return ModelProviderError("gemini", "unavailable")
