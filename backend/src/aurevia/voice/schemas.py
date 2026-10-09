"""Request and response bodies for agents, voice sessions and the worker call API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- Agents ------------------------------------------------------------------------------


class AgentUpdate(_Body):
    """Tenant-supplied agent configuration. Bounded so it cannot swamp the prompt."""

    name: str = Field(min_length=1, max_length=80)
    company_name: str = Field(min_length=1, max_length=200)
    company_description: str = Field(min_length=1, max_length=4000)
    objective: str = Field(min_length=1, max_length=1000)
    greeting: str = Field(min_length=1, max_length=500)
    language: str = Field(default="en-IN", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    voice: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    company_name: str
    company_description: str
    objective: str
    greeting: str
    language: str
    voice: str | None


# --- Voice sessions and calls ------------------------------------------------------------


class VoiceSessionRequest(_Body):
    # The lead being called; optional for ad-hoc test calls (no memory is kept without one).
    lead_id: uuid.UUID | None = None


class VoiceSessionResponse(BaseModel):
    call_id: uuid.UUID
    room: str
    livekit_url: str
    token: str


class CallUsage(BaseModel):
    llm_input_tokens: int
    llm_output_tokens: int
    llm_turns: int
    llm_interrupted_turns: int
    stt_seconds: float
    tts_characters: int


class LatencyResponse(BaseModel):
    """Prospect stops speaking -> agent's first audio, against the Phase 3 targets."""

    agent_turns: int
    measured_turns: int
    interrupted_turns: int
    e2e_p50_ms: int | None
    e2e_p95_ms: int | None
    llm_ttft_p50_ms: int | None
    tts_ttfb_p50_ms: int | None
    end_of_turn_delay_p50_ms: int | None
    target_p50_ms: int
    target_p95_ms: int
    meets_target: bool | None


class CallResponse(BaseModel):
    id: uuid.UUID
    channel: str
    status: str
    sales_state: str
    turn_count: int
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    usage: CallUsage
    latency: LatencyResponse


# --- Worker call API ---------------------------------------------------------------------


class CallStartResponse(BaseModel):
    agent_name: str
    greeting: str
    language: str
    voice: str | None


class UtteranceIn(_Body):
    role: Literal["prospect", "agent"]
    text: str = Field(max_length=4000)


class TurnRequest(_Body):
    history: list[UtteranceIn] = Field(min_length=1, max_length=200)


class UsageReport(_Body):
    kind: Literal["stt", "tts"]
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    audio_seconds: float = Field(default=0.0, ge=0, le=6 * 3600)
    characters: int = Field(default=0, ge=0, le=5_000_000)


class CallEndRequest(_Body):
    reason: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    # True when the call ended because something broke (worker or vendor failure).
    failed: bool = False


_MS = Field(default=None, ge=0, le=600_000)


class TurnMetricIn(_Body):
    seq: int = Field(ge=0, le=100_000)
    role: Literal["prospect", "agent"]
    interrupted: bool = False
    transcription_delay_ms: int | None = _MS
    end_of_turn_delay_ms: int | None = _MS
    e2e_latency_ms: int | None = _MS
    llm_ttft_ms: int | None = _MS
    tts_ttfb_ms: int | None = _MS


class TurnMetricsReport(_Body):
    turns: list[TurnMetricIn] = Field(min_length=1, max_length=1000)
