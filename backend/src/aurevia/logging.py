"""Structured logging foundation.

JSON logs carry the request correlation ID so a request can be traced across log lines.
Never pass secrets, tokens or transcript content as log fields.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
# Set once a request is authenticated, so every later log line carries the tenant and user.
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_HANDLER_MARKER = "_aurevia_handler"


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra structured data goes in ``extra={"fields": {...}}``."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, var in (("tenant_id", tenant_id_var), ("user_id", user_id_var)):
            value = var.get()
            if value:
                payload[key] = value
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                payload.setdefault(str(key), value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Idempotently configure the root logger."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)

    # The request middleware emits the access log; silence uvicorn's duplicate.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
