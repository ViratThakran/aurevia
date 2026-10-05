"""Worker configuration.

``AUREVIA_*`` variables are read here. LiveKit (``LIVEKIT_URL``, ``LIVEKIT_API_KEY``,
``LIVEKIT_API_SECRET``), Deepgram (``DEEPGRAM_API_KEY``) and Cartesia (``CARTESIA_API_KEY``)
read their own variables; those keys exist only in the worker, never in the backend.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUREVIA_", extra="ignore", frozen=True)

    backend_url: str
    agent_name: str = "aurevia-voice"  # must match the backend's AUREVIA_LIVEKIT_AGENT_NAME

    stt_model: str = "nova-3"
    # "multi" lets Deepgram follow code-switching (e.g. English and Hindi in one sentence).
    stt_language: str = "multi"
    tts_model: str | None = None  # None: the Cartesia plugin's default model
    tts_voice: str | None = None  # used when the tenant's agent has no voice set
