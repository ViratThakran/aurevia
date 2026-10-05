"""Application configuration.

All configuration comes from environment variables (prefix ``AUREVIA_``) or a local
``.env`` file. Nothing sensitive has a default value. Invalid configuration fails fast at
startup, and error messages never echo secret values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Environments where secrets must be explicitly provided and debug mode is forbidden.
DEPLOYED_ENVIRONMENTS: frozenset[str] = frozenset({"staging", "production"})

MIN_JWT_SECRET_LENGTH = 32


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

    # --- AI Model Gateway (Phase 2) ---
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    # Spoken replies are short; low effort keeps time-to-first-word down.
    llm_effort: Literal["low", "medium", "high"] = "low"
    llm_max_tokens: int = Field(default=4096, ge=256, le=32000)
    llm_first_token_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    llm_total_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    # Explicit fallback policy. "server_default": if the model declines a request, the API
    # re-runs it on Anthropic's recommended fallback model; the model that actually answered
    # is recorded on every usage event. "none": a declined request stays declined.
    llm_fallback_policy: Literal["none", "server_default"] = "server_default"

    # --- Voice transport: LiveKit (Phase 2) ---
    livekit_url: str | None = None  # server-to-server, e.g. http://livekit:7880
    livekit_public_url: str | None = None  # what browsers connect to, e.g. ws://localhost:7880
    livekit_api_key: str | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_agent_name: str = "aurevia-voice"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "database_url",
        "migration_database_url",
        "jwt_secret",
        "anthropic_api_key",
        "livekit_api_secret",
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
    def _check_deployed_environment(self) -> Self:
        if self.environment not in DEPLOYED_ENVIRONMENTS:
            return self
        missing = [name for name in ("database_url", "jwt_secret") if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{', '.join(missing)} required when environment={self.environment}")
        if self.debug:
            raise ValueError(f"debug must be disabled when environment={self.environment}")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

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
