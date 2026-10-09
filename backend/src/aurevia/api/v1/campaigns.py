"""Campaigns (minimal, Phase 7): limits the compliance gate enforces on their calls."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from aurevia.campaigns.models import Campaign, CampaignStatus
from aurevia.campaigns.schemas import (
    CampaignIn,
    CampaignResponse,
    CampaignStatusIn,
    CampaignUpdate,
)
from aurevia.campaigns.service import CampaignService
from aurevia.identity.dependencies import AdminDep, PrincipalDep, SessionDep

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _campaign(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a campaign (owner/admin)")
async def create_campaign(
    body: CampaignIn, principal: AdminDep, session: SessionDep
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
    campaign_id: uuid.UUID, body: CampaignUpdate, principal: AdminDep, session: SessionDep
) -> CampaignResponse:
    campaign = await CampaignService(session, principal.tenant_id).update(
        campaign_id, body, principal.user_id
    )
    return _campaign(campaign)


@router.post("/{campaign_id}/status", summary="Start, pause or end a campaign (owner/admin)")
async def set_campaign_status(
    campaign_id: uuid.UUID, body: CampaignStatusIn, principal: AdminDep, session: SessionDep
) -> CampaignResponse:
    campaign = await CampaignService(session, principal.tenant_id).set_status(
        campaign_id, CampaignStatus(body.status), principal.user_id
    )
    return _campaign(campaign)
