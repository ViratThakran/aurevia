"""Analytics, usage and cost, and the tenant's plan limits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from aurevia.analytics.service import AnalyticsService, Period
from aurevia.identity.dependencies import AnalyticsDep, SessionDep, SettingsDep
from aurevia.platform.limits import limits_for, month_start, usage_this_month
from aurevia.usage.costs import cost_summary

router = APIRouter(tags=["analytics"])


@router.get("/analytics/summary", summary="Activity, sales, AI quality and cost for a period")
async def analytics_summary(
    principal: AnalyticsDep,
    session: SessionDep,
    days: int = Query(default=30, ge=1, le=366),
    campaign_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    end = datetime.now(UTC)
    summary = await AnalyticsService(session, principal.tenant_id).summary(
        Period(start=end - timedelta(days=days), end=end, campaign_id=campaign_id)
    )
    encoded: dict[str, Any] = jsonable_encoder(summary)
    return encoded


@router.get("/usage", summary="This month's usage and cost against the plan's limits")
async def usage(
    principal: AnalyticsDep, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    now = datetime.now(UTC)
    limits = await limits_for(session, principal.tenant_id, settings)
    used = await usage_this_month(session, principal.tenant_id, limits, now)
    costs = await cost_summary(session, principal.tenant_id, start=month_start(now), end=now)
    encoded: dict[str, Any] = jsonable_encoder(
        {
            "month_start": month_start(now),
            "plan": limits,
            "used": used,
            "resources": [
                {
                    "resource": r.resource.value,
                    "quantity": str(r.quantity),
                    "unpriced_quantity": str(r.unpriced_quantity),
                    "cost": {cur: str(amount) for cur, amount in r.cost.items()},
                }
                for r in costs.resources
            ],
            "cost": {cur: str(amount) for cur, amount in costs.totals.items()},
            "fully_priced": costs.fully_priced,
        }
    )
    return encoded
