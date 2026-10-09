"""Leads, transcripts and lead memory. Every query is tenant-scoped (RLS + explicit filter)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.memory.models import (
    ConversationMessage,
    Lead,
    LeadMemory,
    LeadStatus,
    MemoryKind,
    Speaker,
)


@dataclass(frozen=True)
class LeadFields:
    name: str
    phone: str | None
    email: str | None
    company: str | None


@dataclass(frozen=True)
class Line:
    seq: int
    speaker: Speaker
    text: str


@dataclass(frozen=True)
class ExtractedFact:
    kind: MemoryKind
    fact: str
    confidence: float


class LeadService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create(self, fields: LeadFields, actor: uuid.UUID) -> Lead:
        lead = Lead(tenant_id=self._tenant_id, status=LeadStatus.ACTIVE, **fields.__dict__)
        self._session.add(lead)
        await self._session.flush()
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="lead.created",
            target_type="lead",
            target_id=lead.id,
        )
        await self._session.commit()
        return lead

    async def get(self, lead_id: uuid.UUID) -> Lead:
        lead = await self._session.scalar(
            select(Lead).where(Lead.id == lead_id, Lead.tenant_id == self._tenant_id)
        )
        if lead is None:
            raise NotFoundError("Lead not found")
        return lead

    async def list(self, *, include_archived: bool = False, limit: int = 100) -> Sequence[Lead]:
        query = select(Lead).where(Lead.tenant_id == self._tenant_id)
        if not include_archived:
            query = query.where(Lead.status == LeadStatus.ACTIVE)
        return (
            await self._session.scalars(query.order_by(Lead.created_at.desc()).limit(limit))
        ).all()

    async def update(self, lead_id: uuid.UUID, fields: LeadFields, actor: uuid.UUID) -> Lead:
        lead = await self.get(lead_id)
        lead.name, lead.phone, lead.email, lead.company = (
            fields.name,
            fields.phone,
            fields.email,
            fields.company,
        )
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="lead.updated",
            target_type="lead",
            target_id=lead.id,
        )
        await self._session.commit()
        return lead


class TranscriptService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def save(self, call_id: uuid.UUID, lines: Sequence[Line], retention_days: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(days=retention_days)
        self._session.add_all(
            ConversationMessage(
                tenant_id=self._tenant_id,
                call_id=call_id,
                seq=line.seq,
                speaker=line.speaker,
                text=line.text,
                expires_at=expires_at,
            )
            for line in lines
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("Transcript already saved", code="duplicate_seq") from exc

    async def for_call(self, call_id: uuid.UUID) -> list[Line]:
        rows = await self._session.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.tenant_id == self._tenant_id,
                ConversationMessage.call_id == call_id,
            )
            .order_by(ConversationMessage.seq)
        )
        return [Line(seq=r.seq, speaker=Speaker(r.speaker), text=r.text) for r in rows]


class MemoryService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def for_prompt(
        self, lead_id: uuid.UUID, *, min_confidence: float, limit: int
    ) -> list[LeadMemory]:
        """The most recent confident facts, oldest first so the prompt reads chronologically."""
        rows = await self._session.scalars(
            select(LeadMemory)
            .where(
                LeadMemory.tenant_id == self._tenant_id,
                LeadMemory.lead_id == lead_id,
                LeadMemory.confidence >= min_confidence,
            )
            .order_by(LeadMemory.created_at.desc())
            .limit(limit)
        )
        return list(reversed(rows.all()))

    async def list(self, lead_id: uuid.UUID) -> Sequence[LeadMemory]:
        return (
            await self._session.scalars(
                select(LeadMemory)
                .where(LeadMemory.tenant_id == self._tenant_id, LeadMemory.lead_id == lead_id)
                .order_by(LeadMemory.created_at)
            )
        ).all()

    async def add(
        self,
        *,
        lead_id: uuid.UUID,
        source_call_id: uuid.UUID,
        facts: Sequence[ExtractedFact],
        extractor: str,
    ) -> int:
        self._session.add_all(
            LeadMemory(
                tenant_id=self._tenant_id,
                lead_id=lead_id,
                source_call_id=source_call_id,
                kind=fact.kind,
                fact=fact.fact,
                confidence=fact.confidence,
                extractor=extractor,
            )
            for fact in facts
        )
        await self._session.commit()
        return len(facts)

    async def delete(self, lead_id: uuid.UUID, memory_id: uuid.UUID, actor: uuid.UUID) -> None:
        memory = await self._session.scalar(
            select(LeadMemory).where(
                LeadMemory.id == memory_id,
                LeadMemory.lead_id == lead_id,
                LeadMemory.tenant_id == self._tenant_id,
            )
        )
        if memory is None:
            raise NotFoundError("Memory not found")
        await self._session.delete(memory)
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="lead_memory.deleted",
            target_type="lead_memory",
            target_id=memory_id,
            details={"lead_id": str(lead_id), "kind": memory.kind},
        )
        await self._session.commit()


async def purge_expired_transcripts(session: AsyncSession) -> int:
    """Delete transcript lines past their retention date, across all tenants."""
    removed = await session.scalar(text("SELECT purge_expired_transcripts()"))
    await session.commit()
    return int(removed or 0)
