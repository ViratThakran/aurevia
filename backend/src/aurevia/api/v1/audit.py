"""The tenant's tamper-evident audit log, for owners/admins and auditors."""

from __future__ import annotations

from fastapi import APIRouter, Query

from aurevia.compliance.schemas import AuditEventResponse, AuditVerifyResponse
from aurevia.identity.audit_chain import list_events, verify_chain
from aurevia.identity.dependencies import AuditDep, SessionDep

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", summary="Audit events in order, with their chain hashes (owner/admin)")
async def get_audit_events(
    principal: AuditDep,
    session: SessionDep,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditEventResponse]:
    events = await list_events(session, principal.tenant_id, after_seq=after_seq, limit=limit)
    return [AuditEventResponse.model_validate(e, from_attributes=True) for e in events]


@router.get("/verify", summary="Check that no audit event was changed or removed (owner/admin)")
async def verify_audit_log(principal: AuditDep, session: SessionDep) -> AuditVerifyResponse:
    report = await verify_chain(session, principal.tenant_id)
    return AuditVerifyResponse(
        events=report.events,
        ok=report.ok,
        first_broken_seq=report.first_broken_seq,
        head_hash=report.head_hash,
    )
