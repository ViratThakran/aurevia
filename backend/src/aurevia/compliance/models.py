"""Consent, the tenant's do-not-call list, and the record of every gate decision.

All tenant-owned and RLS-protected. Decisions are insert-only for the application: a record of
why a call was allowed or blocked can never be edited afterwards.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.compliance.policy import CallPurpose, ConsentKind, TelephonyMode
from aurevia.db.base import Base, UUIDPrimaryKey, one_of


class DoNotCallReason(StrEnum):
    PROSPECT_REQUEST = "prospect_request"  # the prospect asked not to be called again
    MANUAL = "manual"  # added by a team member
    COMPLAINT = "complaint"


class GateDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Consent(UUIDPrimaryKey, Base):
    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint(one_of("kind", ConsentKind), name="kind"),
        CheckConstraint(one_of("purpose", CallPurpose), name="purpose"),
        Index("ix_consents_tenant_phone", "tenant_id", "phone"),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(20))  # E.164, the number consent was given for
    kind: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(200))  # e.g. "website form", "inbound call"
    evidence: Mapped[str | None] = mapped_column(String(1000))
    obtained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class DoNotCallEntry(UUIDPrimaryKey, Base):
    __tablename__ = "do_not_call"
    __table_args__ = (
        CheckConstraint(one_of("reason", DoNotCallReason), name="reason"),
        UniqueConstraint("tenant_id", "phone"),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    phone: Mapped[str] = mapped_column(String(20))  # E.164
    reason: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(500))
    source_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class ComplianceDecision(UUIDPrimaryKey, Base):
    __tablename__ = "compliance_decisions"
    __table_args__ = (
        CheckConstraint(one_of("decision", GateDecision), name="decision"),
        CheckConstraint(one_of("mode", TelephonyMode), name="mode"),
        CheckConstraint(one_of("purpose", CallPurpose), name="purpose"),
        Index("ix_compliance_decisions_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30))  # "outbound_call"
    purpose: Mapped[str] = mapped_column(String(20))
    to_number: Mapped[str | None] = mapped_column(String(20))
    from_number: Mapped[str | None] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10))
    policy_pack: Mapped[str] = mapped_column(String(50))
    policy_version: Mapped[str] = mapped_column(String(50))
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB)  # what the checks saw
    decision: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = _created()
