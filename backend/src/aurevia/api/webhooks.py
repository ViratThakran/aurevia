"""Webhooks from the media server (LiveKit). Signed with our API secret; anything else is 401.

Handlers are idempotent: the media server retries deliveries.
- ``participant_joined`` of a phone line in an inbound room: register the call, send the agent.
- ``room_finished``: close the room's call if it is still open (worker crash, lost network).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request

from aurevia.errors import AuthenticationError, ServiceUnavailableError
from aurevia.providers.voice_transport import (
    PARTICIPANT_JOINED,
    ROOM_FINISHED,
    InvalidWebhookError,
    VoiceTransport,
)
from aurevia.telephony.service import AgentDispatch, close_call_for_room, register_inbound_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)

SIP_TRUNK_NUMBER = "sip.trunkPhoneNumber"  # the number that was dialed (ours)
SIP_CALLER_NUMBER = "sip.phoneNumber"  # the caller's number


@router.post("/livekit")
async def livekit_webhook(
    request: Request, authorization: str = Header(default="")
) -> dict[str, str]:
    transport: VoiceTransport | None = request.app.state.voice_transport
    database = request.app.state.database
    if transport is None or database is None:
        raise ServiceUnavailableError("Voice is not configured")
    body = (await request.body()).decode("utf-8", errors="replace")
    try:
        event = transport.parse_webhook(body, authorization)
    except InvalidWebhookError as exc:
        raise AuthenticationError("Invalid webhook signature") from exc

    settings = request.app.state.settings
    if event.kind == ROOM_FINISHED and event.room:
        await close_call_for_room(database, room=event.room)
    elif (
        event.kind == PARTICIPANT_JOINED
        and event.is_phone
        and event.room.startswith(settings.inbound_room_prefix)
    ):
        if settings.jwt_secret is None:
            raise ServiceUnavailableError("Voice is not configured")
        await register_inbound_call(
            database,
            transport,
            AgentDispatch(
                agent_name=settings.livekit_agent_name,
                jwt_secret=settings.jwt_secret.get_secret_value(),
                call_token_ttl_seconds=settings.call_token_ttl_seconds,
            ),
            room=event.room,
            dialed=event.attributes.get(SIP_TRUNK_NUMBER),
            caller=event.attributes.get(SIP_CALLER_NUMBER),
        )
    return {"status": "ok"}
