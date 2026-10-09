"""Campaigns, minimal (Phase 7): just enough for the compliance gate to enforce their limits.

Lead lists, schedules, retries and the dashboard arrive in Phase 8 on top of this table.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.compliance.policy import CallPurpose
from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"  # final


class Campaign(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(one_of("status", CampaignStatus), name="status"),
        CheckConstraint(one_of("purpose", CallPurpose), name="purpose"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start < window_end",
            name="window",
        ),
        CheckConstraint("max_attempts_per_lead BETWEEN 1 AND 10", name="attempts"),
        CheckConstraint("daily_call_cap IS NULL OR daily_call_cap >= 1", name="daily_cap"),
        CheckConstraint("retry_delay_minutes BETWEEN 5 AND 10080", name="retry_delay"),
        CheckConstraint("max_concurrent_calls BETWEEN 1 AND 5", name="concurrency"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default=CampaignStatus.DRAFT)
    # Dates are in the policy's time zone; both inclusive.
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    # Optional calling hours, which can only narrow the policy's window (the gate applies both).
    window_start: Mapped[time | None] = mapped_column(Time)
    window_end: Mapped[time | None] = mapped_column(Time)
    max_attempts_per_lead: Mapped[int] = mapped_column(Integer, default=3)
    daily_call_cap: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Phase 8 queue: retries, and the opt-in automatic dialer (off unless switched on).
    retry_delay_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    auto_dial: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class CampaignLeadStatus(StrEnum):
    QUEUED = "queued"  # waiting for its next attempt
    CALLING = "calling"  # a call is being placed or is ringing
    DONE = "done"  # answered
    FAILED = "failed"  # no answer after the campaign's attempts
    SKIPPED = "skipped"  # the gate refused for a reason that will not pass by itself


class CampaignLead(UUIDPrimaryKey, Timestamps, Base):
    """A lead in a campaign's list, and where it is in the calling queue."""

    __tablename__ = "campaign_leads"
    __table_args__ = (
        CheckConstraint(one_of("status", CampaignLeadStatus), name="status"),
        UniqueConstraint("campaign_id", "lead_id"),
        Index("ix_campaign_leads_due", "campaign_id", "status", "next_attempt_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(10), default=CampaignLeadStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL")
    )
    last_result: Mapped[str | None] = mapped_column(String(50))
