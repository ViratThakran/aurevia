"""Consent records, the do-not-call list and the gate's decision history."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.encoders import jsonable_encoder

from aurevia.compliance.gate import effective_policy_json
from aurevia.compliance.models import ComplianceDecision, Consent, DoNotCallEntry, DoNotCallReason
from aurevia.compliance.policy_service import PolicyService
from aurevia.compliance.privacy import PrivacyService
from aurevia.compliance.schemas import (
    ComplianceSettingsIn,
    ComplianceSettingsResponse,
    ConsentIn,
    ConsentResponse,
    DecisionResponse,
    DoNotCallIn,
    DoNotCallResponse,
    ErasureIn,
    ErasureResponse,
    PolicyVersionResponse,
)
from aurevia.compliance.service import ConsentService, DecisionService, DoNotCallService
from aurevia.db.session import set_tenant_context
from aurevia.identity.audit import record_audit_event
from aurevia.identity.dependencies import (
    ComplianceDep,
    LeadsManageDep,
    PrincipalDep,
    PrivacyDep,
    SessionDep,
    SettingsDep,
)
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
    lead_id: uuid.UUID, body: ConsentIn, principal: LeadsManageDep, session: SessionDep
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
    lead_id: uuid.UUID, consent_id: uuid.UUID, principal: LeadsManageDep, session: SessionDep
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


# --- Policy versions and the tenant's settings (Phase 7) ----------------------------------


@router.get("/compliance/policy-versions", summary="Policy versions of the configured pack")
async def list_policy_versions(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> list[PolicyVersionResponse]:
    versions = await PolicyService(session, principal.tenant_id).versions(
        settings.compliance_policy_pack
    )
    return [PolicyVersionResponse.model_validate(v, from_attributes=True) for v in versions]


async def _settings_response(service: PolicyService, pack: str) -> ComplianceSettingsResponse:
    current = await service.settings()
    return ComplianceSettingsResponse(
        policy_version_id=current.policy_version_id if current else None,
        overrides=current.overrides if current else {},
        effective_policy=effective_policy_json(await service.effective_pack(pack)),
    )


@router.get("/compliance/settings", summary="The policy this tenant's calls are checked against")
async def get_compliance_settings(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> ComplianceSettingsResponse:
    service = PolicyService(session, principal.tenant_id)
    return await _settings_response(service, settings.compliance_policy_pack)


@router.put(
    "/compliance/settings",
    summary="Pin a policy version and tighten its rules (owner/admin; stricter only)",
)
async def update_compliance_settings(
    body: ComplianceSettingsIn, principal: ComplianceDep, session: SessionDep, settings: SettingsDep
) -> ComplianceSettingsResponse:
    service = PolicyService(session, principal.tenant_id)
    await service.update_settings(
        settings.compliance_policy_pack,
        policy_version_id=body.policy_version_id,
        overrides=body.overrides,
        actor=principal.user_id,
    )
    await set_tenant_context(session, principal.tenant_id)  # the update committed
    return await _settings_response(service, settings.compliance_policy_pack)


# --- Data-principal rights (DPDP) ---------------------------------------------------------


@router.post(
    "/leads/{lead_id}/erase",
    status_code=status.HTTP_201_CREATED,
    summary="Erase a person's data on their request (owner/admin)",
)
async def erase_lead(
    lead_id: uuid.UUID, body: ErasureIn, principal: PrivacyDep, session: SessionDep
) -> ErasureResponse:
    request = await PrivacyService(session, principal.tenant_id).erase_lead(
        lead_id, received_via=body.received_via, actor=principal.user_id
    )
    return ErasureResponse.model_validate(request, from_attributes=True)


@router.get("/leads/{lead_id}/export", summary="Everything held about a person (owner/admin)")
async def export_lead(
    lead_id: uuid.UUID, principal: PrivacyDep, session: SessionDep
) -> dict[str, Any]:
    data = await PrivacyService(session, principal.tenant_id).export_lead(
        lead_id, actor=principal.user_id
    )
    encoded: dict[str, Any] = jsonable_encoder(data)
    return encoded
