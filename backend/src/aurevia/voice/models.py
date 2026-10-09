"""Agents and calls. Both are tenant-owned and protected by row-level security."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of
from aurevia.sales.state import SalesState


class CallChannel(StrEnum):
    BROWSER = "browser"
    PHONE = "phone"


class CallStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CallDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class DialStatus(StrEnum):
    """Phone leg only. ``answered`` is the only state in which the agent speaks."""

    QUEUED = "queued"
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"


class Agent(UUIDPrimaryKey, Timestamps, Base):
    """A tenant's AI sales agent: who it is, what it sells, how it opens a call.

    Every field is validated server-side before it reaches a prompt.
    """

    __tablename__ = "agents"
    __table_args__ = (
        # At most one default agent per tenant.
        Index(
            "uq_agents_default_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    company_name: Mapped[str] = mapped_column(String(200))
    company_description: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text)
    greeting: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(20))
    voice: Mapped[str | None] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Phase 8 agent setup. Empty means "not configured" and is left out of the prompt.
    personality: Mapped[str] = mapped_column(String(300), default="", server_default="")
    qualification_questions: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), default=list, server_default="{}"
    )
    objection_guidance: Mapped[str] = mapped_column(Text, default="", server_default="")
    escalation_guidance: Mapped[str] = mapped_column(Text, default="", server_default="")


class Call(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(one_of("channel", CallChannel), name="channel"),
        CheckConstraint(one_of("status", CallStatus), name="status"),
        CheckConstraint(one_of("sales_state", SalesState), name="sales_state"),
        CheckConstraint(
            f"direction IS NULL OR {one_of('direction', CallDirection)}", name="direction"
        ),
        CheckConstraint(
            f"dial_status IS NULL OR {one_of('dial_status', DialStatus)}", name="dial_status"
        ),
        # A phone call placed by us always carries the gate decision that allowed it.
        CheckConstraint(
            "direction IS DISTINCT FROM 'outbound' OR compliance_decision_id IS NOT NULL",
            name="outbound_has_decision",
        ),
        Index("ix_calls_tenant_to_number_created", "tenant_id", "to_number", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    # The prospect being called (Phase 4). Optional: ad-hoc test calls may have no lead.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=CallStatus.CREATED)
    sales_state: Mapped[str] = mapped_column(String(30), default=SalesState.NEW)
    room: Mapped[str] = mapped_column(String(100), unique=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(100))
    # Phone calls (Phase 6); all NULL for browser calls.
    direction: Mapped[str | None] = mapped_column(String(10))
    to_number: Mapped[str | None] = mapped_column(String(20))
    from_number: Mapped[str | None] = mapped_column(String(20))
    dial_status: Mapped[str | None] = mapped_column(String(20))
    provider_call_id: Mapped[str | None] = mapped_column(String(100))
    # One decision allows exactly one call.
    compliance_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_decisions.id", ondelete="RESTRICT"), unique=True
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
