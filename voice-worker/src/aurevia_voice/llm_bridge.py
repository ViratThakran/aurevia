"""A LiveKit ``LLM`` whose replies come from the Aurevia backend, not from a model SDK.

LiveKit's session handles listening, turn detection, interruption and speaking; at each turn
it asks this LLM for a reply. We forward the transcript to the backend and stream its answer
back. When the prospect interrupts, LiveKit closes the stream and the backend stops generating.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    NotGivenOr,
    llm,
)

from aurevia_voice.backend_client import BackendClient, BackendError, Utterance


def history_from(chat_ctx: llm.ChatContext) -> list[Utterance]:
    """The spoken transcript, oldest first. Instructions and tool items are not sent: the
    backend owns the prompt."""
    history: list[Utterance] = []
    for message in chat_ctx.messages():
        text = (message.text_content or "").strip()
        if not text:
            continue
        if message.role == "user":
            history.append(Utterance(role="prospect", text=text))
        elif message.role == "assistant":
            history.append(Utterance(role="agent", text=text))
    return history


class BackendLLM(llm.LLM[Any]):
    def __init__(self, backend: BackendClient) -> None:
        super().__init__()
        self._backend = backend

    @property
    def model(self) -> str:
        return "aurevia-model-gateway"

    @property
    def provider(self) -> str:
        return "aurevia"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> BackendLLMStream:
        return BackendLLMStream(
            self, backend=self._backend, chat_ctx=chat_ctx, conn_options=conn_options
        )


class BackendLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm_: BackendLLM,
        *,
        backend: BackendClient,
        chat_ctx: llm.ChatContext,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(llm_, chat_ctx=chat_ctx, tools=[], conn_options=conn_options)
        self._backend = backend
        # Once the agent has started speaking, retrying would repeat words: never retry then.
        self._retry_on_chunk_sent = False

    async def _run(self) -> None:
        chunk_id = uuid.uuid4().hex
        try:
            async for text in self._backend.stream_turn(history_from(self._chat_ctx)):
                self._event_ch.send_nowait(
                    llm.ChatChunk(
                        id=chunk_id, delta=llm.ChoiceDelta(role="assistant", content=text)
                    )
                )
        except BackendError as exc:
            raise APIStatusError(
                f"backend turn failed: {exc.code}", status_code=exc.status, retryable=exc.retryable
            ) from exc
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError() from exc
