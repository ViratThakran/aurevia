from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aurevia.api.v1 import health as v1_health
from aurevia.main import create_app
from tests.conftest import SettingsFactory


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_with_no_registered_checks(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


def test_readiness_ok_when_all_checks_pass(app: FastAPI, client: TestClient) -> None:
    async def healthy() -> bool:
        return True

    app.state.readiness_checks["dependency"] = healthy
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"dependency": "ok"}}


def test_readiness_503_when_a_check_fails(app: FastAPI, client: TestClient) -> None:
    async def healthy() -> bool:
        return True

    async def unhealthy() -> bool:
        return False

    app.state.readiness_checks.update({"good": healthy, "bad": unhealthy})
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"good": "ok", "bad": "failed"}}


def test_readiness_does_not_leak_check_exception_details(app: FastAPI, client: TestClient) -> None:
    async def exploding() -> bool:
        raise RuntimeError("postgresql://user:hunter2@db/prod unreachable")

    app.state.readiness_checks["db"] = exploding
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"db": "failed"}
    assert "hunter2" not in response.text


def test_readiness_times_out_slow_checks(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v1_health, "READINESS_CHECK_TIMEOUT_SECONDS", 0.05)

    async def slow() -> bool:
        await asyncio.sleep(1)
        return True

    app.state.readiness_checks["slow"] = slow
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"slow": "failed"}


def test_readiness_fails_when_database_is_unreachable(make_settings: SettingsFactory) -> None:
    # Port 1 on loopback: nothing listens, the connection is refused immediately.
    settings = make_settings(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/db")
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "failed"}}
