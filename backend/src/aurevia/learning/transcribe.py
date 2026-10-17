"""Transcribe a recording, then delete it (WP-12.1, built early; nothing calls this yet).

The rule from the plan: audio is used only to transcribe and is then deleted. This step takes a
recording from a dedicated working folder (``workdir``), transcribes it
through a :class:`~aurevia.providers.transcription.BatchTranscriber`, and deletes the file
whether transcription worked or not. It refuses any file outside that folder, so it can never
delete anything else. Aurevia stores no audio: encrypted Indian-region storage with per-tenant
keys and audited access must exist before that changes.

The result is lines for the learning import (WP-12.3), which redacts them before storing.
A person maps the provider's speaker labels to expert and prospect.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from pathlib import Path

from aurevia.learning.models import LineSpeaker
from aurevia.learning.schemas import LineIn
from aurevia.providers.transcription import BatchTranscriber

logger = logging.getLogger(__name__)


class AudioOutsideWorkdirError(ValueError):
    pass


def _inside(workdir: Path, audio: Path) -> Path:
    root = workdir.resolve(strict=True)
    resolved = audio.resolve(strict=True)
    if resolved == root or root not in resolved.parents or not resolved.is_file():
        raise AudioOutsideWorkdirError("the recording must be a file in the learning audio folder")
    return resolved


async def transcribe_then_delete(
    audio: Path,
    *,
    workdir: Path,
    transcriber: BatchTranscriber,
    language: str,
    speakers: Mapping[str, LineSpeaker],
) -> list[LineIn]:
    """Transcribe ``audio`` and delete it, success or failure. Unmapped speakers are ``other``."""
    path = _inside(workdir, audio)
    try:
        transcription = await transcriber.transcribe(path, language=language)
    finally:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        # The file name may hold a person's name: log that a file went, never which.
        logger.info("Learning audio deleted after transcription")
    return [
        LineIn(
            speaker=speakers.get(segment.speaker, LineSpeaker.OTHER),
            text=segment.text,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            word_times_ms=list(segment.word_times_ms) or None,
        )
        for segment in transcription.segments
        if segment.text.strip()
    ]
