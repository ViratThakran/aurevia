"""Placing one outbound phone call: plan limits, the compliance gate, the call, the dial.

The one path every outbound call takes: the API, a campaign's "call next", and the automatic
campaign dialer all come through ``place_outbound``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.campaigns.models import Campaign
from aurevia.compliance.gate import ComplianceGate
from aurevia.compliance.policy import CallPurpose, TelephonyMode
from aurevia.compliance.policy_service import PolicyService
from aurevia.config import Settings
from aurevia.db.session import Database, set_tenant_context
from aurevia.errors import ServiceUnavailableError
from aurevia.memory.models import Lead
from aurevia.platform.limits import check_can_start_call
from aurevia.providers.dnd import DndRegistry
from aurevia.providers.telephony import TelephonyProvider
from aurevia.providers.voice_transport import VoiceTransport
from aurevia.telephony.service import AgentDispatch, create_outbound_call, dial
from aurevia.voice.service import AgentService, CallService

# Runs a coroutine factory after the request (FastAPI BackgroundTasks) or as a task.
Schedule = Callable[[Callable[[], Awaitable[object]]], None]


@dataclass(frozen=True)
class OutboundDeps:
    settings: Settings
    database: Database
    telephony: TelephonyProvider
    transport: VoiceTransport
    dnd: DndRegistry
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class PlacedCall:
    call_id: uuid.UUID
    decision_id: uuid.UUID
    room: str


def outbound_deps(state: object) -> OutboundDeps:
    """From ``app.state``; raises 503 when phone calls are not configured."""
    telephony = getattr(state, "telephony", None)
    transport = getattr(state, "voice_transport", None)
    database = getattr(state, "database", None)
    if telephony is None or transport is None or database is None:
        raise ServiceUnavailableError("Phone calls are not configured")
    return OutboundDeps(
        settings=state.settings,  # type: ignore[attr-defined]
        database=database,
        telephony=telephony,
        transport=transport,
        dnd=state.dnd_registry,  # type: ignore[attr-defined]
        clock=state.clock,  # type: ignore[attr-defined]
    )


async def place_outbound(
    session: AsyncSession,
    deps: OutboundDeps,
    *,
    tenant_id: uuid.UUID,
    lead: Lead,
    purpose: CallPurpose,
    campaign: Campaign | None,
    requested_by: uuid.UUID | None,
    schedule: Schedule,
) -> PlacedCall:
    """Raises ``PlanLimitError`` (nothing recorded) or ``CallBlockedError`` (decision recorded).

    Commits; the caller's tenant context is re-set before this returns.
    """
    settings = deps.settings
    assert settings.jwt_secret is not None  # noqa: S101 - telephony implies auth configured
    now = deps.clock()
    await check_can_start_call(session, tenant_id, settings, now)
    agent = await AgentService(session, tenant_id).default_agent()
    pack = await PolicyService(session, tenant_id).effective_pack(settings.compliance_policy_pack)
    gate = ComplianceGate(
        session, tenant_id, pack=pack, mode=TelephonyMode(settings.telephony_mode), dnd=deps.dnd
    )
    approval = await gate.check_outbound(
        lead=lead,
        purpose=purpose,
        requested_by=requested_by,
        agent=agent,
        campaign=campaign,
        now=now,
    )
    call = await create_outbound_call(
        session, approval=approval, agent=agent, user_id=requested_by, now=now
    )
    await session.commit()  # the allow decision and its call, together
    await set_tenant_context(session, tenant_id)

    dispatch = AgentDispatch(
        agent_name=settings.livekit_agent_name,
        jwt_secret=settings.jwt_secret.get_secret_value(),
        call_token_ttl_seconds=settings.call_token_ttl_seconds,
    )
    try:
        await deps.transport.open_room_with_agent(
            room=call.room, agent_name=dispatch.agent_name, metadata=dispatch.metadata(call)
        )
    except Exception as exc:
        await CallService(session, tenant_id).end(call.id, "room_setup_failed", failed=True)
        await set_tenant_context(session, tenant_id)
        raise ServiceUnavailableError("The voice service is unavailable") from exc

    room, call_id = call.room, call.id

    async def job() -> None:  # a coroutine function: BackgroundTasks awaits it
        await dial(
            deps.database,
            deps.telephony,
            deps.transport,
            approval=approval,
            call_id=call_id,
            room=room,
            ring_timeout_seconds=settings.ring_timeout_seconds,
        )

    schedule(job)
    return PlacedCall(call_id=call_id, decision_id=approval.decision_id, room=room)
