"""WP-12.7 retrieval in a real turn: only approved entries of the active version, recorded."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import FakeModelProvider, FakeVoiceTransport
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PASSWORD, PgEnv, admin_fetch, bearer, signup
from tests.integration.test_voice import GREETING_TURN, VoiceEnv, _start_session, _turn, _worker


def _env(db: PgEnv, make_settings: SettingsFactory, *, enabled: bool) -> Any:
    settings = make_settings(
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
        database_app_role=db.app_role,
        playbooks_enabled=enabled,
    )
    app = create_app(settings)
    transport, model = FakeVoiceTransport(), FakeModelProvider(replies=[])
    app.state.voice_transport = transport
    app.state.model_gateway = ModelGateway(
        model,
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    return TestClient(app, raise_server_exceptions=False), transport, model


@pytest.fixture
def voice(db: PgEnv, make_settings: SettingsFactory) -> Iterator[VoiceEnv]:
    client, transport, model = _env(db, make_settings, enabled=True)
    with client:
        yield VoiceEnv(client=client, transport=transport, model=model)


def _active_seed_playbook(env: VoiceEnv, owner: Any, approve: list[int]) -> list[dict[str, Any]]:
    c, h = env.client, bearer(owner)
    agent_id = c.get("/api/v1/agents/default", headers=h).json()["id"]
    draft = c.post("/api/v1/playbooks", json={"agent_id": agent_id, "seed": True}, headers=h)
    version_id = draft.json()["id"]
    entries: list[dict[str, Any]] = c.get(f"/api/v1/playbooks/{version_id}", headers=h).json()[
        "entries"
    ]
    for position in approve:
        entry_id = entries[position]["id"]
        c.post(f"/api/v1/playbooks/{version_id}/entries/{entry_id}/approve", headers=h)
    assert c.post(f"/api/v1/playbooks/{version_id}/activate", headers=h).status_code == 200
    return entries


def _call_turn(env: VoiceEnv, owner: Any) -> str:
    call_id, token = _start_session(env, owner)
    env.client.post(f"/internal/v1/calls/{call_id}/start", headers=_worker(token))
    env.model.replies.append("We help small teams with health cover.")
    assert _turn(env, call_id, token, GREETING_TURN).status_code == 200
    return call_id


def test_turn_offers_only_approved_entries_for_the_stage(voice: VoiceEnv, db: PgEnv) -> None:
    owner = signup(voice.client, "owner@example.com", "Acme")
    entries = _active_seed_playbook(voice, owner, approve=[0, 2, 19])
    assert entries[0]["stage"] == "opening" and entries[19]["stage"] == "discovery"
    assert entries[2]["stage"] is None and entries[12]["stage"] is None  # 12 stays proposed

    call_id = _call_turn(voice, owner)  # the turn moves the call to discovery

    request = voice.model.requests[-1]
    prompt, stable = request.system, request.system[: request.system_cache_prefix]
    assert "# Ideas from expert callers" in prompt and "Ideas from expert" not in stable
    assert prompt.index("# Honesty") < prompt.index("# Ideas from expert callers")
    assert entries[19]["says"] in prompt and entries[2]["says"] in prompt
    assert entries[0]["says"] not in prompt  # approved, but for another stage
    assert entries[12]["says"] not in prompt  # right stage (any), but not approved

    offers = admin_fetch(db, "SELECT call_id, turn, entry_ids, retrieval_ms FROM playbook_offers")
    assert len(offers) == 1 and str(offers[0]["call_id"]) == call_id
    assert offers[0]["turn"] == 1
    assert [str(i) for i in offers[0]["entry_ids"]] == [entries[19]["id"], entries[2]["id"]]
    assert 0 <= offers[0]["retrieval_ms"] < 1000  # measured per turn; target under 50 ms


def test_off_means_no_playbook_in_the_prompt(db: PgEnv, make_settings: SettingsFactory) -> None:
    on_client, transport, model = _env(db, make_settings, enabled=True)
    with on_client:
        owner = signup(on_client, "owner@example.com", "Acme")
        _active_seed_playbook(
            VoiceEnv(client=on_client, transport=transport, model=model), owner, approve=[19]
        )
    off_client, transport, model = _env(db, make_settings, enabled=False)
    with off_client:
        env = VoiceEnv(client=off_client, transport=transport, model=model)
        tokens = off_client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": PASSWORD},
        ).json()
        _call_turn(env, tokens)
        assert "Ideas from expert callers" not in model.requests[-1].system
    assert admin_fetch(db, "SELECT count(*) AS n FROM playbook_offers")[0]["n"] == 0


def test_no_active_playbook_no_offer(voice: VoiceEnv, db: PgEnv) -> None:
    owner = signup(voice.client, "owner@example.com", "Acme")
    _call_turn(voice, owner)
    assert "Ideas from expert callers" not in voice.model.requests[-1].system
    assert admin_fetch(db, "SELECT count(*) AS n FROM playbook_offers")[0]["n"] == 0
