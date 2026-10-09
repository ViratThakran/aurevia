"""A campaign's calling queue (Phase 8): who to call next, retries, and outcomes.

"Call next" takes the earliest due lead (``FOR UPDATE SKIP LOCKED``, so two dialers never take
the same one) and sends it through the normal outbound path: plan limits, then the
compliance gate. A gate refusal that will pass by itself (calling hours, daily caps) puts
the lead back with a delay. Any other refusal (no consent, do-not-call...) skips the lead
for good. Dial outcomes come back through ``campaigns.results.record_dial_result``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.campaigns.models import Campaign, CampaignLead, CampaignLeadStatus, CampaignStatus
from aurevia.compliance.gate import CallBlockedError
from aurevia.compliance.policy import CallPurpose
from aurevia.db.session import set_tenant_context
from aurevia.errors import ConflictError
from aurevia.memory.models import Lead, LeadStatus
from aurevia.platform.limits import PlanLimitError
from aurevia.telephony.outbound import OutboundDeps, Schedule, place_outbound
from aurevia.voice.models import Call, CallStatus

# Gate reasons that clear by themselves: try again after the campaign's retry delay.
RETRYABLE_REASONS = frozenset(
    {
        "outside_calling_window",
        "outside_campaign_hours",
        "campaign_daily_cap_reached",
        "attempt_limit_reached",
    }
)


@dataclass(frozen=True)
class CallNextResult:
    status: str  # "placed" | "empty" | "blocked"
    lead_id: uuid.UUID | None = None
    call_id: uuid.UUID | None = None
    reasons: tuple[str, ...] = ()


async def add_leads(
    session: AsyncSession, tenant_id: uuid.UUID, campaign: Campaign, lead_ids: list[uuid.UUID]
) -> int:
    """Queue leads of this tenant (ignoring unknown, archived and already queued ones)."""
    if campaign.status == CampaignStatus.ENDED:
        raise ConflictError("An ended campaign cannot change", code="campaign_ended")
    valid = list(
        await session.scalars(
            select(Lead.id).where(
                Lead.tenant_id == tenant_id,
                Lead.id.in_(lead_ids),
                Lead.status == LeadStatus.ACTIVE,
            )
        )
    )
    if not valid:
        return 0
    result = await session.execute(
        insert(CampaignLead)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "campaign_id": campaign.id,
                    "lead_id": lead_id,
                    "status": CampaignLeadStatus.QUEUED,
                    "attempts": 0,
                }
                for lead_id in valid
            ]
        )
        .on_conflict_do_nothing(index_elements=["campaign_id", "lead_id"])
        .returning(CampaignLead.id)
    )
    added = len(result.all())
    await session.commit()
    return added


async def active_calls(session: AsyncSession, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Call)
        .where(
            Call.tenant_id == tenant_id,
            Call.campaign_id == campaign_id,
            Call.status.in_([CallStatus.CREATED, CallStatus.IN_PROGRESS]),
            Call.created_at >= func.now() - timedelta(hours=2),
        )
    )
    return int(count or 0)


async def call_next(
    session: AsyncSession,
    deps: OutboundDeps,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    requested_by: uuid.UUID | None,
    schedule: Schedule,
) -> CallNextResult:
    """Call the next due lead. Raises ``PlanLimitError`` (the lead stays queued).

    Queue timing (due, retry) uses real time; ``deps.clock`` is for compliance decisions.
    """
    now = datetime.now(UTC)
    entry = await session.scalar(
        select(CampaignLead)
        .where(
            CampaignLead.tenant_id == tenant_id,
            CampaignLead.campaign_id == campaign.id,
            CampaignLead.status == CampaignLeadStatus.QUEUED,
            CampaignLead.next_attempt_at <= func.now(),
        )
        .order_by(CampaignLead.next_attempt_at, CampaignLead.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if entry is None:
        return CallNextResult(status="empty")
    lead = await session.get(Lead, entry.lead_id)
    entry_id, lead_id = entry.id, entry.lead_id
    entry.status = CampaignLeadStatus.CALLING
    await session.flush()
    try:
        assert lead is not None  # noqa: S101 - FK
        placed = await place_outbound(
            session,
            deps,
            tenant_id=tenant_id,
            lead=lead,
            purpose=CallPurpose(campaign.purpose),
            campaign=campaign,
            requested_by=requested_by,
            schedule=schedule,
        )
    except CallBlockedError as exc:
        reasons = tuple((exc.details or {}).get("reasons", ()))
        await set_tenant_context(session, tenant_id)  # the gate committed its decision
        entry = await _entry(session, entry_id)
        entry.last_result = reasons[0] if reasons else "blocked"
        if reasons and set(reasons) <= RETRYABLE_REASONS:
            entry.status = CampaignLeadStatus.QUEUED
            entry.next_attempt_at = now + timedelta(minutes=campaign.retry_delay_minutes)
        else:
            entry.status = CampaignLeadStatus.SKIPPED
        await session.commit()
        await set_tenant_context(session, tenant_id)
        return CallNextResult(status="blocked", lead_id=lead_id, reasons=reasons)
    except PlanLimitError:
        await session.rollback()  # the lead goes back to the queue untouched
        await set_tenant_context(session, tenant_id)
        raise
    entry = await _entry(session, entry_id)
    entry.attempts += 1
    entry.last_call_id = placed.call_id
    entry.last_result = "dialing"
    await session.commit()
    await set_tenant_context(session, tenant_id)
    return CallNextResult(status="placed", lead_id=lead_id, call_id=placed.call_id)


async def _entry(session: AsyncSession, entry_id: uuid.UUID) -> CampaignLead:
    entry = await session.get(CampaignLead, entry_id, populate_existing=True)
    assert entry is not None  # noqa: S101 - rows are never deleted while calling
    return entry
