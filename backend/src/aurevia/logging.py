"""Structured logging foundation.

JSON logs carry the request correlation ID so a request can be traced across log lines.
Never pass secrets, tokens or transcript content as log fields.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
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


class TextFormatter(logging.Formatter):
    """Human-readable local logs that still show the structured fields (path, status...)."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = getattr(record, "fields", None)
        context = {"tenant_id": tenant_id_var.get(), "request_id": request_id_var.get()}
        extras = {**{k: v for k, v in context.items() if v}, **(fields or {})}
        if not extras:
            return line
        head, newline, rest = line.partition("\n")  # keep tracebacks below the fields
        rendered = " ".join(f"{key}={value}" for key, value in extras.items())
        return f"{head} {rendered}{newline}{rest}"


REDACTED = "[REDACTED]"
# Shorter values are not treated as secrets: replacing them would mangle ordinary text.
_MIN_SECRET_LENGTH = 8


class RedactingFormatter(logging.Formatter):
    """Wraps a formatter and removes known secret values from every formatted line,
    exception tracebacks included. A safety net: code must still never log secrets."""

    def __init__(self, inner: logging.Formatter, secrets: Iterable[str]) -> None:
        super().__init__()
        self._inner = inner
        # Longest first, so a secret containing another is removed whole.
        self._secrets = sorted(
            {s for s in secrets if len(s) >= _MIN_SECRET_LENGTH}, key=len, reverse=True
        )

    def format(self, record: logging.LogRecord) -> str:
        return redact(self._inner.format(record), self._secrets)


def redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, REDACTED)
    return text


def configure_logging(
    level: str = "INFO", *, json_output: bool = True, redact_values: Iterable[str] = ()
) -> None:
    """Idempotently configure the root logger. ``redact_values`` are scrubbed from output."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_MARKER, True)
    inner = JsonFormatter() if json_output else TextFormatter()
    handler.setFormatter(RedactingFormatter(inner, redact_values))
    root.addHandler(handler)
    root.setLevel(level)

    # The request middleware emits the access log; silence uvicorn's duplicate.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
