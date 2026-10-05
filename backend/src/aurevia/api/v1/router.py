"""Aggregate router for API v1. New v1 domains are included here, nowhere else."""

from __future__ import annotations

from fastapi import APIRouter

from aurevia.api.v1 import auth, health, tenant, voice

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(tenant.router)
api_v1_router.include_router(voice.router)
