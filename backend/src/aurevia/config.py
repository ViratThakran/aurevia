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

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url", "migration_database_url", "jwt_secret", mode="before")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
