from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aurevia import __version__
from aurevia.main import create_app
from tests.conftest import TEST_DATABASE_URL, TEST_JWT_SECRET, SettingsFactory


def test_app_factory_returns_configured_app(app: FastAPI) -> None:
    assert isinstance(app, FastAPI)
    assert app.title == "Aurevia API"
    assert app.version == __version__
    assert app.state.settings.environment == "test"


def test_lifespan_runs_and_logs_startup(app: FastAPI, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), TestClient(app):
        pass
    messages = [r.getMessage() for r in caplog.records]
    assert "Aurevia starting" in messages
    assert "Aurevia stopped" in messages


def test_apps_are_independent(make_settings: SettingsFactory) -> None:
    first = create_app(make_settings())
    second = create_app(make_settings())
    assert first is not second
    assert first.state.readiness_checks is not second.state.readiness_checks


def test_openapi_and_docs_available_outside_production(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_openapi_and_docs_disabled_in_production(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        environment="production", jwt_secret=TEST_JWT_SECRET, database_url=TEST_DATABASE_URL
    )
    with TestClient(create_app(settings)) as prod_client:
        assert prod_client.get("/openapi.json").status_code == 404
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/health").status_code == 200


def test_v1_prefix_is_mounted(client: TestClient) -> None:
    assert client.get("/api/v1/health/ready").status_code == 200
    # Readiness is only under the versioned prefix.
    assert client.get("/health/ready").status_code == 404
