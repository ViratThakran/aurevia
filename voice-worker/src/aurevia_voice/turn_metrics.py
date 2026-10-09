"""Collects per-turn latency from LiveKit's chat messages. Timings only, never text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from livekit.agents import llm


def _ms(metrics: dict[str, Any], key: str) -> int | None:
    value = metrics.get(key)
    if not isinstance(value, int | float) or value < 0:
        return None
    return round(value * 1000)


@dataclass
class TurnMetricsCollector:
    turns: list[dict[str, Any]] = field(default_factory=list)

    def add(self, item: object) -> None:
        if not isinstance(item, llm.ChatMessage) or item.role not in ("user", "assistant"):
            return
        metrics: dict[str, Any] = dict(item.metrics or {})
        turn: dict[str, Any] = {
            "seq": len(self.turns),
            "role": "prospect" if item.role == "user" else "agent",
            "interrupted": bool(item.interrupted),
        }
        if item.role == "user":
            turn["transcription_delay_ms"] = _ms(metrics, "transcription_delay")
            turn["end_of_turn_delay_ms"] = _ms(metrics, "end_of_turn_delay")
        else:
            turn["e2e_latency_ms"] = _ms(metrics, "e2e_latency")
            turn["llm_ttft_ms"] = _ms(metrics, "llm_node_ttft")
            turn["tts_ttfb_ms"] = _ms(metrics, "tts_node_ttfb")
        self.turns.append(turn)
