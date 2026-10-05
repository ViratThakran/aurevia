"""Usage events: one row per billable unit of work. Append-only for the application role."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, UUIDPrimaryKey, one_of


class UsageKind(StrEnum):
    LLM = "llm"
    STT = "stt"
    TTS = "tts"
    TELEPHONY = "telephony"


class UsageEvent(UUIDPrimaryKey, Base):
    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint(one_of("kind", UsageKind), name="kind"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(50))
    # For LLM events: the model requested and the model that actually answered (they differ
    # when the explicit fallback policy re-ran a declined request).
    model: Mapped[str] = mapped_column(String(100))
    served_model: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    characters: Mapped[int] = mapped_column(Integer, default=0)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    provider_request_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
