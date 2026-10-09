"""Leads, call transcripts and durable lead memory (Phase 4). All tenant-owned, all RLS-protected.

Retention: transcripts expire ``transcript_retention_days`` after they are written (90 by
default) and are purged by a database function that runs on a schedule. Extracted memories
stay until the lead is deleted or someone removes them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of


class LeadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class LeadInterest(StrEnum):
    UNKNOWN = "unknown"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"


class Speaker(StrEnum):
    PROSPECT = "prospect"
    AGENT = "agent"


class MemoryKind(StrEnum):
    NEED = "need"
    OBJECTION = "objection"
    PREFERENCE = "preference"
    PROMISE = "promise"  # something the agent or company committed to
    BUSINESS = "business"  # facts about the prospect's company
    PERSONAL = "personal"  # small talk the prospect volunteered (e.g. a holiday)


class Lead(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(one_of("status", LeadStatus), name="status"),
        CheckConstraint(one_of("interest", LeadInterest), name="interest"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=LeadStatus.ACTIVE)
    # Set only by validated sales tools (Phase 5).
    interest: Mapped[str] = mapped_column(String(20), default=LeadInterest.UNKNOWN)
    interest_reason: Mapped[str | None] = mapped_column(String(500))
    qualification: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Set when the person's data was erased on request (DPDP); the row stays as a stub.
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(UUIDPrimaryKey, Base):
    """One spoken utterance. Deleted automatically at ``expires_at``."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(one_of("speaker", Speaker), name="speaker"),
        UniqueConstraint("call_id", "seq"),
        Index("ix_conversation_messages_expires_at", "expires_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeadMemory(UUIDPrimaryKey, Base):
    """A fact worth remembering about a lead, with where it came from and how sure we are."""

    __tablename__ = "lead_memories"
    __table_args__ = (
        CheckConstraint(one_of("kind", MemoryKind), name="kind"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    # Provenance: the call it was learned on. Kept when the call's transcript expires.
    source_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20))
    fact: Mapped[str] = mapped_column(String(500))
    confidence: Mapped[float] = mapped_column(Float)
    extractor: Mapped[str] = mapped_column(String(100))  # model/prompt version that wrote it
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
