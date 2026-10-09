"""Platform administration (Phase 8): Aurevia staff managing tenants, plans and prices.

Callers are platform administrators (``PlatformAdminDep``; the flag is set only by
``python -m aurevia.platform.operator``). Listing all tenants reads through one SECURITY DEFINER
function (``platform_tenants``). Every change to a tenant is made inside that tenant's own
row-level-security scope and written to **that tenant's** audit log, so customers can see
what Aurevia staff did.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.db.session import set_tenant_context
from aurevia.errors import NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.identity.models import RefreshToken, Tenant, TenantStatus
from aurevia.platform.models import Price, PriceResource, TenantPlan


class PlanIn(BaseModel):
    plan_name: str = Field(min_length=1, max_length=50)
    monthly_call_limit: int | None = Field(default=None, ge=1)
    monthly_minute_limit: int | None = Field(default=None, ge=1)
    monthly_cost_limit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    cost_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    max_concurrent_calls: int = Field(default=2, ge=1, le=100)

    @model_validator(mode="after")
    def _currency(self) -> PlanIn:
        if self.monthly_cost_limit is not None and self.cost_currency is None:
            raise ValueError("a cost limit needs its currency")
        return self


class PriceIn(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    resource: PriceResource
    model: str = Field(default="*", min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    per_quantity: int = Field(ge=1)  # e.g. 1000000 tokens, 60 seconds, 1000 characters
    effective_from: datetime | None = None  # default: now


async def list_tenants(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(text("SELECT * FROM platform_tenants()"))).mappings().all()
    await session.commit()
    return [dict(r) for r in rows]


async def _tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    await set_tenant_context(session, tenant_id)
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise NotFoundError("Tenant not found")
    return tenant


async def set_tenant_status(
    session: AsyncSession, tenant_id: uuid.UUID, status: TenantStatus, actor: uuid.UUID
) -> Tenant:
    tenant = await _tenant(session, tenant_id)
    if tenant.status != status:
        tenant.status = status
        if status == TenantStatus.SUSPENDED:
            # Signed-in sessions end now; access tokens already fail the membership check.
            await session.execute(
                RefreshToken.__table__.update()  # type: ignore[attr-defined]
                .where(RefreshToken.tenant_id == tenant_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        record_audit_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=actor,
            action=(
                "platform.tenant_suspended"
                if status == TenantStatus.SUSPENDED
                else "platform.tenant_resumed"
            ),
            target_type="tenant",
            target_id=tenant_id,
        )
        await session.commit()
    return tenant


async def get_plan(session: AsyncSession, tenant_id: uuid.UUID) -> TenantPlan | None:
    await _tenant(session, tenant_id)
    return await session.get(TenantPlan, tenant_id)


async def set_plan(
    session: AsyncSession, tenant_id: uuid.UUID, body: PlanIn, actor: uuid.UUID
) -> TenantPlan:
    await _tenant(session, tenant_id)
    plan = await session.get(TenantPlan, tenant_id)
    if plan is None:
        plan = TenantPlan(tenant_id=tenant_id)
        session.add(plan)
    for name, value in body.model_dump().items():
        setattr(plan, name, value)
    plan.updated_by_user_id = actor
    record_audit_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor,
        action="platform.plan_changed",
        target_type="tenant",
        target_id=tenant_id,
        details=body.model_dump(mode="json"),
    )
    await session.commit()
    return plan


async def list_prices(session: AsyncSession) -> list[Price]:
    rows = await session.scalars(
        select(Price).order_by(Price.provider, Price.resource, Price.effective_from.desc())
    )
    return list(rows)


async def add_price(session: AsyncSession, body: PriceIn, actor: uuid.UUID) -> Price:
    price = Price(
        provider=body.provider,
        resource=body.resource,
        model=body.model,
        currency=body.currency,
        amount=body.amount,
        per_quantity=body.per_quantity,
        effective_from=body.effective_from or datetime.now(UTC),
        created_by_user_id=actor,
    )
    session.add(price)
    await session.commit()
    return price
