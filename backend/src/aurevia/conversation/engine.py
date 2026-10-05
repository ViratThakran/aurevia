"""One conversational turn: validated history in, streamed reply out."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

from aurevia.conversation.prompt import AgentProfile, build_system_prompt
from aurevia.gateway import GenerationRecord, ModelGateway
from aurevia.providers.model import ModelMessage
from aurevia.sales.state import SalesState

# The model API requires a conversation to open with the user. Voice calls open with the
# agent's greeting, so a neutral marker stands in for the moment the call connected.
CALL_CONNECTED = "(The call has connected.)"


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


class ConversationEngine:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def stream_reply(
        self,
        *,
        agent: AgentProfile,
        state: SalesState,
        history: Sequence[Utterance],
        record: GenerationRecord,
    ) -> AsyncIterator[str]:
        return self._gateway.stream_text(
            system=build_system_prompt(agent, state),
            messages=to_model_messages(history),
            record=record,
        )
