"""Removes known secret values from every log record the worker creates.

A safety net: no code should log a key, but vendor SDK errors are not under our control.
Redaction happens when the record is created (a log-record factory), so it applies to every
logger and every handler, including handlers LiveKit installs after start-up.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any

SECRET_ENV_VARS = ("DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "LIVEKIT_API_SECRET")
REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 8

_original_factory: Callable[..., logging.LogRecord] | None = None


def redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, REDACTED)
    return text


def scrub(record: logging.LogRecord, secrets: list[str]) -> None:
    """Render the message (and any traceback) now, with secrets removed."""
    message = redact(record.getMessage(), secrets)
    if record.exc_info:
        trace = logging.Formatter().formatException(record.exc_info)
        message = f"{message}\n{redact(trace, secrets)}"
        record.exc_info = None
        record.exc_text = None
    record.msg, record.args = message, None


def install_log_redaction(env: Mapping[str, str] | None = None) -> None:
    global _original_factory
    source = os.environ if env is None else env
    secrets = sorted(
        {
            source[name]
            for name in SECRET_ENV_VARS
            if len(source.get(name, "")) >= _MIN_SECRET_LENGTH
        },
        key=len,
        reverse=True,
    )
    if _original_factory is None:
        _original_factory = logging.getLogRecordFactory()
    base = _original_factory

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base(*args, **kwargs)
        if secrets:
            scrub(record, secrets)
        return record

    logging.setLogRecordFactory(factory)
