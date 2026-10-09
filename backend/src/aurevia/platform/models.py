"""Platform data (Phase 8): tenant plans (usage limits) and provider prices.

Plans are tenant-owned rows (RLS) that only platform administrators change. Prices are
platform-wide reference data. They are insert-only: a new price is a new row with a later
``effective_from``, so the cost of past usage never changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, UUIDPrimaryKey, one_of


class PriceResource(StrEnum):
    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"
    STT_SECONDS = "stt_seconds"
    TTS_CHARACTERS = "tts_characters"
    TELEPHONY_SECONDS = "telephony_seconds"


class TenantPlan(Base):
    """Usage limits for one tenant. ``None`` means unlimited. No row: the default plan."""

    __tablename__ = "tenant_plans"
    __table_args__ = (
        CheckConstraint("max_concurrent_calls BETWEEN 1 AND 100", name="concurrency"),
        CheckConstraint(
            "monthly_cost_limit IS NULL OR cost_currency IS NOT NULL", name="cost_currency"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    plan_name: Mapped[str] = mapped_column(String(50))
    monthly_call_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_minute_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_cost_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    max_concurrent_calls: Mapped[int] = mapped_column(Integer)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Price(UUIDPrimaryKey, Base):
    """``amount`` (in ``currency``) per ``per_quantity`` units of ``resource``.

    ``model`` is a specific model or voice id, or ``*`` for any.
    """

    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint(one_of("resource", PriceResource), name="resource"),
        CheckConstraint("amount >= 0 AND per_quantity > 0", name="amount"),
        Index("ix_prices_lookup", "provider", "resource", "model", "effective_from"),
    )

    provider: Mapped[str] = mapped_column(String(50))
    resource: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100), default="*")
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    per_quantity: Mapped[int] = mapped_column(BigInteger)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
