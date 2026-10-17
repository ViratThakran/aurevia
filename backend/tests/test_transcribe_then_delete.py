"""WP-12.1: audio is used only to transcribe, then deleted; nothing outside the folder."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aurevia.learning.models import LineSpeaker
from aurevia.learning.transcribe import AudioOutsideWorkdirError, transcribe_then_delete
from aurevia.providers.fakes import FakeBatchTranscriber
from aurevia.providers.transcription import (
    BatchTranscriber,
    TranscribedSegment,
    TranscriptionError,
)

SEGMENTS = [
    TranscribedSegment("0", "Hi, is this a good time?", 0, 1500, ((0, 300), (300, 700))),
    TranscribedSegment("1", "Haan, boliye.", 1700, 2400),
    TranscribedSegment("2", "  ", 2500, 2600),  # empty: dropped
    TranscribedSegment("3", "Someone in the background.", 2600, 3000),
]
SPEAKERS = {"0": LineSpeaker.EXPERT, "1": LineSpeaker.PROSPECT}


def _audio(tmp_path: Path) -> tuple[Path, Path]:
    workdir = tmp_path / "audio"
    workdir.mkdir()
    audio = workdir / "call-001.wav"
    audio.write_bytes(b"RIFF fake audio")
    return workdir, audio


def test_lines_come_back_and_the_audio_is_gone(tmp_path: Path) -> None:
    workdir, audio = _audio(tmp_path)
    fake = FakeBatchTranscriber(segments=SEGMENTS)
    assert isinstance(fake, BatchTranscriber)
    lines = asyncio.run(
        transcribe_then_delete(
            audio, workdir=workdir, transcriber=fake, language="hi-IN", speakers=SPEAKERS
        )
    )
    assert not audio.exists()
    assert [line.speaker for line in lines] == [
        LineSpeaker.EXPERT,
        LineSpeaker.PROSPECT,
        LineSpeaker.OTHER,  # unmapped speaker
    ]
    assert lines[0].word_times_ms == [(0, 300), (300, 700)] and lines[1].word_times_ms is None
    assert (lines[1].start_ms, lines[1].end_ms) == (1700, 2400)


def test_failed_transcription_still_deletes(tmp_path: Path) -> None:
    workdir, audio = _audio(tmp_path)
    with pytest.raises(TranscriptionError):
        asyncio.run(
            transcribe_then_delete(
                audio,
                workdir=workdir,
                transcriber=FakeBatchTranscriber(segments=[], fail=True),
                language="en-IN",
                speakers=SPEAKERS,
            )
        )
    assert not audio.exists()


def test_files_outside_the_folder_are_never_touched(tmp_path: Path) -> None:
    workdir, _ = _audio(tmp_path)
    outside = tmp_path / "keep.wav"
    outside.write_bytes(b"keep me")
    sneaky = workdir / ".." / "keep.wav"
    fake = FakeBatchTranscriber(segments=SEGMENTS)
    for path in (outside, sneaky, workdir):
        with pytest.raises(AudioOutsideWorkdirError):
            asyncio.run(
                transcribe_then_delete(
                    path, workdir=workdir, transcriber=fake, language="en-IN", speakers=SPEAKERS
                )
            )
    assert outside.read_bytes() == b"keep me" and fake.seen == []
