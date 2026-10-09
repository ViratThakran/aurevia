"""One conversational turn: validated history in, streamed reply out, tools in between."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from aurevia.conversation.prompt import AgentProfile, PromptContext, build_system_prompt
from aurevia.gateway import GenerationRecord, ModelGateway
from aurevia.providers.model import ModelMessage, ToolResult, ToolSpec
from aurevia.sales.state import SalesState
from aurevia.tools.framework import ToolExecutor

# The model API requires a conversation to open with the user. Voice calls open with the
# agent's greeting, so a neutral marker stands in for the moment the call connected.
CALL_CONNECTED = "(The call has connected.)"
# Model -> tools -> model rounds per turn. The last round offers no tools, so the turn
# always ends with words for the prospect.
MAX_TOOL_ROUNDS = 3


@dataclass(frozen=True)
class Utterance:
    role: Literal["prospect", "agent"]
    text: str


class InvalidHistoryError(ValueError):
    pass


def to_model_messages(history: Sequence[Utterance]) -> tuple[ModelMessage, ...]:
    """Map a call transcript to model messages. The last utterance must be the prospect's."""
    spoken = [u for u in history if u.text.strip()]
    if not spoken or spoken[-1].role != "prospect":
        raise InvalidHistoryError("the turn must end with something the prospect said")
    messages = [
        ModelMessage(role="user" if u.role == "prospect" else "assistant", content=u.text.strip())
        for u in spoken
    ]
    if messages[0].role == "assistant":
        messages.insert(0, ModelMessage(role="user", content=CALL_CONNECTED))
    return tuple(messages)


@dataclass(frozen=True)
class TurnEvent:
    delta: str = ""
    tool_results: tuple[ToolResult, ...] = ()


@dataclass
class TurnRecords:
    """One GenerationRecord per model round, for usage accounting."""

    records: list[GenerationRecord] = field(default_factory=list)


class ConversationEngine:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def stream_reply(
        self,
        *,
        agent: AgentProfile,
        state: SalesState,
        messages: tuple[ModelMessage, ...],
        new_record: Callable[[], GenerationRecord],
        records: TurnRecords,
        context: PromptContext | None = None,
        tools: tuple[ToolSpec, ...] = (),
        executor: ToolExecutor | None = None,
    ) -> AsyncIterator[TurnEvent]:
        """``messages`` come from :func:`to_model_messages` (validated before streaming)."""
        system = build_system_prompt(agent, state, context, tools_enabled=bool(tools))
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            offer = tools if (executor is not None and round_number < MAX_TOOL_ROUNDS) else ()
            record = new_record()
            records.records.append(record)
            final = None
            async for event in self._gateway.stream(
                system=system, messages=messages, record=record, tools=offer
            ):
                if event.delta:
                    yield TurnEvent(delta=event.delta)
                if event.final is not None:
                    final = event.final
            if final is None or not final.tool_calls or executor is None:
                return
            results = tuple([await executor.execute(call) for call in final.tool_calls])
            yield TurnEvent(tool_results=results)
            if final.text.strip() and not executor.needs_follow_up(results):
                return  # already spoke; the calls only recorded things and all succeeded
            messages = (
                *messages,
                ModelMessage(
                    role="assistant",
                    content=final.text,
                    tool_calls=final.tool_calls,
                    provider_state=final.provider_state,
                ),
                ModelMessage(role="user", tool_results=results),
            )
