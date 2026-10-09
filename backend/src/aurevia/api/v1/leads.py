"""Leads and what Aurevia remembers about them (signed-in users of the lead's tenant)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from aurevia.campaigns.queue import add_leads
from aurevia.campaigns.service import CampaignService
from aurevia.db.session import set_tenant_context
from aurevia.identity.dependencies import LeadsManageDep, PrincipalDep, SessionDep
from aurevia.memory.importer import import_leads
from aurevia.memory.models import Lead, LeadMemory
from aurevia.memory.schemas import (
    LeadImportIn,
    LeadImportResult,
    LeadIn,
    LeadResponse,
    MemoryResponse,
)
from aurevia.memory.service import LeadFields, LeadService, MemoryService

router = APIRouter(prefix="/leads", tags=["leads"])


def _lead(lead: Lead) -> LeadResponse:
    return LeadResponse.model_validate(lead, from_attributes=True)


def _memory(memory: LeadMemory) -> MemoryResponse:
    return MemoryResponse.model_validate(memory, from_attributes=True)


def _fields(body: LeadIn) -> LeadFields:
    return LeadFields(
        name=body.name,
        phone=body.phone,
        email=str(body.email).lower() if body.email else None,
        company=body.company,
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a lead")
async def create_lead(body: LeadIn, principal: LeadsManageDep, session: SessionDep) -> LeadResponse:
    lead = await LeadService(session, principal.tenant_id).create(_fields(body), principal.user_id)
    return _lead(lead)


@router.post("/import", summary="Create leads from CSV (name, phone, email, company)")
async def import_leads_csv(
    body: LeadImportIn, principal: LeadsManageDep, session: SessionDep
) -> LeadImportResult:
    campaign = None
    if body.campaign_id is not None:  # check before creating anything
        campaign = await CampaignService(session, principal.tenant_id).get(body.campaign_id)
    result = await import_leads(session, principal.tenant_id, body.csv, principal.user_id)
    added = 0
    if campaign is not None and result.lead_ids:
        await set_tenant_context(session, principal.tenant_id)  # the import committed
        added = await add_leads(session, principal.tenant_id, campaign, result.lead_ids)
    return LeadImportResult(
        created=len(result.lead_ids), added_to_campaign=added, errors=result.errors
    )


@router.get("", summary="List leads")
async def list_leads(
    principal: PrincipalDep,
    session: SessionDep,
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[LeadResponse]:
    leads = await LeadService(session, principal.tenant_id).list(
        include_archived=include_archived, limit=limit
    )
    return [_lead(lead) for lead in leads]


@router.get("/{lead_id}", summary="Get a lead")
async def get_lead(
    lead_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> LeadResponse:
    return _lead(await LeadService(session, principal.tenant_id).get(lead_id))


@router.put("/{lead_id}", summary="Update a lead")
async def update_lead(
    lead_id: uuid.UUID, body: LeadIn, principal: LeadsManageDep, session: SessionDep
) -> LeadResponse:
    lead = await LeadService(session, principal.tenant_id).update(
        lead_id, _fields(body), principal.user_id
    )
    return _lead(lead)


@router.get("/{lead_id}/memories", summary="What Aurevia remembers about this lead")
async def list_memories(
    lead_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[MemoryResponse]:
    await LeadService(session, principal.tenant_id).get(lead_id)  # 404 if not this tenant's
    memories = await MemoryService(session, principal.tenant_id).list(lead_id)
    return [_memory(m) for m in memories]


@router.delete(
    "/{lead_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget one remembered fact (correction)",
)
async def delete_memory(
    lead_id: uuid.UUID, memory_id: uuid.UUID, principal: LeadsManageDep, session: SessionDep
) -> Response:
    await MemoryService(session, principal.tenant_id).delete(lead_id, memory_id, principal.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
