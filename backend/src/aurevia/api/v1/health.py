"""Readiness probe: is the service able to serve traffic (dependencies reachable)?

Dependencies register async checks in ``app.state.readiness_checks`` (name -> callable).
The app factory registers the database check when a database is configured. Failure details
are logged server-side and never returned to callers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[bool]]
READINESS_CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(tags=["health"])


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "failed"]]


async def _run_check(name: str, check: ReadinessCheck) -> Literal["ok", "failed"]:
    try:
        healthy = await asyncio.wait_for(check(), timeout=READINESS_CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Readiness check raised", extra={"fields": {"check": name}})
        return "failed"
    return "ok" if healthy else "failed"


@router.get("/health/ready", summary="Readiness probe", response_model=ReadinessResponse)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    registered: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    names = list(registered)
    outcomes = await asyncio.gather(*(_run_check(n, registered[n]) for n in names))
    checks = dict(zip(names, outcomes, strict=True))
    healthy = all(result == "ok" for result in checks.values())
    if not healthy:
        response.status_code = 503
    return ReadinessResponse(status="ok" if healthy else "unavailable", checks=checks)
