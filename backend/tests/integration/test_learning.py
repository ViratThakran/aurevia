"""WP-12.3 learning tables and import: off by default, redacted before storing, tenant-isolated."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import FakeModelProvider
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import (
    PASSWORD,
    PgEnv,
    add_member,
    admin_fetch,
    bearer,
    me,
    signup,
)

TABLES = ("learning_labels", "learning_sources", "learning_transcripts")
# Obviously fake, test-only personal data.
LINES = [
    {"speaker": "expert", "text": "Hi, is this Ravi Kumar? I'm calling from Acme Cover."},
    {"speaker": "prospect", "text": "Yes. Call me on 98765 43210 or ravi@example.com."},
    {"speaker": "expert", "text": "Thanks Ravi Kumar. How many people are on your team?"},
]
DETECTOR_REPLY = json.dumps({"items": [{"kind": "NAME", "text": "Ravi Kumar"}]})


def _client(db: PgEnv, make_settings: SettingsFactory, replies: list[str], **over: Any) -> Any:
    settings = make_settings(
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
        database_app_role=db.app_role,
        learning_enabled=True,
        **over,
    )
    app = create_app(settings)
    app.state.model_gateway = ModelGateway(
        FakeModelProvider(replies=list(replies)),
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(db: PgEnv, make_settings: SettingsFactory) -> Iterator[TestClient]:
    with _client(db, make_settings, [DETECTOR_REPLY] * 5) as c:
        yield c


def _import(client: TestClient, owner: dict[str, Any], **over: Any) -> Any:
    body: dict[str, Any] = {
        "source_type": "call",
        "title": "Ravi Kumar renewal call",
        "language": "en-IN",
        "outcome": "booked",
        "caller_permission_confirmed": True,
        "lines": LINES,
        **over,
    }
    return client.post("/api/v1/learning/sources", json=body, headers=bearer(owner))


def test_learning_api_is_off_by_default(api: TestClient) -> None:
    owner = signup(api, "owner@example.com", "Acme")
    assert api.get("/api/v1/learning/sources", headers=bearer(owner)).status_code == 404


def test_import_stores_only_redacted_text_and_counts(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    response = _import(client, owner)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["line_count"] == 3 and body["title"] == "[NAME_1] renewal call"
    assert body["redaction_counts"] == {"NAME": 3, "PHONE": 1, "EMAIL": 1}

    stored = " ".join(r["text"] for r in admin_fetch(db, "SELECT text FROM learning_transcripts"))
    for value in ("Ravi Kumar", "98765", "ravi@example.com"):
        assert value not in stored
    assert "Acme Cover" in stored  # not personal data: kept
    assert stored.count("[NAME_1]") == 2  # same person, same placeholder across lines

    audit = admin_fetch(
        db, "SELECT details FROM audit_events WHERE action = 'learning.source_imported'"
    )
    details = (
        json.loads(audit[0]["details"])
        if isinstance(audit[0]["details"], str)
        else (audit[0]["details"])
    )
    assert details["redacted"] == {"NAME": 3, "PHONE": 1, "EMAIL": 1}
    assert "Ravi" not in json.dumps(details)

    detail = client.get(f"/api/v1/learning/sources/{body['id']}", headers=bearer(owner)).json()
    assert [line["seq"] for line in detail["lines"]] == [0, 1, 2]
    assert detail["lines"][1]["text"] == "Yes. Call me on [PHONE_1] or [EMAIL_1]."


def test_csv_import(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    csv_text = (
        "speaker,text,start_ms,end_ms\n"
        'expert,"Hello, Ravi Kumar here?",0,1500\n'
        "prospect,Yes.,1700,1900\n"
    )
    response = _import(client, owner, lines=None, lines_csv=csv_text)
    assert response.status_code == 201, response.text
    rows = admin_fetch(db, "SELECT seq, text, start_ms FROM learning_transcripts ORDER BY seq")
    assert [(r["seq"], r["start_ms"]) for r in rows] == [(0, 0), (1, 1700)]
    assert "Ravi" not in rows[0]["text"]


@pytest.mark.parametrize(
    ("over", "problem"),
    [
        ({"caller_permission_confirmed": False}, "permission"),
        ({"source_type": "talk", "lines": [{**LINES[0], "start_ms": 0}]}, "talk"),
        ({"lines_csv": "speaker,text\nexpert,hi\n"}, "either lines or lines_csv"),
        ({"lines": None, "lines_csv": "who,what\nexpert,hi\n"}, "header"),
    ],
)
def test_bad_imports_are_refused(
    client: TestClient, db: PgEnv, over: dict[str, Any], problem: str
) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    response = _import(client, owner, **over)
    assert response.status_code == 422 and problem in response.text
    assert admin_fetch(db, "SELECT count(*) AS n FROM learning_sources")[0]["n"] == 0


def test_redaction_failure_stores_nothing(db: PgEnv, make_settings: SettingsFactory) -> None:
    with _client(db, make_settings, replies=[]) as broken:  # the detector model fails
        owner = signup(broken, "owner@example.com", "Acme")
        response = _import(broken, owner)
    assert response.status_code == 503 and response.json()["error"]["code"] == "redaction_failed"
    for table in TABLES:
        assert admin_fetch(db, f"SELECT count(*) AS n FROM {table}")[0]["n"] == 0


def test_permissions_are_needed(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    tenant_id = me(client, owner)["tenant"]["id"]
    signup(client, "member@example.com", "Member Own")
    add_member(db, tenant_id=tenant_id, email="member@example.com", role="member")
    member = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": PASSWORD, "tenant_id": tenant_id},
    ).json()
    assert _import(client, member).status_code == 403
    assert client.get("/api/v1/learning/sources", headers=bearer(member)).status_code == 403
    assert _import(client, owner).status_code == 201  # owners have the learning permissions


def test_sources_stay_in_their_tenant(client: TestClient, db: PgEnv) -> None:
    owner = signup(client, "owner@example.com", "Acme")
    source_id = _import(client, owner).json()["id"]
    other = signup(client, "other@example.com", "Other Co")
    assert client.get("/api/v1/learning/sources", headers=bearer(other)).json() == []
    foreign = client.get(f"/api/v1/learning/sources/{source_id}", headers=bearer(other))
    assert foreign.status_code == 404

    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(TABLES),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in TABLES]
    # The app role can add rows but never delete them; labels may change review status.
    privileges = admin_fetch(
        db,
        "SELECT t AS tbl, has_table_privilege($1, t, 'DELETE') AS d, "
        "has_table_privilege($1, t, 'UPDATE') AS u FROM unnest($2::text[]) AS t ORDER BY t",
        db.app_role,
        list(TABLES),
    )
    assert [(r["tbl"], r["d"], r["u"]) for r in privileges] == [
        ("learning_labels", False, True),
        ("learning_sources", False, False),
        ("learning_transcripts", False, False),
    ]


def test_no_model_means_no_import(db: PgEnv, make_settings: SettingsFactory) -> None:
    with _client(db, make_settings, []) as c:
        c.app.state.model_gateway = None
        owner = signup(c, "owner@example.com", "Acme")
        assert _import(c, owner).status_code == 503
