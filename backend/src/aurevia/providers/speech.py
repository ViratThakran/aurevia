"""Streaming speech-to-text and text-to-speech contracts for the voice runtime (Phase 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AudioFormat(StrEnum):
    PCM16 = "pcm16"  # little-endian signed 16-bit
    MULAW = "mulaw"  # 8 kHz telephony audio


@dataclass(frozen=True)
class AudioChunk:
    data: bytes
    sample_rate: int
    format: AudioFormat = AudioFormat.PCM16
    channels: int = 1


@dataclass(frozen=True)
class STTConfig:
    language: str  # BCP-47, e.g. "en-IN", "hi-IN"
    sample_rate: int
    format: AudioFormat = AudioFormat.PCM16
    interim_results: bool = True


@dataclass(frozen=True)
class TranscriptEvent:
    text: str
    is_final: bool
    confidence: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class TTSConfig:
    voice: str
    language: str
    sample_rate: int
    format: AudioFormat = AudioFormat.PCM16


@runtime_checkable
class STTProvider(Protocol):
    name: str

    def transcribe(
        self, audio: AsyncIterator[AudioChunk], config: STTConfig
    ) -> AsyncIterator[TranscriptEvent]:
        """Yield partial and final transcripts while audio streams in."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: AsyncIterator[str], config: TTSConfig) -> AsyncIterator[AudioChunk]:
        """Yield audio as text arrives. Closing the iterator must stop synthesis (barge-in)."""
        ...
