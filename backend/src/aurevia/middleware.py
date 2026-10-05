"""Request context middleware: correlation ID + access log.

Implemented as pure ASGI (not ``BaseHTTPMiddleware``) so context variables and streaming
responses behave correctly.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aurevia.logging import request_id_var, tenant_id_var, user_id_var

REQUEST_ID_HEADER = "X-Request-ID"
# Client-supplied IDs are accepted only if they are short and made of safe characters,
# which prevents log injection (newlines, control characters) and oversized values.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = frozenset({"/health"})  # container healthchecks: log at DEBUG only

logger = logging.getLogger("aurevia.access")


def _incoming_request_id(scope: Scope) -> str | None:
    wanted = REQUEST_ID_HEADER.lower().encode()
    for name, value in scope.get("headers", []):
        if name == wanted:
            candidate = value.decode("latin-1")
            return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        # Filled in by authentication; cleared here so nothing carries over between requests.
        tenant_token = tenant_id_var.set(None)
        user_token = user_id_var.set(None)
        started = time.perf_counter()
        status_code = 500  # if the app raises, the outer error handler responds with 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            path = scope["path"]
            logger.log(
                logging.DEBUG if path in _QUIET_PATHS else logging.INFO,
                "request",
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": path,  # path only: query strings may carry sensitive data
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                },
            )
            user_id_var.reset(user_token)
            tenant_id_var.reset(tenant_token)
            request_id_var.reset(token)
