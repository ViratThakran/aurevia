"""Speech provider adapters: the only module that imports speech-vendor plugins.

The voice runtime (``main.py``) asks for "an STT" and "a TTS" through LiveKit's own ``stt.STT``
and ``tts.TTS`` interfaces and never names a vendor. Adding a vendor means adding a builder
here and a value to ``STTProvider``/``TTSProvider``; nothing else changes.

Keys are read from the environment by name (``DEEPGRAM_API_KEY``, ``CARTESIA_API_KEY``) and
passed straight to the plugin. Errors name the missing variable, never a value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from livekit.agents import stt, tts, vad

STTProvider = Literal["deepgram"]
TTSProvider = Literal["cartesia"]

REQUIRED_KEYS: dict[str, str] = {
    "deepgram": "DEEPGRAM_API_KEY",
    "cartesia": "CARTESIA_API_KEY",
}


class SpeechConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechOptions:
    stt_provider: STTProvider
    tts_provider: TTSProvider
    stt_model: str
    stt_language: str
    tts_model: str | None
    tts_voice: str | None
    tts_language: str


def missing_keys(
    stt_provider: STTProvider, tts_provider: TTSProvider, env: Mapping[str, str] | None = None
) -> list[str]:
    """Names of the required key variables that are unset or blank."""
    source = os.environ if env is None else env
    names = [REQUIRED_KEYS[stt_provider], REQUIRED_KEYS[tts_provider]]
    return [name for name in names if not source.get(name, "").strip()]


def _key(provider: str, env: Mapping[str, str] | None) -> str:
    source = os.environ if env is None else env
    name = REQUIRED_KEYS[provider]
    value = source.get(name, "").strip()
    if not value:
        raise SpeechConfigError(f"{name} is not set")
    return value


def build_stt(options: SpeechOptions, env: Mapping[str, str] | None = None) -> stt.STT[Any]:
    if options.stt_provider == "deepgram":
        from livekit.plugins import deepgram

        return deepgram.STT(
            api_key=_key("deepgram", env),
            model=options.stt_model,
            language=options.stt_language,
            interim_results=True,  # partial transcripts feed turn detection and barge-in
        )
    raise SpeechConfigError(f"unknown STT provider {options.stt_provider!r}")


def build_tts(
    options: SpeechOptions,
    env: Mapping[str, str] | None = None,
    *,
    http_session: Any = None,  # only for use outside a LiveKit job (the simulator)
) -> tts.TTS[Any]:
    if options.tts_provider == "cartesia":
        from livekit.plugins import cartesia

        kwargs: dict[str, Any] = {
            "api_key": _key("cartesia", env),
            "language": options.tts_language,
        }
        if options.tts_model:
            kwargs["model"] = options.tts_model
        if options.tts_voice:
            kwargs["voice"] = options.tts_voice
        if http_session is not None:
            kwargs["http_session"] = http_session
        return cartesia.TTS(**kwargs)
    raise SpeechConfigError(f"unknown TTS provider {options.tts_provider!r}")


def load_vad() -> vad.VAD:
    """Voice activity detection runs locally (no key); loaded once per worker process."""
    from livekit.plugins import silero

    return silero.VAD.load()
