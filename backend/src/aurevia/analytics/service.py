"""Analytics (Phase 8): activity, sales outcomes, AI quality and economics for a period.

All figures come from records the platform already keeps (calls, tool executions,
appointments, handoffs, turn metrics, usage). Nothing is estimated. A ratio is ``None`` when
its denominator is zero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.sales.models import Appointment, Followup, Handoff, ToolExecution, ToolStatus
from aurevia.usage.costs import cost_summary
from aurevia.voice.metrics import summarize
from aurevia.voice.models import Call, CallChannel, CallStatus, DialStatus


def _ratio(part: int | float, whole: int | float) -> float | None:
    return round(part / whole, 4) if whole else None


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime
    campaign_id: uuid.UUID | None = None


class AnalyticsService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def _calls(self, period: Period) -> list[Any]:
        filters = [
            Call.tenant_id == self._tenant_id,
            Call.created_at >= period.start,
            Call.created_at < period.end,
        ]
        if period.campaign_id is not None:
            filters.append(Call.campaign_id == period.campaign_id)
        return filters

    def _call_ids(self, period: Period) -> Select[Any]:
        return select(Call.id).where(*self._calls(period))

    async def summary(self, period: Period) -> dict[str, Any]:
        s, tenant = self._session, self._tenant_id
        calls = self._calls(period)

        by_status = dict(
            (await s.execute(select(Call.status, func.count()).where(*calls).group_by(Call.status)))
            .tuples()
            .all()
        )
        by_channel = dict(
            (
                await s.execute(
                    select(Call.channel, func.count()).where(*calls).group_by(Call.channel)
                )
            )
            .tuples()
            .all()
        )
        total = sum(by_status.values())
        phone_dialed = await s.scalar(
            select(func.count()).where(*calls, Call.channel == CallChannel.PHONE)
        )
        answered = await s.scalar(
            select(func.count()).where(
                *calls, Call.channel == CallChannel.PHONE, Call.dial_status == DialStatus.ANSWERED
            )
        )
        connected = await s.scalar(select(func.count()).where(*calls, Call.started_at.is_not(None)))
        avg_seconds = await s.scalar(
            select(func.avg(func.extract("epoch", Call.ended_at - Call.started_at))).where(
                *calls, Call.started_at.is_not(None), Call.ended_at.is_not(None)
            )
        )
        avg_turns = await s.scalar(
            select(func.avg(Call.turn_count)).where(*calls, Call.started_at.is_not(None))
        )

        in_calls = self._call_ids(period)

        async def count(model: Any, *where: Any) -> int:
            value = await s.scalar(
                select(func.count())
                .select_from(model)
                .where(model.tenant_id == tenant, model.call_id.in_(in_calls), *where)
            )
            return int(value or 0)

        tool_total = await count(ToolExecution)
        tool_failed = await count(ToolExecution, ToolExecution.status == ToolStatus.FAILED)
        tool_rejected = await count(ToolExecution, ToolExecution.status == ToolStatus.REJECTED)

        async def tool_ok(name: str) -> int:
            return await count(
                ToolExecution, ToolExecution.tool == name, ToolExecution.status == ToolStatus.OK
            )

        meetings = await count(Appointment)
        handoffs = await count(Handoff)
        followups = await count(Followup)
        interested = await tool_ok("mark_interested")
        not_interested = await tool_ok("mark_not_interested")
        dnc_requests = await tool_ok("request_do_not_call")

        latency = await summarize(s, tenant_id=tenant, since=period.start)
        costs = await cost_summary(
            s, tenant, start=period.start, end=period.end, campaign_id=period.campaign_id
        )

        def per(amounts: dict[str, Decimal], n: int) -> dict[str, str] | None:
            if not n:
                return None
            return {cur: str((amt / n).quantize(Decimal("0.0001"))) for cur, amt in amounts.items()}

        return {
            "period": {
                "start": period.start,
                "end": period.end,
                "campaign_id": period.campaign_id,
            },
            "activity": {
                "calls": total,
                "by_status": by_status,
                "by_channel": by_channel,
                "connected": int(connected or 0),
                "completed": by_status.get(CallStatus.COMPLETED, 0),
                "failed": by_status.get(CallStatus.FAILED, 0),
                "phone_answer_rate": _ratio(int(answered or 0), int(phone_dialed or 0)),
                "avg_call_seconds": round(float(avg_seconds), 1) if avg_seconds else None,
                "avg_turns": round(float(avg_turns), 1) if avg_turns else None,
            },
            "sales": {
                "meetings_booked": meetings,
                "followups_scheduled": followups,
                "interested": interested,
                "not_interested": not_interested,
                "handoffs": handoffs,
                "do_not_call_requests": dnc_requests,
                "meetings_per_connected_call": _ratio(meetings, int(connected or 0)),
            },
            "ai_quality": {
                "latency_p50_ms": latency.e2e_p50_ms,
                "latency_p95_ms": latency.e2e_p95_ms,
                "latency_target_met": latency.meets_target,
                "interrupted_turn_rate": _ratio(latency.interrupted_turns, latency.agent_turns),
                "tool_calls": tool_total,
                "tool_failure_rate": _ratio(tool_failed, tool_total),
                "tool_rejection_rate": _ratio(tool_rejected, tool_total),
                "escalations": handoffs,
                "latency_scope": "tenant",  # turn metrics are not split by campaign
            },
            "economics": {
                "cost": {cur: str(amt) for cur, amt in costs.totals.items()},
                "fully_priced": costs.fully_priced,
                "cost_per_call": per(costs.totals, total),
                "cost_per_meeting": per(costs.totals, meetings),
            },
        }
