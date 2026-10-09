"""Phone call lifecycle: outbound (gate-approved) dialing, inbound registration, cleanup.

``dial`` is the only caller of ``TelephonyProvider.place_call`` and it takes an ``Approval``,
which only the compliance gate can create. Webhook handlers run without a tenant in scope, so
they find their call or number through two narrow SECURITY DEFINER lookups (migration 0006)
and then work inside that tenant's row-level-security scope like everything else.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.compliance.gate import Approval
from aurevia.compliance.phone import lookup_variants, mask, normalize_e164
from aurevia.db.session import Database, set_tenant_context
from aurevia.errors import ConflictError
from aurevia.memory.models import Lead, LeadStatus
from aurevia.providers.telephony import DialError, OutboundCallRequest, TelephonyProvider
from aurevia.providers.voice_transport import VoiceTransport
from aurevia.sales.state import SalesState
from aurevia.telephony.models import PhoneNumber
from aurevia.voice.call_auth import create_call_token
from aurevia.voice.models import (
    Agent,
    Call,
    CallChannel,
    CallDirection,
    CallStatus,
    DialStatus,
)
from aurevia.voice.service import AgentService, CallService, room_name

logger = logging.getLogger(__name__)

# An approval is spent at once: a decision taken minutes ago may no longer hold.
APPROVAL_MAX_AGE_SECONDS = 60


@dataclass(frozen=True)
class AgentDispatch:
    agent_name: str
    jwt_secret: str
    call_token_ttl_seconds: int

    def metadata(self, call: Call) -> str:
        token = create_call_token(
            call_id=call.id,
            tenant_id=call.tenant_id,
            secret=self.jwt_secret,
            ttl_seconds=self.call_token_ttl_seconds,
        )
        return json.dumps({"call_id": str(call.id), "call_token": token, "channel": "phone"})


async def create_outbound_call(
    session: AsyncSession,
    *,
    approval: Approval,
    agent: Agent,
    user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> Call:
    """Create the call the approval allows. The caller commits (with the decision)."""
    now = now or datetime.now(UTC)
    if (now - approval.issued_at).total_seconds() > APPROVAL_MAX_AGE_SECONDS:
        raise ConflictError("The compliance approval has expired", code="approval_expired")
    caller_id = await session.scalar(
        select(PhoneNumber).where(
            PhoneNumber.tenant_id == approval.tenant_id,
            PhoneNumber.e164 == approval.from_number,
        )
    )
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        tenant_id=approval.tenant_id,
        agent_id=agent.id,
        lead_id=approval.lead_id,
        created_by_user_id=user_id,
        channel=CallChannel.PHONE,
        status=CallStatus.CREATED,
        sales_state=SalesState.NEW,
        room=room_name(call_id),
        direction=CallDirection.OUTBOUND,
        to_number=approval.to_number,
        from_number=approval.from_number,
        dial_status=DialStatus.QUEUED,
        compliance_decision_id=approval.decision_id,
        phone_number_id=caller_id.id if caller_id else None,
        campaign_id=approval.campaign_id,
    )
    session.add(call)
    await session.flush()
    return call


async def dial(
    database: Database,
    telephony: TelephonyProvider,
    transport: VoiceTransport,
    *,
    approval: Approval,
    call_id: uuid.UUID,
    room: str,
    ring_timeout_seconds: int,
) -> DialStatus:
    """Place the approved call and record how it went. Never raises."""
    request = OutboundCallRequest(
        tenant_id=approval.tenant_id,
        call_id=call_id,
        room=room,
        to_number=approval.to_number,
        from_number=approval.from_number,
        compliance_decision_id=approval.decision_id,
        ring_timeout_seconds=ring_timeout_seconds,
    )
    provider_call_id: str | None = None
    try:
        answered = await telephony.place_call(request)
        status, provider_call_id = DialStatus.ANSWERED, answered.provider_call_id
    except DialError as exc:
        status = DialStatus(exc.failure.value)
    except Exception:
        logger.exception("Dialing failed", extra={"fields": {"call_id": str(call_id)}})
        status = DialStatus.FAILED
    logger.info(
        "Dial finished",
        extra={
            "fields": {
                "call_id": str(call_id),
                "to": mask(approval.to_number),
                "dial_status": status.value,
            }
        },
    )
    try:
        async with database.sessionmaker() as session:
            await set_tenant_context(session, approval.tenant_id)
            call = await CallService(session, approval.tenant_id).get(call_id)
            call.dial_status = status
            call.provider_call_id = provider_call_id
            await session.commit()
            if status != DialStatus.ANSWERED:
                await set_tenant_context(session, approval.tenant_id)
                await CallService(session, approval.tenant_id).end(
                    call_id, f"dial_{status.value}", failed=True
                )
    except Exception:
        logger.exception("Recording the dial result failed")
    if status != DialStatus.ANSWERED:
        try:
            await transport.close_room(room)  # lets the waiting agent leave
        except Exception:
            logger.exception("Closing the room after a failed dial failed")
    return status


@dataclass(frozen=True)
class InboundLine:
    tenant_id: uuid.UUID
    phone_number_id: uuid.UUID
    agent_id: uuid.UUID | None


async def resolve_inbound_line(session: AsyncSession, dialed: str) -> InboundLine | None:
    row = (
        await session.execute(
            text("SELECT tenant_id, phone_number_id, agent_id FROM resolve_inbound_number(:n)"),
            {"n": dialed},
        )
    ).first()
    await session.commit()  # ends the lookup's transaction
    if row is None:
        return None
    return InboundLine(tenant_id=row[0], phone_number_id=row[1], agent_id=row[2])


async def register_inbound_call(
    database: Database,
    transport: VoiceTransport,
    dispatch: AgentDispatch,
    *,
    room: str,
    dialed: str | None,
    caller: str | None,
) -> uuid.UUID | None:
    """Create the call for a phone line that rang in, and send the agent. Idempotent.

    Returns ``None`` (and closes the room) when the dialed number belongs to no tenant.
    """
    to_number = normalize_e164(dialed)
    from_number = normalize_e164(caller)
    async with database.sessionmaker() as session:
        line = await resolve_inbound_line(session, to_number) if to_number else None
        if line is None:
            logger.warning("Inbound call to an unknown number; closing the room")
            await transport.close_room(room)
            return None
        await set_tenant_context(session, line.tenant_id)
        existing = await session.scalar(
            select(Call.id).where(Call.tenant_id == line.tenant_id, Call.room == room)
        )
        if existing is not None:
            return existing  # a retried webhook: the agent was already sent
        agents = AgentService(session, line.tenant_id)
        agent = None
        if line.agent_id is not None:
            agent = await session.scalar(
                select(Agent).where(Agent.id == line.agent_id, Agent.tenant_id == line.tenant_id)
            )
        agent = agent or await agents.default_agent()
        lead_id = None
        if from_number is not None:
            lead_id = await session.scalar(
                select(Lead.id)
                .where(
                    Lead.tenant_id == line.tenant_id,
                    Lead.status == LeadStatus.ACTIVE,
                    Lead.phone.in_(lookup_variants(from_number)),
                )
                .order_by(Lead.created_at)
                .limit(1)
            )
        call = Call(
            id=uuid.uuid4(),
            tenant_id=line.tenant_id,
            agent_id=agent.id,
            lead_id=lead_id,
            channel=CallChannel.PHONE,
            status=CallStatus.CREATED,
            sales_state=SalesState.NEW,
            room=room,
            direction=CallDirection.INBOUND,
            to_number=to_number,
            from_number=from_number,
            dial_status=DialStatus.ANSWERED,
            phone_number_id=line.phone_number_id,
        )
        session.add(call)
        await session.commit()
        metadata = dispatch.metadata(call)
    await transport.dispatch_agent(room=room, agent_name=dispatch.agent_name, metadata=metadata)
    return call.id


async def close_call_for_room(database: Database, *, room: str) -> uuid.UUID | None:
    """Safety net when a room ends: a call still open is closed (failed if it never began)."""
    async with database.sessionmaker() as session:
        row = (
            await session.execute(
                text("SELECT call_id, tenant_id FROM resolve_call_room(:room)"), {"room": room}
            )
        ).first()
        await session.commit()
        if row is None:
            return None
        call_id: uuid.UUID = row[0]
        tenant_id: uuid.UUID = row[1]
        await set_tenant_context(session, tenant_id)
        calls = CallService(session, tenant_id)
        call = await calls.get(call_id)
        if call.status in (CallStatus.COMPLETED, CallStatus.FAILED):
            return call_id
        never_started = call.status == CallStatus.CREATED
        await calls.end(call_id, "room_closed", failed=never_started)
        return call_id
