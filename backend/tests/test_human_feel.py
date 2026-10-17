"""WP-11.7 scorecard numbers, from transcript lines and per-turn timings."""

from __future__ import annotations

from aurevia.evaluation.human_feel import Line, score_call, summarize

LINES = [
    Line("agent", "Hello, this is Meera from Aurevia, an AI assistant."),
    Line("prospect", "Hi, yes, I have a couple of minutes."),
    Line("agent", "Hm, okay. How many people are on your team?"),
    Line("prospect", "About forty."),
    Line("agent", "Oh, nice. Would a short call with our specialist help?"),
]


def test_scorecard_from_one_call() -> None:
    card = score_call("c1", LINES, [1200, 900, 1500, -1], duration_seconds=60)
    assert card.agent_turns == 3 and card.minutes == 1.0
    assert card.talk_ratio == round(28 / 38, 3)
    assert card.agent_words_per_turn == 9.3
    assert card.questions_per_agent_turn == 0.67
    assert (card.pause_before_reply_p10_ms, card.pause_before_reply_p50_ms) == (900, 1200)
    assert card.pause_before_reply_p90_ms == 1500
    assert card.reactions_per_minute == 2.0  # "Hm, okay." and "Oh, nice."
    assert card.backchannels_per_minute is None  # WP-11.2 not built


def test_missing_data_gives_none_not_zero() -> None:
    card = score_call("c2", [], [], duration_seconds=None)
    assert card.talk_ratio is None and card.pause_before_reply_p50_ms is None
    assert card.reactions_per_minute is None and card.minutes is None


def test_summary_is_medians_across_calls() -> None:
    a = score_call("a", LINES, [1000], 60)
    b = score_call("b", LINES, [2000], 120)
    c = score_call("c", [], [], None)
    summary = summarize([a, b, c])
    assert summary["calls"] == 3
    assert summary["median_pause_before_reply_p50_ms"] == 1500
    assert summary["median_backchannels_per_minute"] is None
