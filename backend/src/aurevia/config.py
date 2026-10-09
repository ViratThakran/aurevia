"""Application configuration.

All configuration comes from environment variables (prefix ``AUREVIA_``) or a local
``.env`` file. Nothing sensitive has a default value. Invalid configuration fails fast at
startup, and error messages never echo secret values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Environments where secrets must be explicitly provided and debug mode is forbidden.
DEPLOYED_ENVIRONMENTS: frozenset[str] = frozenset({"staging", "production"})

MIN_JWT_SECRET_LENGTH = 32

AIProvider = Literal["gemini", "anthropic"]

# Default model per provider when AUREVIA_LLM_MODEL is unset.
DEFAULT_MODELS: dict[str, str] = {
    # Reliable ~1.1-1.5 s to first token (2026-10-08); flash-lite was faster (~0.9 s) but
    # repeatedly returned 504s on this account, so it is a fallback candidate instead.
    "gemini": "gemini-3.5-flash",
    "anthropic": "claude-opus-5-5",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUREVIA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Environment = "local"
    debug: bool = False
    log_level: LogLevel = "INFO"
    log_json: bool = True

    # Secrets: no defaults, never logged. Optional for running the app without a database
    # (e.g. unit tests), but mandatory in staging/production.
    # `database_url` connects as the application role, which is subject to row-level security.
    # `migration_database_url` connects as the schema owner and is used only by Alembic.
    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    jwt_secret: SecretStr | None = None

    # The role the application connects as. Migrations grant it table privileges; it must not
    # own the tables, be a superuser or have BYPASSRLS.
    database_app_role: str = Field(default="aurevia_app", pattern=r"^[a-z_][a-z0-9_]{0,62}$")

    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=30 * 24 * 3600, ge=3600)
    # Lifetime of the per-call credential the voice worker uses for internal endpoints.
    call_token_ttl_seconds: int = Field(default=2 * 3600, ge=300, le=12 * 3600)

    # Browser origins allowed to call the API (e.g. the voice test page).
    cors_origins: list[str] = Field(default_factory=list)

    # --- AI Model Gateway ---
    # Which model provider the gateway uses. Only the selected provider's key is needed.
    ai_provider: AIProvider = "gemini"
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Unset: the selected provider's default (DEFAULT_MODELS). Pinned names only, never
    # "latest" aliases, so the model cannot change underneath us.
    llm_model: str | None = Field(default=None, min_length=1, max_length=100)
    # Spoken replies are short; low effort keeps time-to-first-word down.
    llm_effort: Literal["low", "medium", "high"] = "low"
    llm_max_tokens: int = Field(default=4096, ge=256, le=32000)
    llm_first_token_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_total_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    # Explicit fallback policy. "server_default": if the model declines a request, the
    # provider re-runs it on its recommended fallback model (Anthropic only); the model that
    # actually answered is recorded on every usage event. "none": a declined request stays
    # declined. Unset: "server_default" for Anthropic, "none" for Gemini.
    llm_fallback_policy: Literal["none", "server_default"] | None = None
    # Gateway-level fallback (any provider): same-provider models tried in order when the
    # current one times out, is unavailable or is rate limited before its first word. Empty
    # by default. The usage record shows every model attempted and the one that answered.
    llm_fallback_models: list[str] = Field(default_factory=list, max_length=3)

    # --- Memory (Phase 4) ---
    # Full transcripts are deleted this many days after they are written (DPDP data
    # minimisation); extracted lead facts are kept separately until removed.
    transcript_retention_days: int = Field(default=90, ge=1, le=3650)
    # Facts below this confidence are stored but never shown to the model on later calls.
    memory_min_confidence: float = Field(default=0.6, ge=0, le=1)
    memory_max_facts_in_prompt: int = Field(default=12, ge=0, le=50)

    # --- Voice transport: LiveKit (Phase 2) ---
    livekit_url: str | None = None  # server-to-server, e.g. http://livekit:7880
    livekit_public_url: str | None = None  # what browsers connect to, e.g. ws://localhost:7880
    livekit_api_key: str | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_agent_name: str = "aurevia-voice"

    # --- Telephony + compliance gate (Phase 6) ---
    # "test" dials only the tenant's registered test numbers. "live" also needs a policy pack
    # reviewed by counsel; until then the gate blocks every live call.
    telephony_mode: Literal["test", "live"] = "test"
    # Phone calls are enabled only when a provider and its outbound trunk are configured.
    telephony_provider: Literal["livekit_sip"] | None = None
    livekit_sip_outbound_trunk_id: str | None = Field(default=None, max_length=100)
    # Rooms created by the inbound SIP dispatch rule start with this prefix.
    inbound_room_prefix: str = Field(default="aurevia-in-", min_length=3, max_length=40)
    compliance_policy_pack: Literal["india"] = "india"
    ring_timeout_seconds: int = Field(default=40, ge=10, le=120)
    max_test_numbers: int = Field(default=5, ge=1, le=20)

    # --- Plans and campaigns (Phase 8) ---
    # The default plan for tenants without one (None = unlimited). No payments are taken.
    plan_default_monthly_calls: int | None = Field(default=200, ge=1)
    plan_default_monthly_minutes: int | None = Field(default=500, ge=1)
    plan_default_max_concurrent_calls: int = Field(default=2, ge=1, le=100)
    # The automatic campaign dialer runs only when switched on here AND per campaign.
    campaign_scheduler_enabled: bool = False
    campaign_scheduler_interval_seconds: float = Field(default=30.0, ge=5.0, le=3600.0)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "database_url",
        "migration_database_url",
        "jwt_secret",
        "anthropic_api_key",
        "gemini_api_key",
        "livekit_api_secret",
        "llm_model",
        "llm_fallback_policy",
        "telephony_provider",
        "livekit_sip_outbound_trunk_id",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_unset(cls, value: Any) -> Any:
        # `.env.example` ships blank placeholders; treat them as "not set".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", "migration_database_url", mode="after")
    @classmethod
    def _check_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith("postgresql"):
            raise ValueError("database URLs must be PostgreSQL URLs (postgresql://...)")
        return value

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def _check_jwt_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"jwt_secret must be at least {MIN_JWT_SECRET_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def _check_fallback_supported(self) -> Self:
        if self.llm_fallback_policy == "server_default" and self.ai_provider != "anthropic":
            # Refuse rather than silently ignore: fallback must be an explicit, real policy.
            raise ValueError(
                f"llm_fallback_policy=server_default is not supported by {self.ai_provider}"
            )
        return self

    @model_validator(mode="after")
    def _check_deployed_environment(self) -> Self:
        if self.environment not in DEPLOYED_ENVIRONMENTS:
            return self
        missing = [name for name in ("database_url", "jwt_secret") if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{', '.join(missing)} required when environment={self.environment}")
        if self.debug:
            raise ValueError(f"debug must be disabled when environment={self.environment}")
        if self.provider_api_key is None:
            raise ValueError(
                f"{self.ai_provider}_api_key required when environment={self.environment}"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.ai_provider]

    @property
    def resolved_fallback_policy(self) -> Literal["none", "server_default"]:
        if self.llm_fallback_policy is not None:
            return self.llm_fallback_policy
        return "server_default" if self.ai_provider == "anthropic" else "none"

    @property
    def provider_api_key(self) -> SecretStr | None:
        """The key of the selected AI provider; other providers' keys are never needed."""
        keys = {"gemini": self.gemini_api_key, "anthropic": self.anthropic_api_key}
        return keys[self.ai_provider]

    def secret_values(self) -> list[str]:
        """Every configured secret, for redaction from logs. Never log or return this."""
        secrets = [
            self.database_url,
            self.migration_database_url,
            self.jwt_secret,
            self.gemini_api_key,
            self.anthropic_api_key,
            self.livekit_api_secret,
        ]
        values = [s.get_secret_value() for s in secrets if s is not None]
        for url in (self.database_url, self.migration_database_url):
            if url is not None and (password := urlsplit(url.get_secret_value()).password):
                values.append(password)  # drivers may print the password on its own
        return values

    @property
    def voice_configured(self) -> bool:
        return None not in (
            self.livekit_url,
            self.livekit_public_url,
            self.livekit_api_key,
            self.livekit_api_secret,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
