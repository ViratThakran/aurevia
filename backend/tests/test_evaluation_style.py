"""Phase 10 baseline: the style metrics count what makes spoken replies tiring."""

from __future__ import annotations

from aurevia.evaluation.style import measure


def test_style_metrics() -> None:
    call = [
        "I understand. How many people work at your company?",
        "I understand, that is a lot. Do you have cover today? When is the renewal?",
        "Great question, absolutely. " + "word " * 40,
    ]
    m = measure([call])
    assert m.replies == 3
    assert m.stock_opener_rate == 1.0  # "I understand" (x2) and "Great" all match
    assert m.repeated_opener_rate == 1 / 3  # the second "I understand"
    assert m.multi_question_rate == 1 / 3
    assert m.long_reply_rate == 1 / 3
    assert m.fillers_per_reply == 2 / 3  # "great question", "absolutely"


def test_empty() -> None:
    assert measure([]).replies == 0
