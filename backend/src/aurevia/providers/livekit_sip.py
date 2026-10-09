"""Telephony through LiveKit SIP: the callee joins the call's LiveKit room as a participant.

The carrier (Exotel first) is an outbound SIP trunk configured in LiveKit; its id is the only
carrier-specific setting here. See docs/02-voice/telephony.md.
"""

from __future__ import annotations

from datetime import timedelta

from google.protobuf.duration_pb2 import Duration
from livekit import api

from aurevia.providers.telephony import (
    AnsweredCall,
    DialError,
    DialFailure,
    OutboundCallRequest,
    failure_for_sip_status,
)

PHONE_IDENTITY_PREFIX = "phone-"


class LiveKitSipTelephony:
    name = "livekit_sip"

    def __init__(self, *, url: str, api_key: str, api_secret: str, outbound_trunk_id: str) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._trunk_id = outbound_trunk_id

    async def place_call(self, request: OutboundCallRequest) -> AnsweredCall:
        ring = Duration()
        ring.FromTimedelta(timedelta(seconds=request.ring_timeout_seconds))
        lk = api.LiveKitAPI(url=self._url, api_key=self._api_key, api_secret=self._api_secret)
        try:
            info = await lk.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=self._trunk_id,
                    sip_call_to=request.to_number,
                    sip_number=request.from_number,
                    room_name=request.room,
                    participant_identity=f"{PHONE_IDENTITY_PREFIX}{request.call_id.hex}",
                    participant_name="Prospect",
                    ringing_timeout=ring,
                    wait_until_answered=True,
                )
            )
        except api.SipCallError as exc:
            raise DialError(
                failure_for_sip_status(exc.sip_status_code), sip_status=exc.sip_status_code
            ) from exc
        except api.ServerError as exc:
            raise DialError(DialFailure.FAILED) from exc
        finally:
            await lk.aclose()
        return AnsweredCall(provider_call_id=info.sip_call_id)
