"""What sales tools record (Phase 5). Every table is tenant-owned and RLS-protected.

Rows here are only ever written by validated tool executions (``tools/``), never directly by
the model.
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
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of


class ObjectionCategory(StrEnum):
    PRICE = "price"
    TIMING = "timing"
    COMPETITOR = "competitor"
    TRUST = "trust"
    NO_NEED = "no_need"
    AUTHORITY = "authority"
    OTHER = "other"


class FollowupChannel(StrEnum):
    CALL = "call"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class FollowupStatus(StrEnum):
    SCHEDULED = "scheduled"
    DONE = "done"
    CANCELLED = "cancelled"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class HandoffUrgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class HandoffStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ToolStatus(StrEnum):
    OK = "ok"  # the action happened
    REJECTED = "rejected"  # invalid input or a business rule said no; nothing happened
    FAILED = "failed"  # an error occurred; nothing happened


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LeadNote(UUIDPrimaryKey, Base):
    __tablename__ = "lead_notes"

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = _created()


class Objection(UUIDPrimaryKey, Base):
    __tablename__ = "objections"
    __table_args__ = (CheckConstraint(one_of("category", ObjectionCategory), name="category"),)

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()


class Followup(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "followups"
    __table_args__ = (
        CheckConstraint(one_of("channel", FollowupChannel), name="channel"),
        CheckConstraint(one_of("status", FollowupStatus), name="status"),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=FollowupStatus.SCHEDULED)


class SchedulingSettings(Base):
    """A tenant's bookable hours for the built-in calendar. Missing row = defaults."""

    __tablename__ = "scheduling_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64))
    work_days: Mapped[list[int]] = mapped_column(ARRAY(Integer))  # 0 = Monday
    day_start_minute: Mapped[int] = mapped_column(Integer)
    day_end_minute: Mapped[int] = mapped_column(Integer)
    slot_minutes: Mapped[int] = mapped_column(Integer)
    min_notice_minutes: Mapped[int] = mapped_column(Integer)
    horizon_days: Mapped[int] = mapped_column(Integer)


class Appointment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(one_of("status", AppointmentStatus), name="status"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        # One calendar per tenant: a booked slot cannot be booked twice, even concurrently.
        Index(
            "uq_appointments_booked_slot",
            "tenant_id",
            "starts_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=AppointmentStatus.BOOKED)


class Handoff(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        CheckConstraint(one_of("urgency", HandoffUrgency), name="urgency"),
        CheckConstraint(one_of("status", HandoffStatus), name="status"),
    )

    tenant_id: Mapped[uuid.UUID] = _tenant()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(500))
    urgency: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default=HandoffStatus.OPEN)


class ToolExecution(UUIDPrimaryKey, Base):
    """Audit trail of every tool the model asked for, and what actually happened."""

    __tablename__ = "tool_executions"
    __table_args__ = (CheckConstraint(one_of("status", ToolStatus), name="status"),)

    tenant_id: Mapped[uuid.UUID] = _tenant()
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(50))
    # Same call + tool + arguments => same key: a retried request never acts twice.
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(50))
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
