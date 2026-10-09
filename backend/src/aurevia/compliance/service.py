"""Consent records, the do-not-call list and decision history, in the tenant's RLS scope."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.compliance.models import (
    ComplianceDecision,
    Consent,
    DoNotCallEntry,
    DoNotCallReason,
)
from aurevia.compliance.phone import normalize_e164
from aurevia.compliance.schemas import ConsentIn
from aurevia.errors import AureviaError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.memory.models import Lead

# Consent cannot be recorded as obtained in the future (small allowance for clock skew).
_CLOCK_SKEW = timedelta(minutes=5)


class InvalidConsentError(AureviaError):
    status_code = 422
    code = "invalid_consent"


class ConsentService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def record(self, lead: Lead, body: ConsentIn, actor: uuid.UUID) -> Consent:
        now = datetime.now(UTC)
        phone = normalize_e164(lead.phone)
        if phone is None:
            raise InvalidConsentError("The lead has no valid phone number to record consent for")
        obtained = body.obtained_at or now
        if obtained.tzinfo is None or obtained > now + _CLOCK_SKEW:
            raise InvalidConsentError("obtained_at must be a past time with a time zone")
        if body.expires_at is not None and (
            body.expires_at.tzinfo is None or body.expires_at <= obtained
        ):
            raise InvalidConsentError("expires_at must be after obtained_at, with a time zone")
        consent = Consent(
            tenant_id=self._tenant_id,
            lead_id=lead.id,
            phone=phone,
            kind=body.kind,
            purpose=body.purpose,
            source=body.source,
            evidence=body.evidence,
            obtained_at=obtained,
            expires_at=body.expires_at,
            recorded_by_user_id=actor,
        )
        self._session.add(consent)
        await self._session.flush()
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="consent.recorded",
            target_type="consent",
            target_id=consent.id,
            details={"kind": body.kind.value, "purpose": body.purpose.value},
        )
        await self._session.commit()
        return consent

    async def for_lead(self, lead_id: uuid.UUID) -> list[Consent]:
        rows = await self._session.scalars(
            select(Consent)
            .where(Consent.tenant_id == self._tenant_id, Consent.lead_id == lead_id)
            .order_by(Consent.created_at)
        )
        return list(rows)

    async def revoke(self, lead_id: uuid.UUID, consent_id: uuid.UUID, actor: uuid.UUID) -> Consent:
        consent = await self._session.scalar(
            select(Consent).where(
                Consent.id == consent_id,
                Consent.lead_id == lead_id,
                Consent.tenant_id == self._tenant_id,
            )
        )
        if consent is None:
            raise NotFoundError("Consent not found")
        if consent.revoked_at is None:
            consent.revoked_at = datetime.now(UTC)
            record_audit_event(
                self._session,
                tenant_id=self._tenant_id,
                actor_user_id=actor,
                action="consent.revoked",
                target_type="consent",
                target_id=consent.id,
            )
            await self._session.commit()
        return consent


class DoNotCallService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def add(
        self,
        phone: str,
        reason: DoNotCallReason,
        *,
        note: str | None = None,
        actor: uuid.UUID | None = None,
        source_call_id: uuid.UUID | None = None,
    ) -> DoNotCallEntry:
        """Add ``phone`` (E.164); adding a number twice keeps the first entry. Flushes only."""
        await self._session.execute(
            insert(DoNotCallEntry)
            .values(
                id=uuid.uuid4(),
                tenant_id=self._tenant_id,
                phone=phone,
                reason=reason,
                note=note,
                source_call_id=source_call_id,
                created_by_user_id=actor,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "phone"])
        )
        entry = await self._session.scalar(
            select(DoNotCallEntry).where(
                DoNotCallEntry.tenant_id == self._tenant_id, DoNotCallEntry.phone == phone
            )
        )
        assert entry is not None  # noqa: S101 - just inserted or already present
        return entry

    async def list(self) -> list[DoNotCallEntry]:
        rows = await self._session.scalars(
            select(DoNotCallEntry)
            .where(DoNotCallEntry.tenant_id == self._tenant_id)
            .order_by(DoNotCallEntry.created_at.desc())
        )
        return list(rows)


class DecisionService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def list(self, *, lead_id: uuid.UUID | None, limit: int) -> list[ComplianceDecision]:
        query = select(ComplianceDecision).where(ComplianceDecision.tenant_id == self._tenant_id)
        if lead_id is not None:
            query = query.where(ComplianceDecision.lead_id == lead_id)
        rows = await self._session.scalars(
            query.order_by(ComplianceDecision.created_at.desc()).limit(limit)
        )
        return list(rows)
