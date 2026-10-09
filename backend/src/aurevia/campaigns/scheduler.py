"""The automatic campaign dialer (Phase 8, approved 2026-10-10).

Runs only when ``AUREVIA_CAMPAIGN_SCHEDULER_ENABLED`` is on, and dials only campaigns that are
active with ``auto_dial`` switched on, of tenants that are active. Each tick it tops every such
campaign up to its ``max_concurrent_calls``. Every call goes through ``call_next``, so plan
limits and the compliance gate apply exactly as for a person clicking "call next". The
dialer has no way around them, and in test mode only the tenant's own numbers can be reached.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from aurevia.campaigns.models import Campaign, CampaignStatus
from aurevia.campaigns.queue import active_calls, call_next
from aurevia.db.session import set_tenant_context
from aurevia.platform.limits import PlanLimitError
from aurevia.telephony.outbound import OutboundDeps

logger = logging.getLogger(__name__)

# Never more calls in one tick for one campaign than this, whatever its settings say.
MAX_CALLS_PER_TICK = 5


class _Tasks:
    """Keeps dial tasks alive until they finish (asyncio holds only weak references)."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[object]] = set()

    def schedule(self, job: Callable[[], Awaitable[object]]) -> None:
        async def run() -> object:
            return await job()

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def run_campaign(
    deps: OutboundDeps, tasks: _Tasks, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> int:
    """Top one campaign up to its concurrency. Returns how many calls were placed."""
    placed = 0
    async with deps.database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        campaign = await session.get(Campaign, campaign_id)
        if campaign is None or campaign.status != CampaignStatus.ACTIVE or not campaign.auto_dial:
            return 0
        free = campaign.max_concurrent_calls - await active_calls(session, tenant_id, campaign_id)
        for _ in range(max(0, min(free, MAX_CALLS_PER_TICK))):
            try:
                result = await call_next(
                    session,
                    deps,
                    tenant_id=tenant_id,
                    campaign=campaign,
                    requested_by=None,
                    schedule=tasks.schedule,
                )
            except PlanLimitError:
                break  # the tenant's plan is used up for now
            if result.status == "empty":
                break
            if result.status == "placed":
                placed += 1
            campaign = await session.get(Campaign, campaign_id) or campaign
    return placed


async def due_campaigns(deps: OutboundDeps) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with deps.database.sessionmaker() as session:
        rows = (
            await session.execute(text("SELECT tenant_id, campaign_id FROM due_auto_campaigns()"))
        ).all()
        await session.commit()
    return [(row[0], row[1]) for row in rows]


async def tick(deps: OutboundDeps, tasks: _Tasks) -> int:
    placed = 0
    for tenant_id, campaign_id in await due_campaigns(deps):
        try:
            placed += await run_campaign(deps, tasks, tenant_id, campaign_id)
        except Exception:
            logger.exception(
                "Auto-dialing failed for a campaign",
                extra={"fields": {"campaign_id": str(campaign_id)}},
            )
    return placed


async def scheduler_loop(deps: OutboundDeps, interval_seconds: float) -> None:
    tasks = _Tasks()
    while True:
        try:
            placed = await tick(deps, tasks)
            if placed:
                logger.info("Auto-dialer placed calls", extra={"fields": {"calls": placed}})
        except Exception:
            logger.exception("Auto-dialer tick failed; will retry")
        await asyncio.sleep(interval_seconds)
