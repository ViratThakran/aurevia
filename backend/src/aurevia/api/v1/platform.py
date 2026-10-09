"""Aurevia staff only: tenants, plans and prices across all customers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder

from aurevia.identity.dependencies import PlatformAdminDep, SessionDep, SettingsDep
from aurevia.identity.models import TenantStatus
from aurevia.platform import admin
from aurevia.platform.limits import default_limits
from aurevia.platform.models import Price, TenantPlan

router = APIRouter(prefix="/platform", tags=["platform"])


def _plan(plan: TenantPlan | None, settings: Any) -> dict[str, Any]:
    if plan is None:
        return {"default": True, **jsonable_encoder(default_limits(settings))}
    encoded: dict[str, Any] = jsonable_encoder(
        {
            "default": False,
            "plan_name": plan.plan_name,
            "monthly_call_limit": plan.monthly_call_limit,
            "monthly_minute_limit": plan.monthly_minute_limit,
            "monthly_cost_limit": plan.monthly_cost_limit,
            "cost_currency": plan.cost_currency,
            "max_concurrent_calls": plan.max_concurrent_calls,
            "updated_at": plan.updated_at,
        }
    )
    return encoded


def _price(price: Price) -> dict[str, Any]:
    encoded: dict[str, Any] = jsonable_encoder(
        {
            "id": price.id,
            "provider": price.provider,
            "resource": price.resource,
            "model": price.model,
            "currency": price.currency,
            "amount": price.amount,
            "per_quantity": price.per_quantity,
            "effective_from": price.effective_from,
        }
    )
    return encoded


@router.get("/tenants", summary="All tenants with members and this month's calls")
async def list_tenants(principal: PlatformAdminDep, session: SessionDep) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = jsonable_encoder(await admin.list_tenants(session))
    return encoded


@router.post("/tenants/{tenant_id}/suspend", summary="Suspend a tenant (signs everyone out)")
async def suspend_tenant(
    tenant_id: uuid.UUID, principal: PlatformAdminDep, session: SessionDep
) -> dict[str, str]:
    tenant = await admin.set_tenant_status(
        session, tenant_id, TenantStatus.SUSPENDED, principal.user_id
    )
    return {"id": str(tenant.id), "status": tenant.status}


@router.post("/tenants/{tenant_id}/resume", summary="Resume a suspended tenant")
async def resume_tenant(
    tenant_id: uuid.UUID, principal: PlatformAdminDep, session: SessionDep
) -> dict[str, str]:
    tenant = await admin.set_tenant_status(
        session, tenant_id, TenantStatus.ACTIVE, principal.user_id
    )
    return {"id": str(tenant.id), "status": tenant.status}


@router.get("/tenants/{tenant_id}/plan", summary="A tenant's plan limits")
async def get_plan(
    tenant_id: uuid.UUID, principal: PlatformAdminDep, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    return _plan(await admin.get_plan(session, tenant_id), settings)


@router.put("/tenants/{tenant_id}/plan", summary="Set a tenant's plan limits")
async def set_plan(
    tenant_id: uuid.UUID,
    body: admin.PlanIn,
    principal: PlatformAdminDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    return _plan(await admin.set_plan(session, tenant_id, body, principal.user_id), settings)


@router.get("/prices", summary="Provider prices (all versions)")
async def list_prices(principal: PlatformAdminDep, session: SessionDep) -> list[dict[str, Any]]:
    return [_price(p) for p in await admin.list_prices(session)]


@router.post("/prices", status_code=status.HTTP_201_CREATED, summary="Add a price version")
async def add_price(
    body: admin.PriceIn, principal: PlatformAdminDep, session: SessionDep
) -> dict[str, Any]:
    return _price(await admin.add_price(session, body, principal.user_id))
