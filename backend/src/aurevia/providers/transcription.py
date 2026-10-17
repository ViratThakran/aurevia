"""Batch transcription contract (WP-12.1, built early; nothing real implements it yet).

A recording goes in; speaker-separated segments with word timings come out. English, Hindi
and Hinglish. A real adapter (for example Deepgram's pre-recorded API) must live in this
package like every other provider, and is waiting on the recordings inventory, counsel's view
on prospect consent, and the audio storage rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TranscribedSegment:
    speaker: str  # the provider's label, e.g. "0" or "S1"; a person maps it to expert/prospect
    text: str
    start_ms: int
    end_ms: int
    # Word timings as (start_ms, end_ms) pairs, numbers only.
    word_times_ms: tuple[tuple[int, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Transcription:
    language: str
    segments: tuple[TranscribedSegment, ...]


class TranscriptionError(Exception):
    pass


@runtime_checkable
class BatchTranscriber(Protocol):
    name: str

    async def transcribe(self, audio: Path, *, language: str) -> Transcription:
        """Transcribe a recording with speaker separation and word timings."""
        ...
