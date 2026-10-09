"""Phase 4 gate: a second call recalls the first, tenant-safe. Plus transcript retention."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import FakeModelProvider, FakeVoiceTransport
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PgEnv, admin_execute, admin_fetch, bearer, signup


@dataclass
class Env:
    client: TestClient
    transport: FakeVoiceTransport
    model: FakeModelProvider


@pytest.fixture
def env(db: PgEnv, make_settings: SettingsFactory) -> Iterator[Env]:
    app = create_app(
        make_settings(
            database_url=db.app_url, jwt_secret=TEST_JWT_SECRET, database_app_role=db.app_role
        )
    )
    transport, model = FakeVoiceTransport(), FakeModelProvider(replies=[])
    app.state.voice_transport = transport
    app.state.model_gateway = ModelGateway(
        model,
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Env(client, transport, model)


def _worker(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _call(env: Env, tokens: dict[str, Any], lead_id: str | None) -> tuple[str, str]:
    body = {"lead_id": lead_id} if lead_id else {}
    response = env.client.post("/api/v1/voice/sessions", json=body, headers=bearer(tokens))
    assert response.status_code == 201, response.text
    call_id = response.json()["call_id"]
    token = json.loads(env.transport.rooms[-1][2])["call_token"]
    assert (
        env.client.post(f"/internal/v1/calls/{call_id}/start", headers=_worker(token)).status_code
        == 200
    )
    return call_id, token


FACTS = {
    "facts": [
        {"kind": "business", "fact": "Runs a 40-person logistics firm in Pune.", "confidence": 0.9},
        {"kind": "objection", "fact": "Thinks current premiums are too high.", "confidence": 0.8},
        {"kind": "need", "fact": "Maybe wants dental cover.", "confidence": 0.3},
        {"kind": "made_up_kind", "fact": "Should be dropped.", "confidence": 0.9},
    ]
}


def test_second_call_recalls_the_first(env: Env, db: PgEnv) -> None:
    owner = signup(env.client, "owner@example.com", "Acme")
    lead = env.client.post(
        "/api/v1/leads",
        json={"name": "Ravi Kumar", "phone": "+91 98765 43210", "company": "Kumar Logistics"},
        headers=bearer(owner),
    ).json()

    # --- Call 1: a conversation, a transcript, then extraction when it ends.
    call1, token1 = _call(env, owner, lead["id"])
    env.model.replies.append("Thanks for taking the call.")
    history = [
        {"role": "agent", "text": "Hi, this is Aria, an AI assistant."},
        {
            "role": "prospect",
            "text": "We are a 40 person logistics firm in Pune. Premiums are too high.",
        },
    ]
    turn = env.client.post(
        f"/internal/v1/calls/{call1}/turns", json={"history": history}, headers=_worker(token1)
    )
    assert turn.status_code == 200
    lines = [
        {"seq": 0, "speaker": "agent", "text": history[0]["text"]},
        {"seq": 1, "speaker": "prospect", "text": history[1]["text"]},
        {"seq": 2, "speaker": "agent", "text": "Thanks for taking the call."},
    ]
    saved = env.client.post(
        f"/internal/v1/calls/{call1}/transcript", json={"lines": lines}, headers=_worker(token1)
    )
    assert saved.status_code == 204
    env.model.replies.append(json.dumps(FACTS))  # the extraction reply
    ended = env.client.post(
        f"/internal/v1/calls/{call1}/end", json={"reason": "done"}, headers=_worker(token1)
    )
    assert ended.status_code == 204

    memories = env.client.get(f"/api/v1/leads/{lead['id']}/memories", headers=bearer(owner)).json()
    assert {m["fact"] for m in memories} == {
        "Runs a 40-person logistics firm in Pune.",
        "Thinks current premiums are too high.",
        "Maybe wants dental cover.",
    }
    assert all(m["source_call_id"] == call1 for m in memories)
    transcript = env.client.get(
        f"/api/v1/voice/calls/{call1}/transcript", headers=bearer(owner)
    ).json()
    assert [ln["speaker"] for ln in transcript["lines"]] == ["agent", "prospect", "agent"]

    # --- Call 2: the agent's prompt now carries the confident facts, as notes.
    call2, token2 = _call(env, owner, lead["id"])
    env.model.replies.append("Good to speak again.")
    env.client.post(
        f"/internal/v1/calls/{call2}/turns",
        json={"history": [{"role": "prospect", "text": "Hello again."}]},
        headers=_worker(token2),
    )
    system = env.model.requests[-1].system
    assert "Notes from earlier calls with this prospect" in system
    assert "Runs a 40-person logistics firm in Pune." in system
    assert "Thinks current premiums are too high." in system
    assert "dental" not in system  # below the confidence threshold

    # --- Correction: removing a fact keeps it out of the next prompt.
    objection = next(m for m in memories if m["kind"] == "objection")
    removed = env.client.delete(
        f"/api/v1/leads/{lead['id']}/memories/{objection['id']}", headers=bearer(owner)
    )
    assert removed.status_code == 204
    env.model.replies.append("Sure.")
    env.client.post(
        f"/internal/v1/calls/{call2}/turns",
        json={"history": [{"role": "prospect", "text": "Go on."}]},
        headers=_worker(token2),
    )
    assert "premiums" not in env.model.requests[-1].system


def test_memory_is_tenant_isolated(env: Env, db: PgEnv) -> None:
    a = signup(env.client, "a@example.com", "Alpha")
    b = signup(env.client, "b@example.com", "Beta")
    lead = env.client.post("/api/v1/leads", json={"name": "Asha"}, headers=bearer(a)).json()
    lead_path = f"/api/v1/leads/{lead['id']}"

    assert env.client.get(lead_path, headers=bearer(b)).status_code == 404
    assert env.client.get(f"{lead_path}/memories", headers=bearer(b)).status_code == 404
    assert env.client.get("/api/v1/leads", headers=bearer(b)).json() == []
    # B cannot start a call against A's lead.
    response = env.client.post(
        "/api/v1/voice/sessions", json={"lead_id": lead["id"]}, headers=bearer(b)
    )
    assert response.status_code == 404


def test_call_without_lead_keeps_no_memory(env: Env, db: PgEnv) -> None:
    owner = signup(env.client, "owner@example.com", "Acme")
    call_id, token = _call(env, owner, None)
    env.client.post(
        f"/internal/v1/calls/{call_id}/transcript",
        json={"lines": [{"seq": 0, "speaker": "prospect", "text": "hello"}]},
        headers=_worker(token),
    )
    env.client.post(
        f"/internal/v1/calls/{call_id}/end", json={"reason": "done"}, headers=_worker(token)
    )
    assert admin_fetch(db, "SELECT count(*) AS n FROM lead_memories")[0]["n"] == 0
    assert env.model.requests == []  # no extraction request was made


def test_lead_validation(env: Env, db: PgEnv) -> None:
    owner = signup(env.client, "owner@example.com", "Acme")
    for bad in ({"name": ""}, {"name": "X", "phone": "call me"}, {"name": "X", "email": "nope"}):
        assert env.client.post("/api/v1/leads", json=bad, headers=bearer(owner)).status_code == 422


# --- Retention ----------------------------------------------------------------------------


def _as_app(db: PgEnv, *statements: tuple[str, tuple[Any, ...]]) -> list[Any]:
    async def run() -> list[Any]:
        conn = await asyncpg.connect(db.app_dsn)
        try:
            async with conn.transaction():
                return [await conn.fetch(sql, *args) for sql, args in statements]
        finally:
            await conn.close()

    return asyncio.run(run())


def test_expired_transcripts_are_purged_and_nothing_else(env: Env, db: PgEnv) -> None:
    owner = signup(env.client, "owner@example.com", "Acme")
    call_id, token = _call(env, owner, None)
    env.client.post(
        f"/internal/v1/calls/{call_id}/transcript",
        json={
            "lines": [
                {"seq": 0, "speaker": "prospect", "text": "old"},
                {"seq": 1, "speaker": "agent", "text": "new"},
            ]
        },
        headers=_worker(token),
    )
    expiry = admin_fetch(
        db, "SELECT expires_at - created_at AS kept FROM conversation_messages LIMIT 1"
    )
    assert expiry[0]["kept"].days == 90
    admin_execute(
        db, "UPDATE conversation_messages SET expires_at = now() - interval '1 day' WHERE seq = 0"
    )

    (result,) = _as_app(db, ("SELECT purge_expired_transcripts() AS n", ()))
    assert result[0]["n"] == 1
    assert [r["text"] for r in admin_fetch(db, "SELECT text FROM conversation_messages")] == ["new"]


def test_app_role_cannot_delete_or_peek_at_transcripts(env: Env, db: PgEnv) -> None:
    owner = signup(env.client, "owner@example.com", "Acme")
    call_id, token = _call(env, owner, None)
    env.client.post(
        f"/internal/v1/calls/{call_id}/transcript",
        json={"lines": [{"seq": 0, "speaker": "prospect", "text": "secret-ish"}]},
        headers=_worker(token),
    )
    admin_execute(db, "UPDATE conversation_messages SET expires_at = now() - interval '1 day'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        _as_app(db, ("DELETE FROM conversation_messages", ()))
    # The purge policy is the owner's only: setting app.purge does not expose other rows.
    _, rows = _as_app(
        db,
        ("SELECT set_config('app.purge', 'on', true)", ()),
        ("SELECT * FROM conversation_messages", ()),
    )
    assert rows == []
