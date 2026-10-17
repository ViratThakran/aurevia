"""WP-12.2 redaction: seeded fake personal data must all be gone; reports hold counts only."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from aurevia.gateway import ModelGateway
from aurevia.learning.redaction import (
    GatewayDetector,
    Kind,
    RedactionError,
    Span,
    redact,
    spans_from_reply,
)
from aurevia.providers.fakes import FakeModelProvider

# Obviously fake, test-only personal data.
NAMES = ("Ravi Kumar", "Priyanka Iyer")
ADDRESS = "Flat 4B, 12 MG Road, Indiranagar"
SEEDED = {
    "phone": "+91 98765 43210",
    "phone2": "9123456780",
    "email": "ravi.kumar@example.com",
    "pan": "ABCDE1234F",
    "aadhaar": "2345 6789 0123",
    "gstin": "29ABCDE1234F1Z5",
    "pin": "pin 560038",
}
TRANSCRIPT = (
    f"Agent: Hello, am I speaking with {NAMES[0]}? "
    f"Prospect: Yes, this is {NAMES[0]}. My number is {SEEDED['phone']}, or {SEEDED['phone2']}. "
    f"Email me at {SEEDED['email']}. Our PAN is {SEEDED['pan']}, GSTIN {SEEDED['gstin']}. "
    f"My Aadhaar is {SEEDED['aadhaar']}. We are at {ADDRESS}, {SEEDED['pin']}. "
    f"Talk to {NAMES[1]} in accounts; {NAMES[0]} decides. We have 40 staff, renewal in March."
)


class FakeDetector:
    """Finds the seeded names and address, as a model would."""

    async def detect(self, text: str) -> list[Span]:
        spans = []
        for kind, values in ((Kind.NAME, NAMES), (Kind.ADDRESS, (ADDRESS,))):
            for value in values:
                spans += [Span(kind, m.start(), m.end()) for m in re.finditer(value, text)]
        return spans


def test_no_seeded_personal_data_is_left() -> None:
    result = asyncio.run(redact(TRANSCRIPT, FakeDetector()))
    for value in (*NAMES, ADDRESS, *SEEDED.values()):
        assert value.lower() not in result.text.lower(), value
    assert "560038" not in result.text and "98765" not in result.text
    # Structure and non-personal facts stay.
    assert "We have 40 staff, renewal in March." in result.text
    assert result.text.startswith("Agent: Hello, am I speaking with [NAME_1]?")


def test_same_value_same_placeholder_and_counts_only() -> None:
    result = asyncio.run(redact(TRANSCRIPT, FakeDetector()))
    assert result.text.count("[NAME_1]") == 3 and result.text.count("[NAME_2]") == 1
    assert result.counts == {"NAME": 4, "ADDRESS": 2, "PHONE": 2, "EMAIL": 1, "ID": 3}
    assert all(isinstance(v, int) for v in result.counts.values())
    report = json.dumps(result.counts)
    assert not any(value.lower() in report.lower() for value in (*NAMES, *SEEDED.values()))


def test_patterns_alone_catch_fixed_shapes_but_not_names() -> None:
    result = asyncio.run(redact(TRANSCRIPT))
    assert SEEDED["email"] not in result.text and SEEDED["pan"] not in result.text
    assert NAMES[0] in result.text  # names need the detector


def test_amounts_and_years_are_not_phone_numbers() -> None:
    text = "It costs 150000 a year from 2026, about 4000 per person, policy 12345."
    assert asyncio.run(redact(text)).text == text


def _gateway(*replies: str) -> ModelGateway:
    return ModelGateway(
        FakeModelProvider(replies=list(replies)),
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )


def test_gateway_detector_maps_the_models_items_to_positions() -> None:
    reply = json.dumps(
        {"items": [{"kind": "NAME", "text": "Ravi Kumar"}, {"kind": "ADDRESS", "text": ADDRESS}]}
    )
    detector = GatewayDetector(_gateway(reply))
    result = asyncio.run(redact(TRANSCRIPT, detector))
    assert "Ravi Kumar" not in result.text and ADDRESS not in result.text
    assert "Priyanka Iyer" in result.text  # the model did not list her: not invented


def test_detector_failure_refuses_rather_than_passing_text_on() -> None:
    with pytest.raises(RedactionError, match="detector_unavailable"):
        asyncio.run(redact(TRANSCRIPT, GatewayDetector(_gateway())))  # no reply: provider error
    with pytest.raises(RedactionError, match="unreadable"):
        spans_from_reply(TRANSCRIPT, "sorry, I cannot help")


def test_items_not_in_the_text_and_unknown_kinds_are_ignored() -> None:
    reply = json.dumps(
        {"items": [{"kind": "NAME", "text": "Nobody Here"}, {"kind": "SECRET", "text": "Ravi"}]}
    )
    assert spans_from_reply(TRANSCRIPT, reply) == []


def test_redact_lines_shares_placeholders_and_never_joins_lines() -> None:
    from aurevia.learning.redaction import redact_lines

    lines = ["Hello Ravi Kumar, call 98765", "43210 is not a phone here.", "Bye, Ravi Kumar."]
    out, counts = asyncio.run(redact_lines(lines, FakeDetector()))
    assert out == ["Hello [NAME_1], call 98765", "43210 is not a phone here.", "Bye, [NAME_1]."]
    assert counts == {"NAME": 2}
