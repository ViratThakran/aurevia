"""WP-12.2: remove personal data from transcripts before anything is stored or learned from.

Two layers:

1. **Patterns** for data with a fixed shape: email addresses, phone numbers (Indian and
   international), PAN, Aadhaar, GSTIN, and PIN codes when labelled ("pin 560001").
2. **A detector** for what patterns cannot find: names and street addresses. In use it asks a
   model through the Model Gateway (``GatewayDetector``); tests use a fake. The detector only
   returns where the data is; it never rewrites the text.

Every value gets a placeholder that keeps the conversation readable: the same value always
becomes the same placeholder in one transcript ("[NAME_1] said ... [NAME_1] agreed"). The
report holds **counts by kind only, never values**, so it is safe to log and store. The
original text is not kept here; deleting the source after success is the caller's job
(WP-12.3 import).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from aurevia.gateway import ModelGateway
from aurevia.gateway.gateway import GatewayError
from aurevia.providers.model import ModelMessage


class Kind(StrEnum):
    NAME = "NAME"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    ADDRESS = "ADDRESS"
    ID_NUMBER = "ID"


@dataclass(frozen=True)
class Span:
    kind: Kind
    start: int
    end: int


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)  # kind -> number replaced; no values

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class Detector(Protocol):
    async def detect(self, text: str) -> list[Span]: ...


_PATTERNS: tuple[tuple[Kind, re.Pattern[str]], ...] = (
    (Kind.EMAIL, re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # PAN: five letters, four digits, one letter. GSTIN: 2 digits + PAN + 3 characters.
    (Kind.ID_NUMBER, re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
    (Kind.ID_NUMBER, re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # Aadhaar: 12 digits, often in groups of four.
    (Kind.ID_NUMBER, re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    (Kind.ADDRESS, re.compile(r"\b(?:pin(?:\s*code)?|pincode)\s*[:\-]?\s*\d{6}\b", re.I)),
)


# A run of digits with single spaces or hyphens between groups, optionally after "+".
_DIGIT_RUN = re.compile(r"(?<![\w+])\+?\d(?:[\s-]?\d){7,14}(?![\w])")


def _is_phone(run: str) -> bool:
    digits = re.sub(r"\D", "", run)
    if run.startswith("+"):
        return 8 <= len(digits) <= 15  # any country with its code
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return len(digits) == 10 and digits[0] in "6789"  # an Indian mobile


def _pattern_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for kind, pattern in _PATTERNS:
        spans.extend(Span(kind, m.start(), m.end()) for m in pattern.finditer(text))
    spans.extend(
        Span(Kind.PHONE, m.start(), m.end())
        for m in _DIGIT_RUN.finditer(text)
        if _is_phone(m.group(0).rstrip(" -"))
    )
    return spans


def _merge(spans: Sequence[Span], length: int) -> list[Span]:
    """Drop overlaps (the earlier, then longer, span wins) and spans outside the text."""
    chosen: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, -(s.end - s.start))):
        if not 0 <= span.start < span.end <= length:
            continue
        if chosen and span.start < chosen[-1].end:
            continue
        chosen.append(span)
    return chosen


async def redact(text: str, detector: Detector | None = None) -> RedactionResult:
    spans = _pattern_spans(text)
    if detector is not None:
        spans.extend(await detector.detect(text))
    placeholders: dict[tuple[Kind, str], str] = {}
    per_kind: Counter[Kind] = Counter()
    counts: Counter[str] = Counter()
    out: list[str] = []
    cursor = 0
    for span in _merge(spans, len(text)):
        value = " ".join(text[span.start : span.end].lower().split())
        key = (span.kind, value)
        if key not in placeholders:
            per_kind[span.kind] += 1
            placeholders[key] = f"[{span.kind.value}_{per_kind[span.kind]}]"
        out.append(text[cursor : span.start])
        out.append(placeholders[key])
        counts[span.kind.value] += 1
        cursor = span.end
    out.append(text[cursor:])
    return RedactionResult(text="".join(out), counts=dict(counts))


DETECTOR_SYSTEM = """You find personal data in a sales-call transcript. Reply with JSON only:
{"items": [{"kind": "NAME" or "ADDRESS", "text": "<exact text as it appears>"}]}
NAME: a person's name. ADDRESS: a street address, building, flat or locality that identifies
where someone lives or works. Do not list company names, product names or cities alone.
Copy each item exactly as it appears. If there is none, reply {"items": []}."""


class GatewayDetector:
    """Names and addresses found by a model through the Model Gateway (provider-neutral)."""

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def detect(self, text: str) -> list[Span]:
        record = self._gateway.new_record({"purpose": "learning_redaction"})
        try:
            raw = "".join(
                [
                    d
                    async for d in self._gateway.stream_text(
                        system=DETECTOR_SYSTEM,
                        messages=(ModelMessage(role="user", content=text),),
                        record=record,
                    )
                ]
            )
        except GatewayError as exc:
            # Refuse to pass on unredacted text: the caller must not store it.
            raise RedactionError("detector_unavailable") from exc
        return spans_from_reply(text, raw)


class RedactionError(Exception):
    pass


def spans_from_reply(text: str, raw: str) -> list[Span]:
    """Positions of the model's items in ``text``; items not found verbatim are ignored."""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise RedactionError("detector_reply_unreadable")
    try:
        items = json.loads(match.group(0)).get("items", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RedactionError("detector_reply_unreadable") from exc
    spans: list[Span] = []
    for item in items if isinstance(items, list) else []:
        value = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
        kind = item.get("kind") if isinstance(item, dict) else None
        if not value or kind not in (Kind.NAME.value, Kind.ADDRESS.value):
            continue
        for found in re.finditer(re.escape(value), text, re.IGNORECASE):
            spans.append(Span(Kind(kind), found.start(), found.end()))
    return spans
