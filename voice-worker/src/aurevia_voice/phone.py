"""Phone calls: the agent speaks only once the phone line has actually been answered.

A dialed phone joins the room while it is still ringing; LiveKit sets the participant attribute
``sip.callStatus`` to ``active`` when it is picked up. Inbound callers are active on arrival.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from livekit import rtc

SIP_CALL_STATUS = "sip.callStatus"
ANSWERED = "active"


class _Participant(Protocol):
    @property
    def kind(self) -> Any: ...

    @property
    def attributes(self) -> dict[str, str]: ...


def is_answered_phone(participant: _Participant) -> bool:
    return (
        participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        and participant.attributes.get(SIP_CALL_STATUS) == ANSWERED
    )


async def wait_for_answer(room: rtc.Room, within_seconds: float) -> bool:
    """True once a phone participant is answered; False on timeout or if the room closes."""
    answered: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def check(participant: Any) -> None:
        if not answered.done() and is_answered_phone(participant):
            answered.set_result(True)

    def on_attributes(_changed: dict[str, str], participant: Any) -> None:
        check(participant)

    def on_disconnected(*_args: Any) -> None:
        # The backend closes the room when the dial fails: stop waiting at once.
        if not answered.done():
            answered.set_result(False)

    room.on("participant_connected", check)
    room.on("participant_attributes_changed", on_attributes)
    room.on("disconnected", on_disconnected)
    try:
        for participant in room.remote_participants.values():
            check(participant)
        return await asyncio.wait_for(answered, within_seconds)
    except TimeoutError:
        return False
    finally:
        room.off("participant_connected", check)
        room.off("participant_attributes_changed", on_attributes)
        room.off("disconnected", on_disconnected)
