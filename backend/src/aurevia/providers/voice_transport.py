"""Real-time voice transport (rooms, participant tokens, agent dispatch, webhooks).

The LiveKit server SDK is imported only here and in ``livekit_sip.py``. Business code sees
``VoiceTransport`` and neutral ``TransportEvent`` values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol, runtime_checkable

from livekit import api

ROOM_FINISHED = "room_finished"
PARTICIPANT_JOINED = "participant_joined"


class InvalidWebhookError(Exception):
    """The webhook was not signed by our media server, or its body was altered."""


@dataclass(frozen=True)
class TransportEvent:
    kind: str
    room: str
    participant_identity: str = ""
    is_phone: bool = False  # the participant is a phone line (SIP)
    attributes: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class VoiceTransport(Protocol):
    @property
    def public_url(self) -> str:
        """The URL a browser connects to."""
        ...

    def participant_token(self, *, room: str, identity: str, name: str, ttl_seconds: int) -> str:
        """A token that lets one browser participant join one room with audio."""
        ...

    async def open_room_with_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        """Create the room and dispatch the voice agent into it, server to server.

        ``metadata`` reaches only the agent worker; browsers never see it.
        """
        ...

    async def dispatch_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        """Send the voice agent into an existing room (inbound phone calls)."""
        ...

    async def close_room(self, room: str) -> None:
        """End the room for everyone in it, including a phone line."""
        ...

    def parse_webhook(self, body: str, authorization: str) -> TransportEvent:
        """Verify a media-server webhook and return it; raise ``InvalidWebhookError``."""
        ...


class LiveKitTransport:
    def __init__(self, *, url: str, public_url: str, api_key: str, api_secret: str) -> None:
        self._url = url
        self._public_url = public_url
        self._api_key = api_key
        self._api_secret = api_secret

    @property
    def public_url(self) -> str:
        return self._public_url

    def participant_token(self, *, room: str, identity: str, name: str, ttl_seconds: int) -> str:
        grants = api.VideoGrants(
            room_join=True,
            room=room,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        return (
            api.AccessToken(self._api_key, self._api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=ttl_seconds))
            .to_jwt()
        )

    async def open_room_with_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        lk = api.LiveKitAPI(url=self._url, api_key=self._api_key, api_secret=self._api_secret)
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(
                    name=room,
                    empty_timeout=120,  # seconds a room may sit empty before closing
                    max_participants=4,
                    agents=[api.RoomAgentDispatch(agent_name=agent_name, metadata=metadata)],
                )
            )
        finally:
            await lk.aclose()

    async def dispatch_agent(self, *, room: str, agent_name: str, metadata: str) -> None:
        lk = api.LiveKitAPI(url=self._url, api_key=self._api_key, api_secret=self._api_secret)
        try:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=agent_name, room=room, metadata=metadata)
            )
        finally:
            await lk.aclose()

    async def close_room(self, room: str) -> None:
        lk = api.LiveKitAPI(url=self._url, api_key=self._api_key, api_secret=self._api_secret)
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))
        except api.ServerError as exc:
            if exc.status != 404:  # already gone is fine
                raise
        finally:
            await lk.aclose()

    def parse_webhook(self, body: str, authorization: str) -> TransportEvent:
        receiver = api.WebhookReceiver(api.TokenVerifier(self._api_key, self._api_secret))
        try:
            event = receiver.receive(body, authorization)
        except Exception as exc:  # the SDK raises several types for a bad signature or body
            raise InvalidWebhookError("invalid webhook") from exc
        participant = event.participant if event.HasField("participant") else None
        return TransportEvent(
            kind=event.event,
            room=event.room.name if event.HasField("room") else "",
            participant_identity=participant.identity if participant else "",
            is_phone=bool(participant and participant.kind == api.ParticipantInfo.Kind.SIP),
            attributes=dict(participant.attributes) if participant else {},
        )
