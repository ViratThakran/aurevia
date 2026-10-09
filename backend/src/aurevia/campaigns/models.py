"""Campaigns, minimal (Phase 7): just enough for the compliance gate to enforce their limits.

Lead lists, schedules, retries and the dashboard arrive in Phase 8 on top of this table.
"""

from __future__ import annotations

import uuid
from datetime import date, time
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Time
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
