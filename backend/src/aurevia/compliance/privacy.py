"""Data-principal rights (DPDP): see everything held about a person; erase it on request.

Erasure keeps the legal minimum (decision 2026-10-09, to be confirmed by counsel):
- the number goes on the tenant's do-not-call list, so the person is never called again;
- compliance decisions, consent records and call metadata stay, as proof of lawful calling.

Everything else about the person goes: transcripts, remembered facts, notes, objections,
follow-ups, handoff reasons, tool arguments, and future appointments (cancelled). The lead row
stays as an anonymous stub, so the links that remain point somewhere. The deletion runs in one
SECURITY DEFINER function (``erase_lead``, migration 0007), limited to the current tenant.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.compliance.models import (
    ComplianceDecision,
    Consent,
    DoNotCallEntry,
    DoNotCallReason,
    ErasureRequest,
)
from aurevia.compliance.phone import normalize_e164
from aurevia.compliance.service import DoNotCallService
from aurevia.errors import ConflictError
from aurevia.identity.audit import record_audit_event
from aurevia.memory.models import ConversationMessage, LeadMemory
from aurevia.memory.service import LeadService
from aurevia.sales.models import Appointment, Followup, Handoff, LeadNote, Objection
from aurevia.voice.models import Call


class PrivacyService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def erase_lead(
        self, lead_id: uuid.UUID, *, received_via: str, actor: uuid.UUID
    ) -> ErasureRequest:
        lead = await LeadService(self._session, self._tenant_id).get(lead_id)
        if lead.erased_at is not None:
            raise ConflictError("This lead's data was already erased", code="lead_erased")
        phone = normalize_e164(lead.phone)
        if phone is not None:
            await DoNotCallService(self._session, self._tenant_id).add(
                phone, DoNotCallReason.ERASURE_REQUEST, actor=actor
            )
        summary: dict[str, Any] = dict(
            await self._session.scalar(text("SELECT erase_lead(:lead)"), {"lead": lead_id}) or {}
        )
        summary["added_to_do_not_call"] = phone is not None
        request = ErasureRequest(
            tenant_id=self._tenant_id,
            lead_id=lead_id,
            requested_by_user_id=actor,
            received_via=received_via,
            summary=summary,
        )
        self._session.add(request)
        await self._session.flush()
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="lead.erased",
            target_type="lead",
            target_id=lead_id,
            details={"erasure_request_id": str(request.id), **summary},
        )
        await self._session.commit()
        return request

    async def export_lead(self, lead_id: uuid.UUID, *, actor: uuid.UUID) -> dict[str, Any]:
        """Everything held about one person, for an access request."""
        lead = await LeadService(self._session, self._tenant_id).get(lead_id)
        tenant = self._tenant_id
        calls = list(
            await self._session.scalars(
                select(Call)
                .where(Call.tenant_id == tenant, Call.lead_id == lead_id)
                .order_by(Call.created_at)
            )
        )
        call_ids = [c.id for c in calls]
        lines = list(
            await self._session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.tenant_id == tenant,
                    ConversationMessage.call_id.in_(call_ids),
                )
                .order_by(ConversationMessage.call_id, ConversationMessage.seq)
            )
        )
        phone = normalize_e164(lead.phone)

        async def rows(model: Any, *conditions: Any) -> list[Any]:
            return list(
                await self._session.scalars(
                    select(model).where(model.tenant_id == tenant, *conditions)
                )
            )

        export: dict[str, Any] = {
            "lead": {
                "id": lead.id,
                "name": lead.name,
                "phone": lead.phone,
                "email": lead.email,
                "company": lead.company,
                "status": lead.status,
                "interest": lead.interest,
                "interest_reason": lead.interest_reason,
                "qualification": lead.qualification,
                "created_at": lead.created_at,
                "erased_at": lead.erased_at,
            },
            "consents": [
                _pick(
                    c,
                    "kind",
                    "purpose",
                    "source",
                    "evidence",
                    "obtained_at",
                    "expires_at",
                    "revoked_at",
                )
                for c in await rows(Consent, Consent.lead_id == lead_id)
            ],
            "remembered_facts": [
                _pick(m, "kind", "fact", "confidence", "created_at")
                for m in await rows(LeadMemory, LeadMemory.lead_id == lead_id)
            ],
            "notes": [
                _pick(n, "text", "created_at")
                for n in await rows(LeadNote, LeadNote.lead_id == lead_id)
            ],
            "objections": [
                _pick(o, "category", "detail", "created_at")
                for o in await rows(Objection, Objection.lead_id == lead_id)
            ],
            "followups": [
                _pick(f, "due_at", "channel", "note", "status")
                for f in await rows(Followup, Followup.lead_id == lead_id)
            ],
            "appointments": [
                _pick(a, "starts_at", "ends_at", "status")
                for a in await rows(Appointment, Appointment.lead_id == lead_id)
            ],
            "handoffs": [
                _pick(h, "reason", "urgency", "status", "created_at")
                for h in await rows(Handoff, Handoff.lead_id == lead_id)
            ],
            "calls": [
                {
                    **_pick(
                        c,
                        "id",
                        "channel",
                        "direction",
                        "status",
                        "to_number",
                        "from_number",
                        "started_at",
                        "ended_at",
                        "end_reason",
                    ),
                    "transcript": [
                        {"speaker": ln.speaker, "text": ln.text, "expires_at": ln.expires_at}
                        for ln in lines
                        if ln.call_id == c.id
                    ],
                }
                for c in calls
            ],
            "do_not_call": [
                _pick(d, "phone", "reason", "created_at")
                for d in (
                    await rows(DoNotCallEntry, DoNotCallEntry.phone == phone) if phone else []
                )
            ],
            "compliance_decisions": [
                _pick(d, "id", "action", "decision", "reason_code", "policy_version", "created_at")
                for d in await rows(ComplianceDecision, ComplianceDecision.lead_id == lead_id)
            ],
        }
        record_audit_event(
            self._session,
            tenant_id=tenant,
            actor_user_id=actor,
            action="lead.exported",
            target_type="lead",
            target_id=lead_id,
        )
        await self._session.commit()
        return export


def _pick(row: Any, *names: str) -> dict[str, Any]:
    return {name: getattr(row, name) for name in names}
