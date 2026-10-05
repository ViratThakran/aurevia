"""Browser voice sessions and call status, for signed-in users."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import case, func, select

from aurevia.errors import ServiceUnavailableError
from aurevia.identity.dependencies import AdminDep, PrincipalDep, SessionDep, SettingsDep
from aurevia.providers.voice_transport import VoiceTransport
from aurevia.usage.models import UsageEvent, UsageKind
from aurevia.voice.call_auth import create_call_token
from aurevia.voice.schemas import (
    AgentResponse,
    AgentUpdate,
    CallResponse,
    CallUsage,
    VoiceSessionResponse,
)
from aurevia.voice.service import AgentService, AgentSettings, CallService

router = APIRouter(tags=["voice"])

# Browser participant tokens only need to outlive joining the room.
PARTICIPANT_TOKEN_TTL_SECONDS = 15 * 60


def _transport(request: Request) -> VoiceTransport:
    transport: VoiceTransport | None = request.app.state.voice_transport
    if transport is None:
        raise ServiceUnavailableError("Voice is not configured")
    return transport


def _agent_response(agent: object) -> AgentResponse:
    return AgentResponse.model_validate(agent, from_attributes=True)


@router.get("/agents/default", summary="The tenant's default AI agent")
async def get_default_agent(principal: PrincipalDep, session: SessionDep) -> AgentResponse:
    agent = await AgentService(session, principal.tenant_id).default_agent()
    await session.commit()  # persists the agent if this call created it
    return _agent_response(agent)


@router.put("/agents/default", summary="Configure the default AI agent (owner/admin)")
async def update_default_agent(
    body: AgentUpdate, principal: AdminDep, session: SessionDep
) -> AgentResponse:
    agent = await AgentService(session, principal.tenant_id).update_default_agent(
        AgentSettings(**body.model_dump()), actor=principal.user_id
    )
    return _agent_response(agent)


@router.post(
    "/voice/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Start a browser voice call with the default agent",
)
async def create_voice_session(
    request: Request, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> VoiceSessionResponse:
    transport = _transport(request)
    assert settings.jwt_secret is not None  # noqa: S101 - authenticated requests imply it
    agent = await AgentService(session, principal.tenant_id).default_agent()
    call = await CallService(session, principal.tenant_id).create_browser_call(
        agent=agent, user_id=principal.user_id
    )
    await session.commit()

    call_token = create_call_token(
        call_id=call.id,
        tenant_id=principal.tenant_id,
        secret=settings.jwt_secret.get_secret_value(),
        ttl_seconds=settings.call_token_ttl_seconds,
    )
    await transport.open_room_with_agent(
        room=call.room,
        agent_name=settings.livekit_agent_name,
        metadata=json.dumps({"call_id": str(call.id), "call_token": call_token}),
    )
    return VoiceSessionResponse(
        call_id=call.id,
        room=call.room,
        livekit_url=transport.public_url,
        token=transport.participant_token(
            room=call.room,
            identity=f"user-{principal.user_id}",
            name="Prospect",
            ttl_seconds=PARTICIPANT_TOKEN_TTL_SECONDS,
        ),
    )


@router.get("/voice/calls/{call_id}", summary="Call status and usage")
async def get_call(
    call_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CallResponse:
    call = await CallService(session, principal.tenant_id).get(call_id)
    is_llm = UsageEvent.kind == UsageKind.LLM
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((is_llm, UsageEvent.input_tokens), else_=0)), 0),
                func.coalesce(func.sum(case((is_llm, UsageEvent.output_tokens), else_=0)), 0),
                func.count().filter(is_llm),
                func.count().filter(is_llm, UsageEvent.interrupted.is_(True)),
                func.coalesce(
                    func.sum(
                        case((UsageEvent.kind == UsageKind.STT, UsageEvent.audio_seconds), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((UsageEvent.kind == UsageKind.TTS, UsageEvent.characters), else_=0)
                    ),
                    0,
                ),
            ).where(UsageEvent.tenant_id == principal.tenant_id, UsageEvent.call_id == call.id)
        )
    ).one()
    return CallResponse(
        id=call.id,
        channel=call.channel,
        status=call.status,
        sales_state=call.sales_state,
        turn_count=call.turn_count,
        started_at=call.started_at,
        ended_at=call.ended_at,
        end_reason=call.end_reason,
        usage=CallUsage(
            llm_input_tokens=int(row[0]),
            llm_output_tokens=int(row[1]),
            llm_turns=int(row[2]),
            llm_interrupted_turns=int(row[3]),
            stt_seconds=float(row[4]),
            tts_characters=int(row[5]),
        ),
    )
