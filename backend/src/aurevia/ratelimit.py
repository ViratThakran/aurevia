"""Rate limiting (Phase 9): slows password guessing and protects the API from floods.

In-memory sliding windows, one set per API process. That is enough for the pilot, which runs a
single API process; with several processes, swap ``SlidingWindowLimiter`` for a Redis-backed
one behind the same ``hit`` method.

Limited: every /api request per client IP; the sign-in endpoints per IP; sign-in attempts
per email. Not limited: /internal (the voice worker, already authenticated per call) and
/webhooks (signature-checked, from our media server).
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from aurevia.errors import AureviaError, error_response

MAX_KEYS = 100_000  # bounded memory: the least recently seen keys are forgotten first


class RateLimitedError(AureviaError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after: float) -> None:
        seconds = max(1, math.ceil(retry_after))
        super().__init__(
            "Too many requests; try again shortly",
            headers={"Retry-After": str(seconds)},
            details={"retry_after_seconds": seconds},
        )


@dataclass
class SlidingWindowLimiter:
    limit: int
    window_seconds: float
    _hits: OrderedDict[str, deque[float]] = field(default_factory=OrderedDict)

    def hit(self, key: str, now: float | None = None) -> float | None:
        """Count one request; return seconds to wait if over the limit, else None."""
        now = time.monotonic() if now is None else now
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
            if len(self._hits) > MAX_KEYS:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return hits[0] + self.window_seconds - now
        hits.append(now)
        return None


@dataclass
class RateLimits:
    api_per_ip: SlidingWindowLimiter
    auth_per_ip: SlidingWindowLimiter
    login_per_email: SlidingWindowLimiter

    def check(self, limiter: SlidingWindowLimiter, key: str) -> None:
        wait = limiter.hit(key)
        if wait is not None:
            raise RateLimitedError(wait)


def client_ip(scope: Scope | Any, trust_forwarded: bool) -> str:
    """The caller's address. ``X-Forwarded-For`` only behind a trusted proxy."""
    headers = scope.get("headers", []) if isinstance(scope, dict) else []
    if trust_forwarded:
        for name, value in headers:
            if name == b"x-forwarded-for":
                return str(value.decode("latin-1").split(",")[0].strip())[:64]
    client = scope.get("client") if isinstance(scope, dict) else None
    return str(client[0]) if client else "unknown"


class RateLimitMiddleware:
    """Per-IP limit on /api requests (pure ASGI, runs before routing)."""

    def __init__(self, app: ASGIApp, limits: RateLimits, trust_forwarded: bool) -> None:
        self.app = app
        self.limits = limits
        self.trust_forwarded = trust_forwarded

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/api/")
            and (scope.get("method") != "OPTIONS")
        ):
            wait = self.limits.api_per_ip.hit(client_ip(scope, self.trust_forwarded))
            if wait is not None:
                error = RateLimitedError(wait)
                response = error_response(
                    Request(scope),
                    status_code=error.status_code,
                    code=error.code,
                    message=error.message,
                    details=error.details,
                    headers=error.headers,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def limit_auth(request: Request) -> None:
    """Dependency for the sign-in endpoints: per client IP."""
    limits: RateLimits | None = getattr(request.app.state, "rate_limits", None)
    if limits is not None:
        settings = request.app.state.settings
        limits.check(limits.auth_per_ip, client_ip(request.scope, settings.trust_proxy_headers))


def limit_login_email(request: Request, email: str) -> None:
    """Sign-in attempts per email address, wherever they come from (password guessing)."""
    limits: RateLimits | None = getattr(request.app.state, "rate_limits", None)
    if limits is not None:
        limits.check(limits.login_per_email, email.strip().lower())
