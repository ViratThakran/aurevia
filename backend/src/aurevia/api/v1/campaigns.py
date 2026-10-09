"""Campaigns (minimal, Phase 7): limits the compliance gate enforces on their calls."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response, status
from sqlalchemy import select

from aurevia.campaigns.models import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from aurevia.campaigns.queue import add_leads, call_next
from aurevia.campaigns.schemas import (
    CallNextResponse,
    CampaignIn,
    CampaignLeadResponse,
    CampaignLeadsAdded,
    CampaignLeadsIn,
    CampaignResponse,
    CampaignStatusIn,
    CampaignUpdate,
)
from aurevia.campaigns.service import CampaignService
from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.dependencies import CallsDep, CampaignsDep, PrincipalDep, SessionDep
from aurevia.memory.models import Lead
from aurevia.telephony.outbound import outbound_deps

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _campaign(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a campaign (owner/admin)")
async def create_campaign(
    body: CampaignIn, principal: CampaignsDep, session: SessionDep
) -> CampaignResponse:
    campaign = await CampaignService(session, principal.tenant_id).create(body, principal.user_id)
    return _campaign(campaign)


@router.get("", summary="List campaigns")
async def list_campaigns(principal: PrincipalDep, session: SessionDep) -> list[CampaignResponse]:
    return [_campaign(c) for c in await CampaignService(session, principal.tenant_id).list()]


@router.get("/{campaign_id}", summary="One campaign")
async def get_campaign(
    campaign_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CampaignResponse:
    return _campaign(await CampaignService(session, principal.tenant_id).get(campaign_id))


@router.patch("/{campaign_id}", summary="Change a campaign's limits (owner/admin)")
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignUpdate, principal: CampaignsDep, session: SessionDep
) -> CampaignResponse:
    campaign = await CampaignService(session, principal.tenant_id).update(
        campaign_id, body, principal.user_id
    )
    return _campaign(campaign)


@router.post("/{campaign_id}/status", summary="Start, pause or end a campaign (owner/admin)")
async def set_campaign_status(
    campaign_id: uuid.UUID, body: CampaignStatusIn, principal: CampaignsDep, session: SessionDep
) -> CampaignResponse:
    campaign = await CampaignService(session, principal.tenant_id).set_status(
        campaign_id, CampaignStatus(body.status), principal.user_id
    )
    return _campaign(campaign)


# --- Lead list and queue (Phase 8) ---------------------------------------------------------


@router.post("/{campaign_id}/leads", summary="Add leads to the campaign's queue")
async def add_campaign_leads(
    campaign_id: uuid.UUID, body: CampaignLeadsIn, principal: CampaignsDep, session: SessionDep
) -> CampaignLeadsAdded:
    campaign = await CampaignService(session, principal.tenant_id).get(campaign_id)
    added = await add_leads(session, principal.tenant_id, campaign, body.lead_ids)
    return CampaignLeadsAdded(added=added)


@router.get("/{campaign_id}/leads", summary="The campaign's leads and where they are")
async def list_campaign_leads(
    campaign_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[CampaignLeadResponse]:
    await CampaignService(session, principal.tenant_id).get(campaign_id)  # 404 if not ours
    query = (
        select(CampaignLead, Lead.name)
        .join(Lead, Lead.id == CampaignLead.lead_id)
        .where(
            CampaignLead.tenant_id == principal.tenant_id,
            CampaignLead.campaign_id == campaign_id,
        )
    )
    if status_filter:
        query = query.where(CampaignLead.status == status_filter)
    rows = await session.execute(query.order_by(CampaignLead.next_attempt_at).limit(limit))
    return [
        CampaignLeadResponse(
            lead_id=entry.lead_id,
            lead_name=name,
            status=entry.status,
            attempts=entry.attempts,
            next_attempt_at=entry.next_attempt_at,
            last_result=entry.last_result,
            last_call_id=entry.last_call_id,
        )
        for entry, name in rows.tuples()
    ]


@router.delete(
    "/{campaign_id}/leads/{lead_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Take a lead off the campaign (not while it is being called)",
)
async def remove_campaign_lead(
    campaign_id: uuid.UUID, lead_id: uuid.UUID, principal: CampaignsDep, session: SessionDep
) -> Response:
    entry = await session.scalar(
        select(CampaignLead).where(
            CampaignLead.tenant_id == principal.tenant_id,
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.lead_id == lead_id,
        )
    )
    if entry is None:
        raise NotFoundError("Lead is not in this campaign")
    if entry.status == CampaignLeadStatus.CALLING:
        raise ConflictError("This lead is being called right now", code="lead_being_called")
    await session.delete(entry)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{campaign_id}/call-next", summary="Call the next due lead in the campaign")
async def call_next_lead(
    campaign_id: uuid.UUID,
    request: Request,
    principal: CallsDep,
    session: SessionDep,
    background: BackgroundTasks,
) -> CallNextResponse:
    deps = outbound_deps(request.app.state)
    campaign = await CampaignService(session, principal.tenant_id).get(campaign_id)
    result = await call_next(
        session,
        deps,
        tenant_id=principal.tenant_id,
        campaign=campaign,
        requested_by=principal.user_id,
        schedule=lambda job: background.add_task(job),
    )
    return CallNextResponse(
        status=result.status,
        lead_id=result.lead_id,
        call_id=result.call_id,
        reasons=list(result.reasons),
    )
