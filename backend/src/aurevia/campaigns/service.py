"""Campaign records and their status lifecycle, in the tenant's RLS scope. Changes are audited."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.campaigns.models import Campaign, CampaignStatus
from aurevia.campaigns.schemas import CampaignIn, CampaignUpdate
from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event

# Allowed status changes. "ended" is final.
_TRANSITIONS: dict[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.DRAFT: frozenset({CampaignStatus.ACTIVE, CampaignStatus.ENDED}),
    CampaignStatus.ACTIVE: frozenset({CampaignStatus.PAUSED, CampaignStatus.ENDED}),
    CampaignStatus.PAUSED: frozenset({CampaignStatus.ACTIVE, CampaignStatus.ENDED}),
    CampaignStatus.ENDED: frozenset(),
}


class CampaignService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create(self, body: CampaignIn, actor: uuid.UUID) -> Campaign:
        campaign = Campaign(
            tenant_id=self._tenant_id,
            status=CampaignStatus.DRAFT,
            created_by_user_id=actor,
            **body.model_dump(),
        )
        self._session.add(campaign)
        await self._session.flush()
        self._audit(actor, "campaign.created", campaign.id, {"purpose": body.purpose.value})
        await self._session.commit()
        return campaign

    async def list(self) -> list[Campaign]:
        rows = await self._session.scalars(
            select(Campaign)
            .where(Campaign.tenant_id == self._tenant_id)
            .order_by(Campaign.created_at.desc())
        )
        return list(rows)

    async def get(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self._session.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id, Campaign.tenant_id == self._tenant_id
            )
        )
        if campaign is None:
            raise NotFoundError("Campaign not found")
        return campaign

    async def update(
        self, campaign_id: uuid.UUID, body: CampaignUpdate, actor: uuid.UUID
    ) -> Campaign:
        campaign = await self.get(campaign_id)
        if campaign.status == CampaignStatus.ENDED:
            raise ConflictError("An ended campaign cannot change", code="campaign_ended")
        changes = body.model_dump(exclude_unset=True)
        for name, value in changes.items():
            setattr(campaign, name, value)
        # The database also checks the ranges; validate the combined result here first.
        if campaign.ends_on is not None and campaign.ends_on < campaign.starts_on:
            raise ConflictError("ends_on must not be before starts_on", code="invalid_dates")
        if (
            campaign.window_start is not None
            and campaign.window_end is not None
            and campaign.window_start >= campaign.window_end
        ):
            raise ConflictError("window_start must be before window_end", code="invalid_window")
        if changes:
            self._audit(
                actor,
                "campaign.updated",
                campaign.id,
                {k: str(v) if v is not None else None for k, v in changes.items()},
            )
            await self._session.commit()
        return campaign

    async def set_status(
        self, campaign_id: uuid.UUID, status: CampaignStatus, actor: uuid.UUID
    ) -> Campaign:
        campaign = await self.get(campaign_id)
        current = CampaignStatus(campaign.status)
        if status == current:
            return campaign
        if status not in _TRANSITIONS[current]:
            raise ConflictError(
                f"A {current.value} campaign cannot become {status.value}",
                code="invalid_campaign_transition",
            )
        campaign.status = status
        self._audit(actor, "campaign.status_changed", campaign.id, {"from": current, "to": status})
        await self._session.commit()
        return campaign

    def _audit(
        self, actor: uuid.UUID, action: str, target_id: uuid.UUID, details: dict[str, object]
    ) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action=action,
            target_type="campaign",
            target_id=target_id,
            details={k: str(v) if isinstance(v, CampaignStatus) else v for k, v in details.items()},
        )
