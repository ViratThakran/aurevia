"""The tenant's phone numbers (caller ids and inbound lines) and its own test numbers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.compliance.policy import CallPurpose
from aurevia.db.base import Base, Timestamps, UUIDPrimaryKey, one_of


class PhoneNumber(UUIDPrimaryKey, Timestamps, Base):
    """A number the tenant owns at its carrier. One number belongs to one tenant."""

    __tablename__ = "phone_numbers"
    __table_args__ = (
        CheckConstraint(one_of("purpose", CallPurpose), name="purpose"),
        UniqueConstraint("e164"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    e164: Mapped[str] = mapped_column(String(20))
    carrier: Mapped[str] = mapped_column(String(30))  # e.g. "exotel"
    purpose: Mapped[str] = mapped_column(String(20))
    # Recorded by the tenant; must be confirmed against the carrier before live calling.
    dlt_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    inbound_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))


class TestNumber(UUIDPrimaryKey, Base):
    """A phone the tenant's own staff use for test calls (the only numbers test mode dials)."""

    __tablename__ = "test_numbers"
    __table_args__ = (UniqueConstraint("tenant_id", "e164"),)
    __test__ = False  # not a pytest test class

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    e164: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(100))
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
