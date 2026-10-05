"""Real-time voice transport (rooms, participant tokens, agent dispatch).

The only module that imports the LiveKit server SDK. Business code sees ``VoiceTransport``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol, runtime_checkable

from livekit import api


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
