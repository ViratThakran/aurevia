"""What to do when the prospect goes quiet: re-prompt, then end the call politely.

LiveKit marks the user "away" after ``user_away_timeout`` seconds in which neither side
speaks. The decision logic here is pure so it can be tested without a live session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SilenceAction = Literal["reprompt", "hang_up"]


@dataclass
class SilenceTracker:
    reprompts_before_hang_up: int
    _silent_periods: int = 0

    def on_user_state(self, new_state: str) -> SilenceAction | None:
        if new_state == "speaking":
            self._silent_periods = 0  # any speech resets the count
            return None
        if new_state != "away":
            return None
        self._silent_periods += 1
        if self._silent_periods <= self.reprompts_before_hang_up:
            return "reprompt"
        return "hang_up"
