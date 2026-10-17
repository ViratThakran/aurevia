"""WP-12.6 automatic policy check: what the voice rules forbid is flagged before review."""

from __future__ import annotations

import pytest

from aurevia.learning.policy import FLAG_TEXT, policy_flags


@pytest.mark.parametrize(
    ("says", "flag"),
    [
        ("Don't worry, I'm a real person, not a recording.", "claims_human"),
        ("I'm not a bot, promise.", "claims_human"),
        ("Main insaan hoon, aap bataiye.", "claims_human"),
        ("We guarantee you will save money.", "guarantee"),
        ("It's completely risk-free.", "guarantee"),
        ("This offer ends tonight, so you must decide now.", "pressure"),
        ("Hi [NAME_1], is this a good time?", "redaction_placeholder"),
        ("Call me back on 98765 43210.", "personal_data"),
    ],
)
def test_flags(says: str, flag: str) -> None:
    assert flag in policy_flags("A situation.", says, "A goal.")
    assert flag in FLAG_TEXT


def test_clean_candidates_pass() -> None:
    assert (
        policy_flags(
            "The prospect says it is too expensive.",
            "Fair enough. Expensive compared with what you have now?",
            "Find what they compare the price with.",
        )
        == []
    )
    # An honest answer about being an AI is fine.
    assert policy_flags("Asked if a bot.", "I'm an AI assistant for Acme.", "Be honest.") == []


def test_personal_data_anywhere_is_flagged() -> None:
    assert policy_flags("They gave ravi@example.com.", "Thanks.", "Note it.") == ["personal_data"]
