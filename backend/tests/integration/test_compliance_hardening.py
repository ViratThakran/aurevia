"""Phase 7: versioned policies, campaigns, disclosures, the audit chain and DPDP rights."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aurevia.compliance import operator
from aurevia.compliance.policy import INDIA_DRAFT_FILE, load_builtin
from tests.conftest import SettingsFactory
from tests.integration.conftest import PgEnv, admin_execute, admin_fetch, bearer
from tests.integration.test_telephony import (
    CALLER_ID,
    NOON_IST,
    OWN_PHONE,
    Env,
    _lead,
    _make_env,
    _post,
    _setup_lines,
)

DRAFT = load_builtin(INDIA_DRAFT_FILE)


@pytest.fixture
def env(db: PgEnv, make_settings: SettingsFactory) -> Iterator[Env]:
    yield from _make_env(db, make_settings)


@pytest.fixture
def live_env(db: PgEnv, make_settings: SettingsFactory) -> Iterator[Env]:
    yield from _make_env(db, make_settings, telephony_mode="live")


def _as_owner(db: PgEnv, action: Any) -> Any:
    """Run an operator action with the schema owner's connection (as the CLI does)."""

    async def run() -> Any:
        engine = create_async_engine(db.owner_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await action(session)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _publish_reviewed(db: PgEnv, version: str = "india-test-reviewed-1") -> None:
    raw = json.dumps(
        {
            "pack": "india",
            "version": version,
            "notes": "test",
            "rules": json.loads(DRAFT.rules.model_dump_json()),
        }
    )
    _as_owner(db, lambda s: operator.publish(s, raw))
    _as_owner(db, lambda s: operator.review(s, version, by="Test Counsel", reference="OPINION-1"))


def _campaign(env: Env, **overrides: Any) -> str:
    body = {
        "name": "October outreach",
        "purpose": "promotional",
        "starts_on": (NOON_IST.date() - timedelta(days=1)).isoformat(),
        **overrides,
    }
    response = _post(env, "/campaigns", body)
    assert response.status_code == 201, response.text
    campaign_id = str(response.json()["id"])
    activated = _post(env, f"/campaigns/{campaign_id}/status", {"status": "active"})
    assert activated.status_code == 200
    return campaign_id


def _reasons(response: Any) -> list[str]:
    assert response.status_code == 403, response.text
    return list(response.json()["error"]["details"]["reasons"])


def _prepare_live_lead(env: Env) -> str:
    """A lead with everything a live call needs: consent, a DLT 140-series line."""
    body = {"e164": "+911401234567", "purpose": "promotional", "dlt_registered": True}
    assert _post(env, "/telephony/numbers", body).status_code == 201
    lead_id = _lead(env)
    consent = {
        "kind": "express",
        "purpose": "promotional",
        "source": "website form",
        "obtained_at": (NOON_IST - timedelta(days=1)).isoformat(),
    }
    assert _post(env, f"/leads/{lead_id}/consents", consent).status_code == 201
    return lead_id


# --- Versioned policies ------------------------------------------------------------------


def test_the_india_draft_is_seeded_and_applies_by_default(env: Env) -> None:
    versions = env.client.get("/api/v1/compliance/policy-versions", headers=bearer(env.owner))
    assert [(v["version"], v["status"]) for v in versions.json()] == [
        ("india-2026-10-draft-1", "draft")
    ]
    effective = env.client.get("/api/v1/compliance/settings", headers=bearer(env.owner)).json()
    assert effective["effective_policy"]["version"] == "india-2026-10-draft-1"
    assert effective["effective_policy"]["status"] == "draft"


def test_policy_versions_are_immutable(env: Env, db: PgEnv) -> None:
    privileges = admin_fetch(
        db,
        "SELECT has_table_privilege($1, 'policy_versions', 'UPDATE') AS u, "
        "has_table_privilege($1, 'policy_versions', 'INSERT') AS i",
        db.app_role,
    )[0]
    assert tuple(privileges) == (False, False)
    # Not even the schema owner can rewrite rules, un-review, or delete a version.
    for statement in (
        "UPDATE policy_versions SET rules = '{}'::jsonb",
        "DELETE FROM policy_versions",
    ):
        with pytest.raises(asyncpg.RaiseError):
            admin_execute(db, statement)
    _publish_reviewed(db)
    with pytest.raises(asyncpg.RaiseError):
        admin_execute(db, "UPDATE policy_versions SET status = 'draft' WHERE status = 'reviewed'")
    with pytest.raises(asyncpg.RaiseError):
        admin_execute(db, "UPDATE policy_versions SET reviewed_by = 'someone else'")


def test_operator_rules(db: PgEnv) -> None:
    with pytest.raises(operator.OperatorError, match="already exists"):
        _as_owner(db, lambda s: operator.publish(s, DRAFT.raw))
    with pytest.raises(operator.OperatorError, match="reviewer"):
        _as_owner(db, lambda s: operator.review(s, DRAFT.version, by=" ", reference="x"))
    retired = _as_owner(db, lambda s: operator.retire(s, DRAFT.version))
    assert retired.status == "retired"
    with pytest.raises(operator.OperatorError, match="only a draft"):
        _as_owner(db, lambda s: operator.review(s, DRAFT.version, by="A", reference="B"))


def test_live_calls_open_only_under_a_reviewed_version(live_env: Env, db: PgEnv) -> None:
    env = live_env
    lead_id = _prepare_live_lead(env)
    campaign_id = _campaign(env)
    body = {"lead_id": lead_id, "campaign_id": campaign_id}

    # Everything is in place, but the version is only a draft.
    assert _reasons(_post(env, "/calls/outbound", body)) == ["policy_not_reviewed"]
    assert env.telephony.placed == []

    _publish_reviewed(db)
    response = _post(env, "/calls/outbound", body)
    assert response.status_code == 202, response.text
    [placed] = env.telephony.placed
    assert (placed.to_number, placed.from_number) == (OWN_PHONE, "+911401234567")
    decision = admin_fetch(
        db,
        "SELECT d.decision, v.version, v.status, d.campaign_id::text AS c "
        "FROM compliance_decisions d JOIN policy_versions v ON v.id = d.policy_version_id "
        "WHERE d.id = $1::uuid",
        response.json()["decision_id"],
    )[0]
    assert tuple(decision) == ("allow", "india-test-reviewed-1", "reviewed", campaign_id)
    call = admin_fetch(db, "SELECT campaign_id::text AS c FROM calls")[0]
    assert call["c"] == campaign_id


def test_tenants_may_tighten_but_never_loosen(live_env: Env, db: PgEnv) -> None:
    env = live_env
    _publish_reviewed(db)
    looser = env.client.put(
        "/api/v1/compliance/settings",
        json={"overrides": {"window_end": "22:30:00"}},
        headers=bearer(env.owner),
    )
    assert looser.status_code == 422
    assert looser.json()["error"]["details"]["fields"] == ["window_end"]

    stricter = env.client.put(
        "/api/v1/compliance/settings",
        json={"overrides": {"window_end": "11:00:00"}},
        headers=bearer(env.owner),
    )
    assert stricter.status_code == 200, stricter.text
    assert stricter.json()["effective_policy"]["window_end"] == "11:00:00"
    lead_id = _prepare_live_lead(env)
    body = {"lead_id": lead_id, "campaign_id": _campaign(env)}
    # Noon is inside the policy's window but outside this tenant's own.
    assert _reasons(_post(env, "/calls/outbound", body)) == ["outside_calling_window"]


# --- Campaigns and disclosures -----------------------------------------------------------


def test_campaign_lifecycle_and_limits(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env)
    campaign_id = _campaign(env, max_attempts_per_lead=1)
    body = {"lead_id": lead_id, "campaign_id": campaign_id}
    assert _post(env, "/calls/outbound", body).status_code == 202
    assert _reasons(_post(env, "/calls/outbound", body)) == ["campaign_attempts_reached"]

    assert _post(env, f"/campaigns/{campaign_id}/status", {"status": "paused"}).status_code == 200
    other_lead = _lead(env, phone="+919811111111", name="Other")
    admin_body = {"e164": "+919811111111", "label": "Colleague"}
    assert _post(env, "/telephony/test-numbers", admin_body).status_code == 201
    paused = _post(env, "/calls/outbound", {"lead_id": other_lead, "campaign_id": campaign_id})
    assert _reasons(paused) == ["campaign_not_active"]

    assert _post(env, f"/campaigns/{campaign_id}/status", {"status": "ended"}).status_code == 200
    reopen = _post(env, f"/campaigns/{campaign_id}/status", {"status": "active"})
    assert reopen.status_code == 409
    edit = env.client.patch(
        f"/api/v1/campaigns/{campaign_id}", json={"name": "x"}, headers=bearer(env.owner)
    )
    assert edit.status_code == 409
    bad = _post(
        env,
        "/campaigns",
        {
            "name": "Bad",
            "purpose": "promotional",
            "starts_on": "2026-10-10",
            "ends_on": "2026-10-01",
        },
    )
    assert bad.status_code == 422


def test_an_agent_that_does_not_disclose_cannot_call(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    agent = env.client.get("/api/v1/agents/default", headers=bearer(env.owner)).json()
    update = {
        key: agent[key]
        for key in ("name", "company_name", "company_description", "objective", "language")
    }
    update |= {"greeting": "Hello! Is now a good time for a quick chat?", "voice": None}
    response = env.client.put("/api/v1/agents/default", json=update, headers=bearer(env.owner))
    assert response.status_code == 200, response.text
    blocked = _post(env, "/calls/outbound", {"lead_id": _lead(env)})
    assert _reasons(blocked) == ["missing_disclosure"]
    facts = admin_fetch(db, "SELECT facts FROM compliance_decisions")[0]["facts"]
    assert json.loads(facts)["missing_disclosures"] == ["ai_identity", "agent_name", "company_name"]


# --- Audit trail -------------------------------------------------------------------------


def test_the_audit_log_is_chained_and_tampering_shows(env: Env, db: PgEnv) -> None:
    _setup_lines(env)  # writes audit events
    events = env.client.get("/api/v1/audit/events", headers=bearer(env.owner)).json()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["prev_hash"] == "0" * 64
    assert all(b["prev_hash"] == a["hash"] for a, b in itertools.pairwise(events))
    verify = env.client.get("/api/v1/audit/verify", headers=bearer(env.owner)).json()
    assert verify["ok"] is True and verify["events"] == len(events)
    assert verify["head_hash"] == events[-1]["hash"]

    privileges = admin_fetch(
        db,
        "SELECT has_table_privilege($1, 'audit_events', 'UPDATE') AS u, "
        "has_table_privilege($1, 'audit_events', 'DELETE') AS d",
        db.app_role,
    )[0]
    assert tuple(privileges) == (False, False)

    # Someone with direct database access edits one event: verification finds it.
    tenant = admin_fetch(db, "SELECT id FROM tenants")[0]["id"]
    admin_execute(
        db,
        "UPDATE audit_events SET details = '{\"forged\": true}'::jsonb "
        f"WHERE seq = 2 AND tenant_id = '{tenant}'",
    )
    broken = env.client.get("/api/v1/audit/verify", headers=bearer(env.owner)).json()
    assert broken["ok"] is False and broken["first_broken_seq"] == 2


# --- DPDP: access and erasure ------------------------------------------------------------


def _call_with_transcript(env: Env, lead_id: str) -> str:
    call_id = _post(env, "/calls/outbound", {"lead_id": lead_id}).json()["call_id"]
    token = json.loads(env.transport.rooms[-1][2])["call_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        env.client.post(f"/internal/v1/calls/{call_id}/start", headers=headers).status_code == 200
    )
    lines = [
        {"seq": 0, "speaker": "agent", "text": "Hi, this is Aria, an AI assistant."},
        {"seq": 1, "speaker": "prospect", "text": "I'm Meera, my email is meera@example.com."},
    ]
    saved = env.client.post(
        f"/internal/v1/calls/{call_id}/transcript", json={"lines": lines}, headers=headers
    )
    assert saved.status_code in (200, 204), saved.text
    return str(call_id)


def test_access_then_erasure_keeps_only_the_legal_minimum(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env)
    consent = {"kind": "express", "purpose": "promotional", "source": "web form"}
    assert _post(env, f"/leads/{lead_id}/consents", consent).status_code == 201
    _call_with_transcript(env, lead_id)
    tenant = admin_fetch(db, "SELECT id FROM tenants")[0]["id"]
    admin_execute(
        db,
        "INSERT INTO lead_memories (id, tenant_id, lead_id, kind, fact, confidence, extractor) "
        f"VALUES (gen_random_uuid(), '{tenant}', '{lead_id}', 'preference', "
        "'Prefers WhatsApp', 0.9, 'test')",
    )

    export = env.client.get(f"/api/v1/leads/{lead_id}/export", headers=bearer(env.owner))
    assert export.status_code == 200
    data = export.json()
    assert data["lead"]["phone"] == "98765 43210"
    assert [f["fact"] for f in data["remembered_facts"]] == ["Prefers WhatsApp"]
    assert len(data["calls"][0]["transcript"]) == 2

    erased = _post(env, f"/leads/{lead_id}/erase", {"received_via": "email to support"})
    assert erased.status_code == 201, erased.text
    summary = erased.json()["summary"]
    assert (summary["transcript_lines"], summary["memories"]) == (2, 1)
    assert summary["added_to_do_not_call"] is True

    lead = admin_fetch(
        db, "SELECT name, phone, email, status, erased_at FROM leads WHERE id = $1::uuid", lead_id
    )[0]
    assert (lead["name"], lead["phone"], lead["email"], lead["status"]) == (
        "Erased person",
        None,
        None,
        "archived",
    )
    assert lead["erased_at"] is not None
    assert admin_fetch(db, "SELECT count(*) AS n FROM conversation_messages")[0]["n"] == 0
    assert admin_fetch(db, "SELECT count(*) AS n FROM lead_memories")[0]["n"] == 0
    # The legal minimum stays: never call again, and the proof of lawful calling.
    dnc = admin_fetch(db, "SELECT phone, reason FROM do_not_call")
    assert [tuple(r) for r in dnc] == [(OWN_PHONE, "erasure_request")]
    assert admin_fetch(db, "SELECT count(*) AS n FROM compliance_decisions")[0]["n"] == 1
    assert admin_fetch(db, "SELECT count(*) AS n FROM consents")[0]["n"] == 1

    again = _post(env, f"/leads/{lead_id}/erase", {"received_via": "again"})
    assert again.status_code == 409
    edit = env.client.put(
        f"/api/v1/leads/{lead_id}", json={"name": "Back"}, headers=bearer(env.owner)
    )
    assert edit.status_code == 409
    actions = [
        e["action"]
        for e in env.client.get("/api/v1/audit/events", headers=bearer(env.owner)).json()
    ]
    assert "lead.exported" in actions and "lead.erased" in actions


def test_erasure_stays_inside_the_tenant(env: Env, db: PgEnv) -> None:
    lead_id = _lead(env)
    from tests.integration.conftest import signup

    other = signup(env.client, "other@example.com", "Other Co")
    response = env.client.post(
        f"/api/v1/leads/{lead_id}/erase",
        json={"received_via": "x"},
        headers=bearer(other),
    )
    assert response.status_code == 404
    assert admin_fetch(db, "SELECT erased_at FROM leads")[0]["erased_at"] is None


def test_phase7_tables_are_tenant_isolated(env: Env, db: PgEnv) -> None:
    tables = ("campaigns", "erasure_requests", "tenant_compliance_settings")
    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(tables),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in tables]


def test_caller_id_constant_is_registered(env: Env) -> None:
    _setup_lines(env)
    numbers = env.client.get("/api/v1/telephony/numbers", headers=bearer(env.owner)).json()
    assert [n["e164"] for n in numbers] == [CALLER_ID]
