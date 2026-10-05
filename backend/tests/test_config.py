from __future__ import annotations

import pytest
from pydantic import ValidationError

from aurevia.config import Settings, get_settings
from tests.conftest import TEST_DATABASE_URL, TEST_JWT_SECRET, SettingsFactory


def test_defaults_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.database_url is None
    assert settings.jwt_secret is None


def test_loads_from_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUREVIA_ENVIRONMENT", "development")
    monkeypatch.setenv("AUREVIA_LOG_LEVEL", "debug")  # case-insensitive
    monkeypatch.setenv("AUREVIA_JWT_SECRET", TEST_JWT_SECRET)
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.log_level == "DEBUG"
    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value() == TEST_JWT_SECRET


def test_unprefixed_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "x")
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.jwt_secret is None


def test_unknown_aurevia_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUREVIA_SOMETHING_ELSE", "1")
    Settings(_env_file=None)  # must not raise


def test_rejects_unknown_environment(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="prod")


def test_rejects_unknown_log_level(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="chatty")


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_require_secrets(
    make_settings: SettingsFactory, environment: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        make_settings(environment=environment)
    message = str(exc_info.value)
    assert "database_url" in message
    assert "jwt_secret" in message


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_accept_complete_config(
    make_settings: SettingsFactory, environment: str
) -> None:
    settings = make_settings(
        environment=environment, jwt_secret=TEST_JWT_SECRET, database_url=TEST_DATABASE_URL
    )
    assert settings.environment == environment


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_debug_forbidden_in_deployed_environments(
    make_settings: SettingsFactory, environment: str
) -> None:
    with pytest.raises(ValidationError, match="debug must be disabled"):
        make_settings(
            environment=environment,
            debug=True,
            jwt_secret=TEST_JWT_SECRET,
            database_url=TEST_DATABASE_URL,
        )


def test_debug_allowed_locally(make_settings: SettingsFactory) -> None:
    assert make_settings(environment="local", debug=True).debug is True


def test_rejects_short_jwt_secret_without_echoing_it(make_settings: SettingsFactory) -> None:
    short_secret = "tooshort-but-recognisable"
    with pytest.raises(ValidationError) as exc_info:
        make_settings(jwt_secret=short_secret)
    assert "at least 32" in str(exc_info.value)
    assert short_secret not in str(exc_info.value)


def test_rejects_non_postgres_database_url_without_echoing_it(
    make_settings: SettingsFactory,
) -> None:
    bad_url = "mysql://user:s3cretpw@host/db"
    with pytest.raises(ValidationError) as exc_info:
        make_settings(database_url=bad_url)
    assert "PostgreSQL" in str(exc_info.value)
    assert "s3cretpw" not in str(exc_info.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_secrets_are_treated_as_unset(make_settings: SettingsFactory, blank: str) -> None:
    settings = make_settings(jwt_secret=blank, database_url=blank)
    assert settings.jwt_secret is None
    assert settings.database_url is None


def test_blank_secrets_still_fail_in_production(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="production", jwt_secret="", database_url="")


def test_secrets_are_masked_in_repr_and_dumps(make_settings: SettingsFactory) -> None:
    settings = make_settings(jwt_secret=TEST_JWT_SECRET, database_url=TEST_DATABASE_URL)
    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    assert TEST_JWT_SECRET not in rendered
    assert "test_pw" not in rendered


def test_settings_are_immutable(make_settings: SettingsFactory) -> None:
    settings = make_settings()
    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_migration_url_must_be_postgres(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(migration_database_url="mysql://x@y/z")
    assert make_settings(migration_database_url="").migration_database_url is None


@pytest.mark.parametrize("role", ["Aurevia", "app; DROP TABLE users", "1app", "a" * 64])
def test_database_app_role_must_be_a_safe_identifier(
    make_settings: SettingsFactory, role: str
) -> None:
    with pytest.raises(ValidationError):
        make_settings(database_app_role=role)


def test_token_lifetimes_are_bounded(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(access_token_ttl_seconds=10)
    with pytest.raises(ValidationError):
        make_settings(access_token_ttl_seconds=86400)
    assert make_settings().access_token_ttl_seconds == 900
