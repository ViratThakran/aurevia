"""Usage quantities and their cost (Phase 8), from usage events and versioned prices.

Each usage event is priced with the newest price that was already effective when the usage
happened (a model-specific price beats ``*``). Usage without a matching price is reported as
unpriced: no price is ever guessed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.platform.models import PriceResource

_QUERY = """
SELECT r.resource, p.currency,
       sum(r.qty) AS quantity,
       sum(r.qty * p.amount / p.per_quantity) AS cost
FROM usage_events u
CROSS JOIN LATERAL (VALUES
    ('llm_input_tokens',  CASE WHEN u.kind = 'llm' THEN u.input_tokens::numeric END),
    ('llm_output_tokens', CASE WHEN u.kind = 'llm' THEN u.output_tokens::numeric END),
    ('stt_seconds',       CASE WHEN u.kind = 'stt' THEN u.audio_seconds::numeric END),
    ('tts_characters',    CASE WHEN u.kind = 'tts' THEN u.characters::numeric END),
    ('telephony_seconds', CASE WHEN u.kind = 'telephony' THEN u.audio_seconds::numeric END)
) AS r(resource, qty)
LEFT JOIN LATERAL (
    SELECT pr.amount, pr.per_quantity, pr.currency FROM prices pr
    WHERE pr.provider = u.provider AND pr.resource = r.resource
      AND pr.model IN (coalesce(u.served_model, u.model), '*')
      AND pr.effective_from <= u.created_at
    ORDER BY (pr.model = '*'), pr.effective_from DESC
    LIMIT 1
) AS p ON true
WHERE u.tenant_id = :tenant AND u.created_at >= :start AND u.created_at < :end
  AND r.qty > 0 {campaign_filter}
GROUP BY r.resource, p.currency
"""
_CAMPAIGN_FILTER = (
    "AND u.call_id IN (SELECT c.id FROM calls c "
    "WHERE c.tenant_id = :tenant AND c.campaign_id = :campaign)"
)


@dataclass
class ResourceUsage:
    resource: PriceResource
    quantity: Decimal = Decimal(0)
    unpriced_quantity: Decimal = Decimal(0)
    cost: dict[str, Decimal] = field(default_factory=dict)  # currency -> amount


@dataclass
class CostSummary:
    resources: list[ResourceUsage]
    totals: dict[str, Decimal]  # currency -> amount, priced usage only
    fully_priced: bool


async def cost_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    campaign_id: uuid.UUID | None = None,
) -> CostSummary:
    params: dict[str, object] = {"tenant": tenant_id, "start": start, "end": end}
    campaign_filter = ""
    if campaign_id is not None:
        campaign_filter, params["campaign"] = _CAMPAIGN_FILTER, campaign_id
    rows = (
        await session.execute(text(_QUERY.format(campaign_filter=campaign_filter)), params)
    ).all()
    by_resource = {r: ResourceUsage(resource=r) for r in PriceResource}
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for resource, currency, quantity, cost in rows:
        usage = by_resource[PriceResource(resource)]
        usage.quantity += Decimal(quantity)
        if currency is None:
            usage.unpriced_quantity += Decimal(quantity)
        else:
            amount = Decimal(cost).quantize(Decimal("0.000001"))
            usage.cost[currency] = usage.cost.get(currency, Decimal(0)) + amount
            totals[currency] += amount
    resources = list(by_resource.values())
    return CostSummary(
        resources=resources,
        totals=dict(totals),
        fully_priced=all(r.unpriced_quantity == 0 for r in resources),
    )
