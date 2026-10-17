"""WP-12.5 timing profile on synthetic data: aggregates only, talks never count."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aurevia.learning.timing import (
    TimedLine,
    build_profile,
    is_backchannel_text,
    lines_for_profile,
    load_profile,
)


def _call() -> list[TimedLine]:
    # prospect 0-3000, expert backchannel 1500-1800 (mid-turn), expert reply 3400-6400
    # prospect 6500-8000, expert reply 7900-9900 (overlap: starts 100 ms early)
    return [
        TimedLine("prospect", 0, 3000, 8, stage="discovery"),
        TimedLine("expert", 1500, 1800, 1, is_backchannel=True, stage="discovery"),
        TimedLine("expert", 3400, 6400, 10, stage="discovery"),
        TimedLine("prospect", 6500, 8000, 4, stage="objection"),
        TimedLine("expert", 7900, 9900, 6, stage="objection"),
    ]


def test_profile_numbers_from_synthetic_timings() -> None:
    profile = build_profile([_call()])
    every = profile["stages"]["all"]
    assert profile["calls"] == 1 and every["expert_turns"] == 2
    assert (every["pause_before_reply_p10_ms"], every["pause_before_reply_p90_ms"]) == (-100, 400)
    assert every["overlap_rate"] == 0.5
    assert every["backchannel_placement"] == {"mid_turn": 1, "gap": 0}
    assert every["minutes"] == round(9900 / 60_000, 2)
    assert every["speech_rate_wpm"] == round(16 / (5000 / 60_000), 1)
    assert every["turn_length_p50_ms"] in (2000, 3000)
    assert profile["stages"]["objection"]["overlap_rate"] == 1.0
    assert profile["stages"]["discovery"]["pause_before_reply_p50_ms"] == 400


def test_profile_holds_no_text() -> None:
    rows = [
        SimpleNamespace(seq=0, speaker="prospect", text="I am [NAME_1].", start_ms=0, end_ms=900),
        SimpleNamespace(seq=1, speaker="expert", text="Hmm.", start_ms=500, end_ms=700),
        SimpleNamespace(
            seq=2, speaker="expert", text="Got it, thanks.", start_ms=1200, end_ms=2000
        ),
        SimpleNamespace(
            seq=3, speaker="expert", text="No timing here.", start_ms=None, end_ms=None
        ),
    ]
    lines = lines_for_profile(rows, {0: "opening"})
    assert len(lines) == 3 and lines[1].is_backchannel and not lines[2].is_backchannel
    assert all(line.stage == "opening" for line in lines)  # a stage holds until the next
    dumped = json.dumps(build_profile([lines]))
    assert "NAME" not in dumped and "thanks" not in dumped


@pytest.mark.parametrize(
    ("text", "backchannel"),
    [("Hmm.", True), ("haan haan", True), ("Okay, right.", True), ("Okay, so what?", False)],
)
def test_backchannel_words(text: str, backchannel: bool) -> None:
    assert is_backchannel_text(text) is backchannel


def test_empty_input_and_saved_profile(tmp_path: Path) -> None:
    assert build_profile([]) == {"version": 1, "calls": 0, "stages": {}}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(build_profile([_call()])), encoding="utf-8")
    assert load_profile(path)["stages"]["all"]["expert_turns"] == 2
    path.write_text('{"version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="known version"):
        load_profile(path)
