"""Lists for the dashboard (Phase 8b): calls, meetings, follow-ups and handoffs.

Read by any member. Changing a follow-up or resolving a handoff needs ``leads.manage``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.identity.dependencies import LeadsManageDep, PrincipalDep, SessionDep
from aurevia.memory.models import Lead
from aurevia.sales.models import (
    Appointment,
    Followup,
    FollowupStatus,
    Handoff,
    HandoffStatus,
)
from aurevia.voice.models import Call

router = APIRouter(tags=["activity"])


class CallListItem(BaseModel):
    id: uuid.UUID
    channel: str
    direction: str | None
    status: str
    dial_status: str | None
    sales_state: str
    lead_id: uuid.UUID | None
    lead_name: str | None
    campaign_id: uuid.UUID | None
    to_number: str | None
    from_number: str | None
    turn_count: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class MeetingItem(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str
    call_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    status: str


class FollowupItem(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str
    call_id: uuid.UUID | None
    due_at: datetime
    channel: str
    note: str
    status: str


class HandoffItem(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None
    lead_name: str | None
    call_id: uuid.UUID | None
    reason: str
    urgency: str
    status: str
    created_at: datetime


class FollowupUpdate(BaseModel):
    status: Literal["done", "cancelled"]


@router.get("/voice/calls", summary="Recent calls, newest first")
async def list_calls(
    principal: PrincipalDep,
    session: SessionDep,
    lead_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[CallListItem]:
    query = (
        select(Call, Lead.name)
        .outerjoin(Lead, Lead.id == Call.lead_id)
        .where(Call.tenant_id == principal.tenant_id)
    )
    if lead_id is not None:
        query = query.where(Call.lead_id == lead_id)
    if campaign_id is not None:
        query = query.where(Call.campaign_id == campaign_id)
    rows = await session.execute(query.order_by(Call.created_at.desc()).limit(limit))
    return [
        CallListItem(
            id=c.id,
            channel=c.channel,
            direction=c.direction,
            status=c.status,
            dial_status=c.dial_status,
            sales_state=c.sales_state,
            lead_id=c.lead_id,
            lead_name=name,
            campaign_id=c.campaign_id,
            to_number=c.to_number,
            from_number=c.from_number,
            turn_count=c.turn_count,
            created_at=c.created_at,
            started_at=c.started_at,
            ended_at=c.ended_at,
            end_reason=c.end_reason,
        )
        for c, name in rows.tuples()
    ]


@router.get("/meetings", summary="Booked meetings (upcoming first)")
async def list_meetings(
    principal: PrincipalDep,
    session: SessionDep,
    include_past: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MeetingItem]:
    query = (
        select(Appointment, Lead.name)
        .join(Lead, Lead.id == Appointment.lead_id)
        .where(Appointment.tenant_id == principal.tenant_id)
    )
    if not include_past:
        query = query.where(Appointment.ends_at >= datetime.now().astimezone())
    rows = await session.execute(query.order_by(Appointment.starts_at).limit(limit))
    return [
        MeetingItem(
            id=a.id,
            lead_id=a.lead_id,
            lead_name=name,
            call_id=a.call_id,
            starts_at=a.starts_at,
            ends_at=a.ends_at,
            status=a.status,
        )
        for a, name in rows.tuples()
    ]


@router.get("/followups", summary="Follow-ups, soonest first")
async def list_followups(
    principal: PrincipalDep,
    session: SessionDep,
    status: Literal["scheduled", "done", "cancelled"] | None = "scheduled",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FollowupItem]:
    query = (
        select(Followup, Lead.name)
        .join(Lead, Lead.id == Followup.lead_id)
        .where(Followup.tenant_id == principal.tenant_id)
    )
    if status is not None:
        query = query.where(Followup.status == status)
    rows = await session.execute(query.order_by(Followup.due_at).limit(limit))
    return [
        FollowupItem(
            id=f.id,
            lead_id=f.lead_id,
            lead_name=name,
            call_id=f.call_id,
            due_at=f.due_at,
            channel=f.channel,
            note=f.note,
            status=f.status,
        )
        for f, name in rows.tuples()
    ]


@router.patch("/followups/{followup_id}", summary="Mark a follow-up done or cancelled")
async def update_followup(
    followup_id: uuid.UUID, body: FollowupUpdate, principal: LeadsManageDep, session: SessionDep
) -> dict[str, str]:
    followup = await session.scalar(
        select(Followup).where(
            Followup.id == followup_id, Followup.tenant_id == principal.tenant_id
        )
    )
    if followup is None:
        raise NotFoundError("Follow-up not found")
    if followup.status != FollowupStatus.SCHEDULED:
        raise ConflictError("Only a scheduled follow-up can change", code="followup_closed")
    followup.status = body.status
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action=f"followup.{body.status}",
        target_type="followup",
        target_id=followup.id,
    )
    await session.commit()
    return {"id": str(followup_id), "status": body.status}


@router.get("/handoffs", summary="Requests for a human colleague")
async def list_handoffs(
    principal: PrincipalDep,
    session: SessionDep,
    status: Literal["open", "resolved"] | None = "open",
    limit: int = Query(default=100, ge=1, le=500),
) -> list[HandoffItem]:
    query = (
        select(Handoff, Lead.name)
        .outerjoin(Lead, Lead.id == Handoff.lead_id)
        .where(Handoff.tenant_id == principal.tenant_id)
    )
    if status is not None:
        query = query.where(Handoff.status == status)
    rows = await session.execute(query.order_by(Handoff.created_at.desc()).limit(limit))
    return [
        HandoffItem(
            id=h.id,
            lead_id=h.lead_id,
            lead_name=name,
            call_id=h.call_id,
            reason=h.reason,
            urgency=h.urgency,
            status=h.status,
            created_at=h.created_at,
        )
        for h, name in rows.tuples()
    ]


@router.post("/handoffs/{handoff_id}/resolve", summary="Mark a handoff as handled")
async def resolve_handoff(
    handoff_id: uuid.UUID, principal: LeadsManageDep, session: SessionDep
) -> dict[str, str]:
    handoff = await session.scalar(
        select(Handoff).where(Handoff.id == handoff_id, Handoff.tenant_id == principal.tenant_id)
    )
    if handoff is None:
        raise NotFoundError("Handoff not found")
    if handoff.status != HandoffStatus.RESOLVED:
        handoff.status = HandoffStatus.RESOLVED
        record_audit_event(
            session,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            action="handoff.resolved",
            target_type="handoff",
            target_id=handoff.id,
        )
        await session.commit()
    return {"id": str(handoff_id), "status": HandoffStatus.RESOLVED}
