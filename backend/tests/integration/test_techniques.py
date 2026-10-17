"""WP-12.6 technique review queue: policy check first, person decides, every step audited."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SettingsFactory
from tests.integration.conftest import PgEnv, admin_fetch, bearer, signup
from tests.integration.test_learning import DETECTOR_REPLY, _client, _import

CLEAN = {
    "stage": "objection",
    "situation": "The prospect says it is too expensive.",
    "says": "Fair enough. Expensive compared with what you have now?",
    "tone": "Calm, then firmer",
    "goal": "Find what they compare the price with.",
    "excerpt": "Expert: Fair enough. Compared with what?",
}


@pytest.fixture
def client(db: PgEnv, make_settings: SettingsFactory) -> Iterator[TestClient]:
    with _client(db, make_settings, [DETECTOR_REPLY] * 5, playbooks_enabled=True) as c:
        yield c


def _propose(client: TestClient, owner: Any, **over: Any) -> Any:
    return client.post("/api/v1/learning/techniques", json={**CLEAN, **over}, headers=bearer(owner))


def _review(client: TestClient, owner: Any, technique_id: str, status: str) -> Any:
    return client.post(
        f"/api/v1/learning/techniques/{technique_id}/review",
        json={"status": status},
        headers=bearer(owner),
    )


def test_policy_check_blocks_approval_until_edited(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    source_id = _import(client, owner).json()["id"]  # outcome: booked
    flagged = _propose(
        client, owner, says="I'm a real person, and we guarantee savings.", source_ids=[source_id]
    ).json()
    assert flagged["policy_flags"] == ["claims_human", "guarantee"]
    assert (flagged["booked_count"], flagged["unbooked_count"]) == (1, 0)

    refused = _review(client, owner, flagged["id"], "approved")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "technique_flagged"
    assert "Says or implies the agent is a person" in refused.json()["error"]["details"]["reasons"]

    edit = {k: v for k, v in CLEAN.items() if k != "excerpt"}
    edited = client.put(
        f"/api/v1/learning/techniques/{flagged['id']}", json=edit, headers=bearer(owner)
    ).json()
    assert (edited["policy_flags"], edited["status"]) == ([], "proposed")
    assert _review(client, owner, flagged["id"], "approved").json()["status"] == "approved"

    actions = [
        r["action"]
        for r in admin_fetch(
            db, "SELECT action FROM audit_events WHERE action LIKE 'learning.technique_%'"
        )
    ]
    assert sorted(actions) == [
        "learning.technique_edited",
        "learning.technique_proposed",
        "learning.technique_reviewed",
    ]


def test_queue_reject_and_copy_to_a_draft_playbook(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    keep = _propose(client, owner).json()
    drop = _propose(client, owner, says="Okay, shall we talk next week?").json()
    queue = client.get("/api/v1/learning/techniques", headers=bearer(owner)).json()
    assert {t["id"] for t in queue} == {keep["id"], drop["id"]}
    assert _review(client, owner, drop["id"], "rejected").json()["status"] == "rejected"

    agent_id = client.get("/api/v1/agents/default", headers=bearer(owner)).json()["id"]
    draft = client.post(
        "/api/v1/playbooks", json={"agent_id": agent_id}, headers=bearer(owner)
    ).json()
    copy = f"/api/v1/learning/techniques/{keep['id']}/to-playbook"
    not_yet = client.post(copy, json={"version_id": draft["id"]}, headers=bearer(owner))
    assert not_yet.status_code == 409  # only approved techniques
    _review(client, owner, keep["id"], "approved")
    copied = client.post(copy, json={"version_id": draft["id"]}, headers=bearer(owner)).json()
    assert copied["playbook_entry_id"]

    entries = client.get(f"/api/v1/playbooks/{draft['id']}", headers=bearer(owner)).json()[
        "entries"
    ]
    assert len(entries) == 1 and entries[0]["id"] == copied["playbook_entry_id"]
    assert entries[0]["status"] == "proposed"  # still needs learning.publish approval
    assert entries[0]["says"] == CLEAN["says"]
    assert entries[0]["source"].startswith("Expert technique seen in 0 sources")
    again = client.post(copy, json={"version_id": draft["id"]}, headers=bearer(owner))
    assert again.status_code == 409
    queue = client.get(
        "/api/v1/learning/techniques", params={"status": "approved"}, headers=bearer(owner)
    ).json()
    assert [t["id"] for t in queue] == [keep["id"]]


def test_techniques_stay_in_their_tenant(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    source_id = _import(client, owner).json()["id"]
    technique = _propose(client, owner, source_ids=[source_id]).json()
    other = signup(client, "other@example.com", "Other Co")
    assert client.get("/api/v1/learning/techniques", headers=bearer(other)).json() == []
    assert _review(client, other, technique["id"], "rejected").status_code == 404
    # Another tenant's source cannot be cited.
    assert _propose(client, other, source_ids=[source_id]).status_code == 404

    rows = admin_fetch(
        db,
        "SELECT relrowsecurity, relforcerowsecurity, "
        "has_table_privilege($1, 'learning_techniques', 'DELETE') AS d "
        "FROM pg_class WHERE relname = 'learning_techniques'",
        db.app_role,
    )
    assert (rows[0][0], rows[0][1], rows[0]["d"]) == (True, True, False)
