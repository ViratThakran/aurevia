"""Worker configuration.

``AUREVIA_*`` variables are read here. LiveKit (``LIVEKIT_URL``, ``LIVEKIT_API_KEY``,
``LIVEKIT_API_SECRET``), Deepgram (``DEEPGRAM_API_KEY``) and Cartesia (``CARTESIA_API_KEY``)
read their own variables; those keys exist only in the worker, never in the backend.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUREVIA_", extra="ignore", frozen=True)

    backend_url: str
    agent_name: str = "aurevia-voice"  # must match the backend's AUREVIA_LIVEKIT_AGENT_NAME

    # Which speech vendors to use; adapters live in speech_providers.py.
    stt_provider: Literal["deepgram"] = "deepgram"
    tts_provider: Literal["cartesia"] = "cartesia"

    stt_model: str = "nova-3"
    # "multi" lets Deepgram follow code-switching (e.g. English and Hindi in one sentence).
    stt_language: str = "multi"
    tts_model: str | None = None  # None: the Cartesia plugin's default model
    tts_voice: str | None = None  # used when the tenant's agent has no voice set

    # --- Turn handling (Phase 3 tuning). Defaults equal LiveKit's own unless noted; change
    # them only with measured turn_metrics to compare against.
    # "dynamic" adapts the end-of-turn wait to how this caller pauses.
    endpointing_mode: Literal["fixed", "dynamic"] = "fixed"
    # Silence before the prospect's turn counts as finished. Too low: the agent answers
    # before the transcript is final ("transcript arrives after turn has been committed").
    endpointing_min_delay: float = Field(default=0.5, ge=0.1, le=3.0)
    # Used when LiveKit's end-of-turn model thinks the prospect is not finished. LiveKit's
    # default is 3.0 s; simulations (2026-10-09) showed it misjudging short questions and
    # leaving 3 s of dead air, so the ceiling is 1.5 s.
    endpointing_max_delay: float = Field(default=1.5, ge=0.5, le=10.0)
    # Start the model while the prospect may still be talking; cancelled if they continue.
    # Lowers latency; cancelled starts are recorded as interrupted LLM turns.
    preemptive_generation: bool = True
    # Prospect speech needed to interrupt the agent (barge-in).
    interruption_min_duration: float = Field(default=0.5, ge=0.1, le=3.0)

    # --- Silence handling (Phase 3). After this many seconds with nobody speaking, the agent
    # re-prompts; after the re-prompts are used up it says goodbye and ends the call.
    silence_timeout_seconds: float = Field(default=15.0, ge=3.0, le=120.0)
    silence_reprompts: int = Field(default=1, ge=0, le=3)
    silence_reprompt_text: str = Field(default="Are you still there?", min_length=1, max_length=200)
    silence_goodbye_text: str = Field(
        default="It seems we've lost each other. I'll let you go for now. Goodbye!",
        min_length=1,
        max_length=300,
    )
