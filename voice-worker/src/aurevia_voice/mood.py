"""WP-11.4: map the prospect's mood to voice settings. Built early, off by default.

The backend records a mood from the prospect's words (text only, never voice analysis) and
sends it at the start of the next turn. With ``AUREVIA_MOOD_VOICE`` on, the worker adjusts the
voice for that turn: softer and slower when the prospect is annoyed or confused, a little
lighter when warm, quicker when they are rushed. Neutral (or unknown) means the voice's own
defaults. Not proven on real calls: how it sounds needs the listening test (WP-11.7).
"""

from __future__ import annotations

from dataclasses import dataclass

Speed = str  # Cartesia's named speeds: "slowest", "slow", "normal", "fast", "fastest"


@dataclass(frozen=True)
class VoiceStyle:
    speed: Speed | None = None  # None: the voice default
    emotion: str | None = None  # a provider emotion name; None: no emotion control

    @property
    def label(self) -> str:
        """Stored in turn metrics, e.g. "slow/Calm"; "default" when nothing changes."""
        if self.speed is None and self.emotion is None:
            return "default"
        return f"{self.speed or 'normal'}/{self.emotion or 'none'}"


DEFAULT_STYLE = VoiceStyle()

# Starting points from the plan's tone table; tune by ear before any default changes.
MOOD_STYLES: dict[str, VoiceStyle] = {
    "warm": VoiceStyle(speed="normal", emotion="Content"),
    "neutral": DEFAULT_STYLE,
    "rushed": VoiceStyle(speed="fast"),
    "annoyed": VoiceStyle(speed="slow", emotion="Calm"),
    "skeptical": VoiceStyle(speed="normal", emotion="Confident"),
    "confused": VoiceStyle(speed="slow", emotion="Calm"),
}


def style_for(mood: str | None) -> VoiceStyle:
    """The voice style for a mood; anything unknown keeps the voice defaults."""
    return MOOD_STYLES.get(mood or "", DEFAULT_STYLE)
