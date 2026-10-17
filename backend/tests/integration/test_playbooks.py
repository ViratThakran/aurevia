"""WP-12.7 / 12.A playbooks: off by default, versioned, immutable once active, tenant-isolated."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from aurevia.main import create_app
from aurevia.playbooks.service import seed_entries
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import (
    PASSWORD,
    PgEnv,
    add_member,
    admin_execute,
    admin_fetch,
    bearer,
    me,
    signup,
)

TABLES = ("playbook_entries", "playbook_versions")
ENTRY = {
    "stage": "objection",
    "situation": "The prospect says it is too expensive.",
    "says": "Fair enough. Compared with what?",
    "tone": "Confident and steady",
    "goal": "Find what they compare the price with.",
    "source": "Test",
}


@pytest.fixture
def client(db: PgEnv, make_settings: SettingsFactory) -> Iterator[TestClient]:
    settings = make_settings(
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
        database_app_role=db.app_role,
        playbooks_enabled=True,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


def _owner(client: TestClient, email: str = "owner@example.com", name: str = "Acme") -> Any:
    owner = signup(client, email, name)
    agent = client.get("/api/v1/agents/default", headers=bearer(owner)).json()
    return owner, agent["id"]


def _draft(client: TestClient, owner: Any, agent_id: str, **over: Any) -> dict[str, Any]:
    response = client.post(
        "/api/v1/playbooks", json={"agent_id": agent_id, **over}, headers=bearer(owner)
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _detail(client: TestClient, owner: Any, version_id: str) -> dict[str, Any]:
    body: dict[str, Any] = client.get(
        f"/api/v1/playbooks/{version_id}", headers=bearer(owner)
    ).json()
    return body


def _post(client: TestClient, owner: Any, path: str, **kwargs: Any) -> Any:
    return client.post(f"/api/v1/playbooks/{path}", headers=bearer(owner), **kwargs)


def test_playbooks_are_off_by_default(api: TestClient) -> None:
    owner = signup(api, "owner@example.com", "Acme")
    assert api.get("/api/v1/playbooks", headers=bearer(owner)).status_code == 404


def test_seed_entries_have_the_fixed_format() -> None:
    entries = seed_entries()
    assert 15 <= len(entries) <= 20
    assert all(e.situation and e.says and e.tone and e.goal and e.source for e in entries)


def test_seeded_draft_is_all_proposed(client: TestClient) -> None:
    owner, agent_id = _owner(client)
    draft = _draft(client, owner, agent_id, seed=True, notes="first seed")
    assert (draft["version"], draft["status"]) == (1, "draft")
    entries = _detail(client, owner, draft["id"])["entries"]
    assert len(entries) == len(seed_entries())
    assert {e["status"] for e in entries} == {"proposed"}
    assert [e["position"] for e in entries] == list(range(len(entries)))


def test_lifecycle_activate_freezes_and_retires_the_previous(client: TestClient, db: PgEnv) -> None:
    owner, agent_id = _owner(client)
    v1 = _draft(client, owner, agent_id)
    # Nothing approved yet: activation is refused.
    entry = _post(client, owner, f"{v1['id']}/entries", json=ENTRY).json()
    assert entry["status"] == "proposed"
    refused = _post(client, owner, f"{v1['id']}/activate")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "playbook_not_approved"

    approved = _post(client, owner, f"{v1['id']}/entries/{entry['id']}/approve").json()
    assert approved["status"] == "approved" and approved["approved_at"]
    # Editing an approved entry sends it back to proposed; approve again.
    edited = client.put(
        f"/api/v1/playbooks/{v1['id']}/entries/{entry['id']}",
        json={**ENTRY, "says": "Fair. What are you comparing it with?"},
        headers=bearer(owner),
    ).json()
    assert edited["status"] == "proposed"
    _post(client, owner, f"{v1['id']}/entries/{entry['id']}/approve")
    assert _post(client, owner, f"{v1['id']}/activate").json()["status"] == "active"

    # Active is frozen: no new entries, no edits, no approvals.
    for path, kwargs in (
        (f"{v1['id']}/entries", {"json": ENTRY}),
        (f"{v1['id']}/entries/{entry['id']}/approve", {}),
    ):
        frozen = _post(client, owner, path, **kwargs)
        assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "playbook_not_draft"

    # A copy keeps approvals; activating it retires version 1.
    v2 = _draft(client, owner, agent_id, copy_from_version_id=v1["id"])
    assert v2["version"] == 2
    assert [e["status"] for e in _detail(client, owner, v2["id"])["entries"]] == ["approved"]
    assert _post(client, owner, f"{v2['id']}/activate").json()["status"] == "active"
    versions = client.get(
        "/api/v1/playbooks", params={"agent_id": agent_id}, headers=bearer(owner)
    ).json()
    assert [(v["version"], v["status"]) for v in versions] == [(2, "active"), (1, "retired")]
    assert _post(client, owner, f"{v1['id']}/retire").status_code == 409

    actions = [
        r["action"]
        for r in admin_fetch(
            db, "SELECT action FROM audit_events WHERE action LIKE 'playbook.%' ORDER BY id"
        )
    ]
    assert actions.count("playbook.version_activated") == 2
    assert "playbook.entry_approved" in actions and "playbook.entry_edited" in actions


def test_database_backs_up_immutability(client: TestClient, db: PgEnv) -> None:
    owner, agent_id = _owner(client)
    v1 = _draft(client, owner, agent_id)
    entry = _post(client, owner, f"{v1['id']}/entries", json=ENTRY).json()
    _post(client, owner, f"{v1['id']}/entries/{entry['id']}/approve")
    _post(client, owner, f"{v1['id']}/activate")
    # Even bypassing the service (as the admin role), an active version's entries cannot change
    # and a status cannot go backwards.
    for statement in (
        f"UPDATE playbook_entries SET says = 'x' WHERE id = '{entry['id']}'",
        f"UPDATE playbook_versions SET status = 'draft' WHERE id = '{v1['id']}'",
    ):
        with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError):
            admin_execute(db, statement)


def test_permissions(client: TestClient, db: PgEnv) -> None:
    owner, agent_id = _owner(client)
    tenant_id = me(client, owner)["tenant"]["id"]
    signup(client, "member@example.com", "Member Own")
    add_member(db, tenant_id=tenant_id, email="member@example.com", role="member")
    member = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": PASSWORD, "tenant_id": tenant_id},
    ).json()
    assert client.get("/api/v1/playbooks", headers=bearer(member)).status_code == 403
    assert (
        client.post(
            "/api/v1/playbooks", json={"agent_id": agent_id}, headers=bearer(member)
        ).status_code
        == 403
    )


def test_playbooks_stay_in_their_tenant(client: TestClient, db: PgEnv) -> None:
    owner, agent_id = _owner(client)
    v1 = _draft(client, owner, agent_id, seed=True)
    other, other_agent = _owner(client, "other@example.com", "Other Co")
    assert client.get("/api/v1/playbooks", headers=bearer(other)).json() == []
    assert client.get(f"/api/v1/playbooks/{v1['id']}", headers=bearer(other)).status_code == 404
    # Another tenant's agent or version cannot be used.
    assert (
        client.post(
            "/api/v1/playbooks", json={"agent_id": agent_id}, headers=bearer(other)
        ).status_code
        == 404
    )
    copy = client.post(
        "/api/v1/playbooks",
        json={"agent_id": other_agent, "copy_from_version_id": v1["id"]},
        headers=bearer(other),
    )
    assert copy.status_code == 404

    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(TABLES),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in TABLES]
    privileges = admin_fetch(
        db,
        "SELECT t AS tbl, has_table_privilege($1, t, 'DELETE') AS d FROM unnest($2::text[]) AS t",
        db.app_role,
        list(TABLES),
    )
    assert not any(r["d"] for r in privileges)


def test_seed_and_copy_together_is_refused(client: TestClient) -> None:
    owner, agent_id = _owner(client)
    v1 = _draft(client, owner, agent_id)
    response = client.post(
        "/api/v1/playbooks",
        json={"agent_id": agent_id, "seed": True, "copy_from_version_id": v1["id"]},
        headers=bearer(owner),
    )
    assert response.status_code == 409
