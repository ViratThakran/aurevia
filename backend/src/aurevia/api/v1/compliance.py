"""Consent records, the do-not-call list and the gate's decision history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from aurevia.compliance.models import ComplianceDecision, Consent, DoNotCallEntry, DoNotCallReason
from aurevia.compliance.schemas import (
    ConsentIn,
    ConsentResponse,
    DecisionResponse,
    DoNotCallIn,
    DoNotCallResponse,
)
from aurevia.compliance.service import ConsentService, DecisionService, DoNotCallService
from aurevia.identity.audit import record_audit_event
from aurevia.identity.dependencies import PrincipalDep, SessionDep
from aurevia.memory.service import LeadService

router = APIRouter(tags=["compliance"])


def _consent(consent: Consent) -> ConsentResponse:
    return ConsentResponse.model_validate(consent, from_attributes=True)


def _dnc(entry: DoNotCallEntry) -> DoNotCallResponse:
    return DoNotCallResponse.model_validate(entry, from_attributes=True)


def _decision(decision: ComplianceDecision) -> DecisionResponse:
    return DecisionResponse.model_validate(decision, from_attributes=True)


@router.post(
    "/leads/{lead_id}/consents",
    status_code=status.HTTP_201_CREATED,
    summary="Record the lead's consent to be called",
)
async def record_consent(
    lead_id: uuid.UUID, body: ConsentIn, principal: PrincipalDep, session: SessionDep
) -> ConsentResponse:
    lead = await LeadService(session, principal.tenant_id).get(lead_id)
    consent = await ConsentService(session, principal.tenant_id).record(
        lead, body, principal.user_id
    )
    return _consent(consent)


@router.get("/leads/{lead_id}/consents", summary="The lead's consent records")
async def list_consents(
    lead_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[ConsentResponse]:
    await LeadService(session, principal.tenant_id).get(lead_id)  # 404 if not this tenant's
    consents = await ConsentService(session, principal.tenant_id).for_lead(lead_id)
    return [_consent(c) for c in consents]


@router.post("/leads/{lead_id}/consents/{consent_id}/revoke", summary="Revoke a consent")
async def revoke_consent(
    lead_id: uuid.UUID, consent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> ConsentResponse:
    consent = await ConsentService(session, principal.tenant_id).revoke(
        lead_id, consent_id, principal.user_id
    )
    return _consent(consent)


@router.post(
    "/do-not-call",
    status_code=status.HTTP_201_CREATED,
    summary="Never call this number again",
)
async def add_do_not_call(
    body: DoNotCallIn, principal: PrincipalDep, session: SessionDep
) -> DoNotCallResponse:
    entry = await DoNotCallService(session, principal.tenant_id).add(
        body.phone, DoNotCallReason(body.reason), note=body.note, actor=principal.user_id
    )
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        action="do_not_call.added",
        target_type="do_not_call",
        target_id=entry.id,
    )
    await session.commit()
    return _dnc(entry)


@router.get("/do-not-call", summary="The tenant's do-not-call list")
async def list_do_not_call(principal: PrincipalDep, session: SessionDep) -> list[DoNotCallResponse]:
    return [_dnc(e) for e in await DoNotCallService(session, principal.tenant_id).list()]


@router.get("/compliance/decisions", summary="Why calls were allowed or blocked")
async def list_decisions(
    principal: PrincipalDep,
    session: SessionDep,
    lead_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DecisionResponse]:
    decisions = await DecisionService(session, principal.tenant_id).list(
        lead_id=lead_id, limit=limit
    )
    return [_decision(d) for d in decisions]
