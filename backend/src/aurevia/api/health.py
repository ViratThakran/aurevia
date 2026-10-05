"""Unversioned liveness probe (used by container/orchestrator healthchecks)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", summary="Liveness probe")
async def liveness() -> LivenessResponse:
    """The process is up. Deliberately checks no dependencies."""
    return LivenessResponse(status="ok")
