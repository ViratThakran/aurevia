"""Per-turn voice latency, as measured by the voice runtime. Timings only: no transcript text
(saving what was said is Phase 4, with its own consent and retention rules)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ColumnElement,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, UUIDPrimaryKey, one_of

# Phase 3 targets (agreed 2026-10-05): prospect stops speaking -> agent's first audio.
E2E_TARGET_P50_MS = 1000
E2E_TARGET_P95_MS = 1800


class TurnRole(StrEnum):
    PROSPECT = "prospect"
    AGENT = "agent"


class TurnMetric(UUIDPrimaryKey, Base):
    __tablename__ = "turn_metrics"
    __table_args__ = (
        CheckConstraint(one_of("role", TurnRole), name="role"),
        UniqueConstraint("call_id", "seq"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # order within the call
    role: Mapped[str] = mapped_column(String(20))
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Prospect turns: speech end -> transcript, and speech end -> turn judged complete.
    transcription_delay_ms: Mapped[int | None] = mapped_column(Integer)
    end_of_turn_delay_ms: Mapped[int | None] = mapped_column(Integer)
    # Agent turns: speech end -> agent audio (the target), and its model / TTS components.
    e2e_latency_ms: Mapped[int | None] = mapped_column(Integer)
    llm_ttft_ms: Mapped[int | None] = mapped_column(Integer)
    tts_ttfb_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


@dataclass(frozen=True)
class LatencySummary:
    agent_turns: int
    measured_turns: int
    interrupted_turns: int
    e2e_p50_ms: int | None
    e2e_p95_ms: int | None
    llm_ttft_p50_ms: int | None
    tts_ttfb_p50_ms: int | None
    end_of_turn_delay_p50_ms: int | None
    target_p50_ms: int = E2E_TARGET_P50_MS
    target_p95_ms: int = E2E_TARGET_P95_MS

    @property
    def meets_target(self) -> bool | None:
        if self.e2e_p50_ms is None or self.e2e_p95_ms is None:
            return None
        return self.e2e_p50_ms < self.target_p50_ms and self.e2e_p95_ms < self.target_p95_ms


def _pct(column: Any, fraction: float) -> ColumnElement[Any]:
    return func.percentile_cont(fraction).within_group(column)


async def summarize(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID | None = None,
    since: datetime | None = None,
) -> LatencySummary:
    """Latency percentiles for one call, or for every call of the tenant since ``since``."""
    agent = TurnMetric.role == TurnRole.AGENT
    prospect = TurnMetric.role == TurnRole.PROSPECT
    filters = [TurnMetric.tenant_id == tenant_id]
    if call_id is not None:
        filters.append(TurnMetric.call_id == call_id)
    if since is not None:
        filters.append(TurnMetric.created_at >= since)

    agent_row = (
        await session.execute(
            select(
                func.count(),
                func.count(TurnMetric.e2e_latency_ms),
                func.count().filter(TurnMetric.interrupted.is_(True)),
                _pct(TurnMetric.e2e_latency_ms, 0.5),
                _pct(TurnMetric.e2e_latency_ms, 0.95),
                _pct(TurnMetric.llm_ttft_ms, 0.5),
                _pct(TurnMetric.tts_ttfb_ms, 0.5),
            ).where(agent, *filters)
        )
    ).one()
    eot = await session.scalar(
        select(_pct(TurnMetric.end_of_turn_delay_ms, 0.5)).where(prospect, *filters)
    )

    def ms(value: Any) -> int | None:
        return None if value is None else round(float(value))

    return LatencySummary(
        agent_turns=int(agent_row[0]),
        measured_turns=int(agent_row[1]),
        interrupted_turns=int(agent_row[2]),
        e2e_p50_ms=ms(agent_row[3]),
        e2e_p95_ms=ms(agent_row[4]),
        llm_ttft_p50_ms=ms(agent_row[5]),
        tts_ttfb_p50_ms=ms(agent_row[6]),
        end_of_turn_delay_p50_ms=ms(eot),
    )
