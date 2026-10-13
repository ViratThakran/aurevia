"""Tell the person on a browser call when the voice, listening or model service fails.

Without this a provider failure (for example Cartesia running out of credits) is silent: the
agent's reply is generated but never spoken, and the caller just waits.

What is sent to the browser is a small, fixed shape: the *source* (voice / listening / model),
a *category*, whether retrying makes sense, and, for a reply that could not be spoken, the
words of that reply. Raw provider messages, headers and keys never leave this module: errors
are classified from their type and status code only, and what is logged is the category and
the numeric status.

Retrying audio speaks the stored words again with ``session.say``. That never calls the
language model, so it cannot run tools: a booking, handoff or do-not-call recorded for that
turn is not repeated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from livekit.agents import APIConnectionError, APIError, APIStatusError, APITimeoutError

logger = logging.getLogger(__name__)

TOPIC = "aurevia.voice_status"
RETRY_METHOD = "aurevia.retry_speech"

Category = Literal[
    "credits_exhausted", "rate_limited", "timeout", "provider_unavailable", "unknown"
]
# voice = text to speech, listening = speech to text, model = the AI model (via the backend).
Source = Literal["voice", "listening", "model"]

MAX_TEXT = 4000
MAX_PENDING = 5
_STATUS_IN_MESSAGE = re.compile(r"status_code['\"]?\s*[:=]\s*(\d{3})")
# Codes our own backend puts in the model-failure message (see llm_bridge.py).
_BACKEND_CODES: dict[str, Category] = {
    "rate_limited": "rate_limited",
    "timeout": "timeout",
    "unavailable": "provider_unavailable",
}


def _category_for_status(status: int) -> Category:
    if status == 402:
        return "credits_exhausted"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    if status >= 500:
        return "provider_unavailable"
    return "unknown"


def classify(error: BaseException | None) -> tuple[Category, int | None]:
    """The failure category and the HTTP status when there is one. Never reads message text
    except for a numeric ``status_code`` or one of our own backend codes."""
    seen = 0
    current = error
    while current is not None and seen < 4:
        seen += 1
        if isinstance(current, APIStatusError):
            if current.status_code > 0:
                category = _category_for_status(current.status_code)
                if current.status_code == 502:  # our backend reporting a model failure
                    for code, mapped in _BACKEND_CODES.items():
                        if code in str(current):
                            return mapped, current.status_code
                if category != "unknown":
                    return category, current.status_code
                return "unknown", current.status_code
        elif isinstance(current, APITimeoutError | TimeoutError):
            return "timeout", None
        elif isinstance(current, APIConnectionError):
            return "provider_unavailable", None
        elif isinstance(current, APIError):
            # A provider error carried as text (e.g. an error frame on a websocket).
            found = _STATUS_IN_MESSAGE.search(str(current))
            if found:
                status = int(found.group(1))
                return _category_for_status(status), status
        current = current.__cause__ or current.__context__
    return "unknown", None


class VoiceStatusReporter:
    """Publishes failures to the call's browser and handles its "speak this again" request."""

    def __init__(
        self,
        *,
        call_id: str,
        provider: str,
        publish: Callable[[dict[str, Any], str | None], Awaitable[None]],
        say: Callable[[str], Awaitable[None]],
    ) -> None:
        self._call_id = call_id
        self._provider = provider
        self._publish = publish
        self._say = say
        self._pending: OrderedDict[str, str] = OrderedDict()
        # The latest failures, replayed to a browser that joins after they happened
        # (the greeting can fail before the caller's browser is in the room).
        self._recent: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._failures = 0
        self._retrying = False
        self._tasks: set[asyncio.Task[None]] = set()

    def report(self, error: BaseException | None, *, source: Source, text: str = "") -> str:
        """Record and publish one failure. Never raises; returns the failure id."""
        category, status = classify(error)
        failure_id = uuid.uuid4().hex[:12]
        self._failures += 1
        words = text.strip()[:MAX_TEXT]
        if words and source == "voice":
            self._pending[failure_id] = words
            while len(self._pending) > MAX_PENDING:
                self._pending.popitem(last=False)
        logger.error(
            "Voice service failure",
            extra={
                "call_id": self._call_id,
                "provider": self._provider,
                "source": source,
                "category": category,
                "http_status": status,
            },
        )
        payload = {
            "type": "voice_issue",
            "id": failure_id,
            "source": source,
            "category": category,
            "retryable": source == "voice" and bool(words),
            "text": words or None,
        }
        self._recent[failure_id] = payload
        while len(self._recent) > MAX_PENDING:
            self._recent.popitem(last=False)
        self._schedule(payload)
        return failure_id

    def _schedule(self, payload: dict[str, Any], destination: str | None = None) -> None:
        task = asyncio.ensure_future(self._safe_publish(payload, destination))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def replay_to(self, identity: str) -> None:
        """Send the recent, unresolved failures to a participant that has just joined."""
        for payload in list(self._recent.values()):
            self._schedule(payload, identity)

    async def _safe_publish(self, payload: dict[str, Any], destination: str | None = None) -> None:
        try:
            await self._publish(payload, destination)
        except Exception as exc:  # the call must never break because a notice failed
            logger.warning(
                "Could not publish voice status",
                extra={"call_id": self._call_id, "error_type": type(exc).__name__},
            )

    async def retry(self, failure_id: str) -> dict[str, Any]:
        """Speak a failed reply again. One attempt per failure; no model call, no tools."""
        if self._retrying:
            return {"ok": False, "reason": "busy"}
        words = self._pending.pop(failure_id, None)
        if words is None:
            return {"ok": False, "reason": "not_available"}
        self._recent.pop(failure_id, None)  # this failure is being handled
        self._retrying = True
        failures_before = self._failures
        try:
            await self._say(words)
        except Exception as exc:
            self.report(exc, source="voice", text=words)
            return {"ok": False, "reason": "failed"}
        finally:
            self._retrying = False
        if self._failures != failures_before:
            return {"ok": False, "reason": "failed"}  # the new failure was published already
        await self._safe_publish({"type": "speech_recovered", "id": failure_id}, None)
        return {"ok": True}

    async def handle_rpc(self, payload: str) -> str:
        """RPC entry point: the browser sends ``{"id": "<failure id>"}``; nothing else is read."""
        try:
            failure_id = str(json.loads(payload).get("id", ""))[:40]
        except (ValueError, AttributeError):
            return json.dumps({"ok": False, "reason": "bad_request"})
        return json.dumps(await self.retry(failure_id))
