"""Plan limits (Phase 8 "billing boundaries"): checked before every call. No payments.

A tenant without a plan row gets the default plan from settings. Months are calendar months
in UTC. Concurrency counts calls not yet ended that started within the last two hours (so a
call whose worker died cannot block a tenant for ever).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.config import Settings
from aurevia.errors import AureviaError
from aurevia.platform.models import TenantPlan
from aurevia.usage.costs import cost_summary
from aurevia.voice.models import Call, CallStatus

STALE_CALL_AFTER = timedelta(hours=2)


class PlanLimitError(AureviaError):
    status_code = 429
    code = "plan_limit_reached"


@dataclass(frozen=True)
class PlanLimits:
    plan_name: str
    monthly_call_limit: int | None
    monthly_minute_limit: int | None
    monthly_cost_limit: Decimal | None
    cost_currency: str | None
    max_concurrent_calls: int


@dataclass(frozen=True)
class PlanUsage:
    calls: int
    minutes: float
    concurrent_calls: int
    cost: Decimal | None  # in the plan's cost currency, if it has a cost limit


def default_limits(settings: Settings) -> PlanLimits:
    return PlanLimits(
        plan_name="default",
        monthly_call_limit=settings.plan_default_monthly_calls,
        monthly_minute_limit=settings.plan_default_monthly_minutes,
        monthly_cost_limit=None,
        cost_currency=None,
        max_concurrent_calls=settings.plan_default_max_concurrent_calls,
    )


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def limits_for(session: AsyncSession, tenant_id: uuid.UUID, settings: Settings) -> PlanLimits:
    plan = await session.get(TenantPlan, tenant_id)
    if plan is None:
        return default_limits(settings)
    return PlanLimits(
        plan_name=plan.plan_name,
        monthly_call_limit=plan.monthly_call_limit,
        monthly_minute_limit=plan.monthly_minute_limit,
        monthly_cost_limit=plan.monthly_cost_limit,
        cost_currency=plan.cost_currency,
        max_concurrent_calls=plan.max_concurrent_calls,
    )


async def usage_this_month(
    session: AsyncSession, tenant_id: uuid.UUID, limits: PlanLimits, now: datetime
) -> PlanUsage:
    start = month_start(now)
    calls = await session.scalar(
        select(func.count())
        .select_from(Call)
        .where(Call.tenant_id == tenant_id, Call.created_at >= start)
    )
    seconds = await session.scalar(
        select(
            func.coalesce(
                func.sum(
                    func.extract("epoch", func.coalesce(Call.ended_at, now) - Call.started_at)
                ),
                0,
            )
        ).where(
            Call.tenant_id == tenant_id,
            Call.started_at.is_not(None),
            Call.started_at >= start,
        )
    )
    concurrent = await session.scalar(
        select(func.count())
        .select_from(Call)
        .where(
            Call.tenant_id == tenant_id,
            Call.status.in_([CallStatus.CREATED, CallStatus.IN_PROGRESS]),
            Call.created_at >= now - STALE_CALL_AFTER,
        )
    )
    cost = None
    if limits.monthly_cost_limit is not None and limits.cost_currency:
        summary = await cost_summary(session, tenant_id, start=start, end=now)
        cost = summary.totals.get(limits.cost_currency, Decimal(0))
    return PlanUsage(
        calls=int(calls or 0),
        minutes=float(seconds or 0) / 60,
        concurrent_calls=int(concurrent or 0),
        cost=cost,
    )


async def check_can_start_call(
    session: AsyncSession, tenant_id: uuid.UUID, settings: Settings, now: datetime
) -> None:
    """Raise ``PlanLimitError`` if another call would exceed the tenant's plan."""
    limits = await limits_for(session, tenant_id, settings)
    usage = await usage_this_month(session, tenant_id, limits, now)
    exceeded = []
    if limits.monthly_call_limit is not None and usage.calls >= limits.monthly_call_limit:
        exceeded.append("monthly_calls")
    if limits.monthly_minute_limit is not None and usage.minutes >= limits.monthly_minute_limit:
        exceeded.append("monthly_minutes")
    if (
        limits.monthly_cost_limit is not None
        and usage.cost is not None
        and usage.cost >= limits.monthly_cost_limit
    ):
        exceeded.append("monthly_cost")
    if usage.concurrent_calls >= limits.max_concurrent_calls:
        exceeded.append("concurrent_calls")
    if exceeded:
        raise PlanLimitError(
            "Your plan's limit has been reached",
            details={"limits": exceeded, "plan": limits.plan_name},
        )
