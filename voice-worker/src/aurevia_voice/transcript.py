"""Collects what was said, in order, for the backend to keep until its retention date."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from livekit.agents import llm


@dataclass
class TranscriptCollector:
    lines: list[dict[str, Any]] = field(default_factory=list)

    def add(self, item: object) -> None:
        if not isinstance(item, llm.ChatMessage) or item.role not in ("user", "assistant"):
            return
        text = (item.text_content or "").strip()
        if not text:
            return
        self.lines.append(
            {
                "seq": len(self.lines),
                "speaker": "prospect" if item.role == "user" else "agent",
                "text": text[:4000],
            }
        )
