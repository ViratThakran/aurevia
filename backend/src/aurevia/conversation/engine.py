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
# Pure bookkeeping tools: they change nothing the prospect is told about and nothing about who
# is called again, so they never delay the reply. They run in a second model call after the
# agent has started speaking. Tools the agent talks about, or that stop future calls (booking,
# slots, do-not-call, not interested, handoff), stay in the spoken turn.
DEFERRED_TOOLS = frozenset(
    {
        "set_stage",
        "qualify_lead",
        "mark_interested",
        "log_objection",
        "add_note",
    }
)
RECORD_THIS_TURN = "(Record this turn now.)"
BOOKKEEPING_INSTRUCTIONS = """

# Bookkeeping pass
The reply to the prospect has already been spoken. Do not write any words. Use the tools only
to record what the prospect said and what happened in this turn (stage, qualification, interest,
objection, note). If nothing needs recording, call no tool."""


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
    # What the bookkeeping pass needs once the reply is out (see ConversationEngine.record_turn):
    # the prompt, the history including earlier tool rounds, and the last round's words (earlier
    # rounds' words are already in ``messages``).
    system: str = ""
    messages: tuple[ModelMessage, ...] = ()
    spoken: str = ""


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
        # Speech first: only tools the reply may depend on are offered before the agent talks.
        speech_tools = tuple(t for t in tools if t.name not in DEFERRED_TOOLS)
        records.system = system
        records.messages = messages
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            offer = (
                speech_tools if (executor is not None and round_number < MAX_TOOL_ROUNDS) else ()
            )
            record = new_record()
            records.records.append(record)
            records.spoken = ""
            final = None
            async for event in self._gateway.stream(
                system=system, messages=messages, record=record, tools=offer
            ):
                if event.delta:
                    records.spoken += event.delta
                    yield TurnEvent(delta=event.delta)
                if event.final is not None:
                    final = event.final
            if final is None or not final.tool_calls or executor is None:
                return
            results = tuple([await executor.execute(call) for call in final.tool_calls])
            yield TurnEvent(tool_results=results)
            if final.text.strip() and not executor.needs_follow_up(results):
                return  # already spoke; the calls only recorded things and all succeeded
            messages = records.messages = (
                *messages,
                ModelMessage(
                    role="assistant",
                    content=final.text,
                    tool_calls=final.tool_calls,
                    provider_state=final.provider_state,
                ),
                ModelMessage(role="user", tool_results=results),
            )

    async def record_turn(
        self,
        *,
        records: TurnRecords,
        new_record: Callable[[], GenerationRecord],
        tools: tuple[ToolSpec, ...],
        executor: ToolExecutor,
    ) -> tuple[ToolResult, ...]:
        """The bookkeeping pass: record what happened in a turn whose reply is already out.

        One model call that may only use the deferred bookkeeping tools; its text is ignored.
        Runs after the agent started speaking, so it never adds to the prospect's wait.
        """
        specs = tuple(t for t in tools if t.name in DEFERRED_TOOLS)
        if not specs or not records.system:
            return ()
        messages = records.messages
        if records.spoken.strip():
            messages = (
                *messages,
                ModelMessage(role="assistant", content=records.spoken.strip()),
                ModelMessage(role="user", content=RECORD_THIS_TURN),
            )
        record = new_record()
        records.records.append(record)
        final = None
        async for event in self._gateway.stream(
            system=records.system + BOOKKEEPING_INSTRUCTIONS,
            messages=messages,
            record=record,
            tools=specs,
        ):
            if event.final is not None:
                final = event.final
        if final is None:
            return ()
        calls = [call for call in final.tool_calls if call.name in DEFERRED_TOOLS]
        return tuple([await executor.execute(call) for call in calls])
