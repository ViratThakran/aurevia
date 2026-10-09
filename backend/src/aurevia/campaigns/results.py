"""Dial outcomes back into a campaign's queue (kept apart from ``queue.py``: the telephony
layer calls this, and ``queue.py`` calls the telephony layer)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.campaigns.models import Campaign, CampaignLead, CampaignLeadStatus
from aurevia.voice.models import Call, CallDirection, DialStatus


async def record_dial_result(
    session: AsyncSession, tenant_id: uuid.UUID, call: Call, status: DialStatus, now: datetime
) -> None:
    """Update the campaign queue after a dial (the caller commits)."""
    if call.campaign_id is None or call.lead_id is None or call.direction != CallDirection.OUTBOUND:
        return
    entry = await session.scalar(
        select(CampaignLead).where(
            CampaignLead.tenant_id == tenant_id,
            CampaignLead.campaign_id == call.campaign_id,
            CampaignLead.lead_id == call.lead_id,
        )
    )
    campaign = await session.get(Campaign, call.campaign_id)
    if entry is None or campaign is None:
        return
    entry.last_result = status.value
    if status == DialStatus.ANSWERED:
        entry.status = CampaignLeadStatus.DONE
    elif entry.attempts < campaign.max_attempts_per_lead:
        entry.status = CampaignLeadStatus.QUEUED
        entry.next_attempt_at = now + timedelta(minutes=campaign.retry_delay_minutes)
    else:
        entry.status = CampaignLeadStatus.FAILED
