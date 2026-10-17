"""The WP-10.4 benchmark summary: failed runs are counted, never averaged in."""

from __future__ import annotations

from typing import Any

from aurevia_voice.simulate import SCENARIOS
from aurevia_voice.turn_benchmark import summarize


def _run(scenario: str, e2e: int, eot: int, heard: str = "", wer: float = 0.0) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "status": "completed",
        "prospect_wer": wer,
        "heard": heard,
        "latency": {
            "e2e_p50_ms": e2e,
            "e2e_p95_ms": e2e + 100,
            "end_of_turn_delay_p50_ms": eot,
            "tts_ttfb_p50_ms": 300,
            "llm_ttft_p50_ms": 1200,
            "interrupted_turns": 1,
            "measured_turns": 3,
        },
    }


def test_summary_uses_medians_and_counts_failures_apart() -> None:
    runs = [
        _run("busy", 1800, 500),
        _run("busy", 2000, 700, wer=0.1),
        _run("busy", 1900, 600),
        {"scenario": "busy", "status": "timeout"},
    ]
    s = summarize("fixed", runs)
    assert (s["runs"], s["completed"], s["failed"]) == (4, 3, 1)
    assert s["e2e_p50_ms_median"] == 1900 and s["e2e_p95_ms_median"] == 2000
    assert s["end_of_turn_delay_p50_ms_median"] == 600
    assert s["interrupted_turns_total"] == 3 and s["measured_turns_total"] == 9
    assert s["prospect_wer_mean"] == 0.033
    assert s["key_term_hits"] is None  # no names scenario run


def test_key_term_hits_come_from_the_names_scenario_only() -> None:
    s = summarize(
        "keyterms",
        [
            _run("names", 1800, 500, heard="Is this Meera from Aurevia? Okay Meera"),
            _run("busy", 1800, 500, heard="aurevia aurevia"),
        ],
    )
    assert s["key_term_hits"] == {"aurevia": 1, "meera": 2, "priyanka": 0}


def test_names_scenario_says_every_key_term() -> None:
    said = " ".join(SCENARIOS["names"]).lower()
    assert all(term in said for term in ("aurevia", "meera", "priyanka"))


def test_nothing_completed_gives_no_numbers() -> None:
    s = summarize("x", [{"scenario": "busy", "status": "no_result"}])
    assert s["completed"] == 0 and s["e2e_p50_ms_median"] is None
