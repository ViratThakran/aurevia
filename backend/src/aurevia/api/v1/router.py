"""Aggregate router for API v1. New v1 domains are included here, nowhere else."""

from __future__ import annotations

from fastapi import APIRouter

from aurevia.api.v1 import (
    analytics,
    audit,
    auth,
    campaigns,
    compliance,
    health,
    leads,
    platform,
    team,
    telephony,
    tenant,
    voice,
)

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(tenant.router)
api_v1_router.include_router(voice.router)
api_v1_router.include_router(leads.router)
api_v1_router.include_router(telephony.router)
api_v1_router.include_router(compliance.router)
api_v1_router.include_router(campaigns.router)
api_v1_router.include_router(audit.router)
api_v1_router.include_router(team.router)
api_v1_router.include_router(analytics.router)
api_v1_router.include_router(platform.router)
