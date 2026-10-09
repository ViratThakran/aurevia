"""Provider selection, provider configuration and secret handling."""

from __future__ import annotations

import io
import json
import logging

import pytest
from pydantic import ValidationError

from aurevia.config import DEFAULT_MODELS, Settings
from aurevia.logging import configure_logging
from aurevia.main import create_app
from aurevia.providers.anthropic_model import AnthropicModelProvider
from aurevia.providers.gemini_model import GeminiModelProvider
from aurevia.providers.registry import build_model_provider, missing_key_variable
from tests.conftest import TEST_DATABASE_URL, TEST_JWT_SECRET, SettingsFactory

# Obviously fake, test-only values.
GEMINI_KEY = "gemini-test-key-0000000000"
ANTHROPIC_KEY = "sk-ant-test-key-0000000000"


def test_gemini_is_the_default_provider(make_settings: SettingsFactory) -> None:
    settings = make_settings()
    assert settings.ai_provider == "gemini"
    assert settings.resolved_llm_model == DEFAULT_MODELS["gemini"]
    assert settings.resolved_fallback_policy == "none"


def test_gemini_selected_needs_no_anthropic_key(make_settings: SettingsFactory) -> None:
    settings = make_settings(ai_provider="gemini", gemini_api_key=GEMINI_KEY)
    assert settings.anthropic_api_key is None
    assert isinstance(build_model_provider(settings), GeminiModelProvider)
    assert create_app(settings).state.model_gateway is not None


def test_anthropic_selection_is_configuration_only(make_settings: SettingsFactory) -> None:
    settings = make_settings(ai_provider="anthropic", anthropic_api_key=ANTHROPIC_KEY)
    provider = build_model_provider(settings)
    assert isinstance(provider, AnthropicModelProvider)
    assert settings.resolved_llm_model == DEFAULT_MODELS["anthropic"]
    assert settings.resolved_fallback_policy == "server_default"
    gateway = create_app(settings).state.model_gateway
    assert gateway is not None and gateway.model == DEFAULT_MODELS["anthropic"]


def test_other_providers_key_does_not_count(make_settings: SettingsFactory) -> None:
    # Gemini selected but only an Anthropic key: the model stays off, nothing falls back.
    settings = make_settings(ai_provider="gemini", anthropic_api_key=ANTHROPIC_KEY)
    assert build_model_provider(settings) is None
    assert missing_key_variable(settings) == "AUREVIA_GEMINI_API_KEY"


def test_missing_key_disables_the_model_and_logs_the_variable_name(
    make_settings: SettingsFactory, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        app = create_app(make_settings(ai_provider="gemini"))
    assert app.state.model_gateway is None
    warning = next(r for r in caplog.records if "AI model not configured" in r.getMessage())
    assert warning.fields["missing"] == "AUREVIA_GEMINI_API_KEY"  # type: ignore[attr-defined]


def test_model_override(make_settings: SettingsFactory) -> None:
    settings = make_settings(gemini_api_key=GEMINI_KEY, llm_model="gemini-3.5-flash")
    assert settings.resolved_llm_model == "gemini-3.5-flash"
    assert make_settings(llm_model="").resolved_llm_model == DEFAULT_MODELS["gemini"]


def test_unknown_provider_is_rejected(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(ai_provider="openai")


def test_server_fallback_is_refused_for_gemini(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match="not supported by gemini"):
        make_settings(ai_provider="gemini", llm_fallback_policy="server_default")
    allowed = make_settings(ai_provider="anthropic", llm_fallback_policy="none")
    assert allowed.resolved_fallback_policy == "none"


def test_production_requires_the_selected_providers_key(make_settings: SettingsFactory) -> None:
    base = {
        "environment": "production",
        "database_url": TEST_DATABASE_URL,
        "jwt_secret": TEST_JWT_SECRET,
    }
    with pytest.raises(ValidationError, match="gemini_api_key required"):
        make_settings(**base)
    make_settings(**base, gemini_api_key=GEMINI_KEY)  # does not raise
    with pytest.raises(ValidationError, match="anthropic_api_key required"):
        make_settings(**base, ai_provider="anthropic", gemini_api_key=GEMINI_KEY)


def test_environment_variables_select_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUREVIA_AI_PROVIDER", "anthropic")
    monkeypatch.setenv("AUREVIA_ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    settings = Settings(_env_file=None)
    assert settings.ai_provider == "anthropic"
    assert settings.provider_api_key is not None


# --- Secret masking ----------------------------------------------------------------------


def test_settings_never_render_secrets(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        gemini_api_key=GEMINI_KEY,
        anthropic_api_key=ANTHROPIC_KEY,
        jwt_secret=TEST_JWT_SECRET,
        database_url=TEST_DATABASE_URL,
    )
    rendered = " ".join([repr(settings), str(settings), settings.model_dump_json()])
    for secret in (GEMINI_KEY, ANTHROPIC_KEY, TEST_JWT_SECRET, "test_pw"):
        assert secret not in rendered


def test_secret_values_include_database_passwords(make_settings: SettingsFactory) -> None:
    settings = make_settings(database_url=TEST_DATABASE_URL, gemini_api_key=GEMINI_KEY)
    values = settings.secret_values()
    assert GEMINI_KEY in values and "test_pw" in values


def test_logs_redact_secrets_in_messages_fields_and_tracebacks() -> None:
    stream = io.StringIO()
    configure_logging("INFO", json_output=True, redact_values=[GEMINI_KEY, "short"])
    root = logging.getLogger()
    handler = root.handlers[-1]
    original_stream = handler.stream  # type: ignore[attr-defined]
    handler.stream = stream  # type: ignore[attr-defined]
    try:
        log = logging.getLogger("test.secrets")
        log.warning("key=%s", GEMINI_KEY, extra={"fields": {"header": f"Bearer {GEMINI_KEY}"}})
        try:
            raise RuntimeError(f"upstream rejected {GEMINI_KEY}")
        except RuntimeError:
            log.exception("provider failed")
    finally:
        handler.stream = original_stream  # type: ignore[attr-defined]
        configure_logging("INFO", json_output=True)
    output = stream.getvalue()
    assert GEMINI_KEY not in output
    assert output.count("[REDACTED]") == 3
    lines = [json.loads(line) for line in output.splitlines()]
    assert lines[0]["header"] == "Bearer [REDACTED]"
