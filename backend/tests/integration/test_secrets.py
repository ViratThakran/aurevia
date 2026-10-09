"""No configured secret may ever reach an API client (browser, worker or otherwise)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import FakeModelProvider, FakeVoiceTransport
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PgEnv, bearer, signup

# Distinctive, obviously fake values: if any shows up in a response, it leaked.
SENTINELS = {
    "gemini_api_key": "SENTINEL-gemini-key-7f3a9c",
    "anthropic_api_key": "SENTINEL-anthropic-key-2b8e1d",
    "livekit_api_secret": "SENTINEL-livekit-secret-5c4f0a",
}


@pytest.fixture
def client(db: PgEnv, make_settings: SettingsFactory) -> Iterator[TestClient]:
    settings = make_settings(
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
        database_app_role=db.app_role,
        livekit_url="http://livekit.test",
        livekit_public_url="ws://livekit.test",
        livekit_api_key="devkey",
        **SENTINELS,
    )
    app = create_app(settings)
    app.state.voice_transport = FakeVoiceTransport()
    app.state.model_gateway = ModelGateway(
        FakeModelProvider(replies=[]),
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_no_secret_appears_in_any_response(client: TestClient, db: PgEnv) -> None:
    tokens = signup(client, "owner@example.com", "Acme")
    session = client.post("/api/v1/voice/sessions", headers=bearer(tokens))
    assert session.status_code == 201
    call_id = session.json()["call_id"]

    responses = [
        client.get("/openapi.json"),
        client.get("/health"),
        client.get("/api/v1/health/ready"),
        client.get("/api/v1/auth/me", headers=bearer(tokens)),
        client.get("/api/v1/tenant", headers=bearer(tokens)),
        client.get("/api/v1/agents/default", headers=bearer(tokens)),
        client.get(f"/api/v1/voice/calls/{call_id}", headers=bearer(tokens)),
        client.get("/api/v1/does-not-exist"),
        client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope"}),
        session,
    ]
    for response in responses:
        exposed = response.text + str(dict(response.headers))
        for name, value in SENTINELS.items():
            assert value not in exposed, f"{name} leaked from {response.request.url.path}"
        assert TEST_JWT_SECRET not in exposed
