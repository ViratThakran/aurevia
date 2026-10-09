"""Phase 8a: permissions and custom roles, invitations, plan limits, platform administration,
usage cost, campaign queue and auto-dialer, CSV import and analytics."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aurevia.campaigns.scheduler import _Tasks, tick
from aurevia.db.session import Database
from aurevia.platform import operator as platform_operator
from aurevia.providers.telephony import DialError, DialFailure
from aurevia.telephony.outbound import OutboundDeps
from tests.conftest import SettingsFactory
from tests.integration.conftest import PASSWORD, PgEnv, admin_execute, admin_fetch, bearer, me
from tests.integration.conftest import signup as do_signup
from tests.integration.test_telephony import (
    NOON_IST,
    OWN_PHONE,
    Env,
    _lead,
    _make_env,
    _post,
    _setup_lines,
)


@pytest.fixture
def env(db: PgEnv, make_settings: SettingsFactory) -> Iterator[Env]:
    yield from _make_env(db, make_settings)


def _invite(env: Env, email: str, **body: Any) -> str:
    response = _post(env, "/team/invitations", {"email": email, **body})
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def _accept(env: Env, token: str, password: str = PASSWORD) -> Any:
    return env.client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": password}
    )


def _member(env: Env, email: str = "member@example.com", **invite: Any) -> dict[str, Any]:
    response = _accept(env, _invite(env, email, **invite))
    assert response.status_code == 200, response.text
    tokens: dict[str, Any] = response.json()
    return tokens


def _membership_id(env: Env, email: str) -> str:
    members = env.client.get("/api/v1/tenant/members", headers=bearer(env.owner)).json()
    return str(next(m["membership_id"] for m in members if m["email"] == email))


def _as_owner(db: PgEnv, action: Any) -> Any:
    async def run() -> Any:
        engine = create_async_engine(db.owner_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await action(session)
        finally:
            await engine.dispose()

    return asyncio.run(run())


# --- Permissions, invitations and custom roles -------------------------------------------


def test_invited_member_gets_member_permissions_only(env: Env) -> None:
    member = _member(env)
    info = me(env.client, member)
    assert info["role"] == "member"
    assert info["permissions"] == ["analytics.read", "calls.place", "leads.manage"]
    headers = bearer(member)
    # Allowed: leads. Not allowed: numbers, campaigns, team, audit, privacy.
    assert env.client.post("/api/v1/leads", json={"name": "A"}, headers=headers).status_code == 201
    forbidden = [
        ("post", "/api/v1/telephony/test-numbers", {"e164": OWN_PHONE, "label": "x"}),
        (
            "post",
            "/api/v1/campaigns",
            {"name": "C", "purpose": "promotional", "starts_on": "2026-10-01"},
        ),
        ("post", "/api/v1/team/invitations", {"email": "x@example.com"}),
        ("get", "/api/v1/audit/verify", None),
        ("get", "/api/v1/platform/tenants", None),
    ]
    for method, path, body in forbidden:
        response = env.client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403, (path, response.text)


def test_invitation_rules(env: Env, db: PgEnv) -> None:
    token = _invite(env, "new@example.com")
    assert _accept(env, token, password="short").status_code == 422  # new accounts: 12+ chars
    assert _accept(env, token).status_code == 200
    assert _accept(env, token).status_code == 401  # used
    revoked = _post(env, "/team/invitations", {"email": "late@example.com"}).json()
    env.client.delete(f"/api/v1/team/invitations/{revoked['id']}", headers=bearer(env.owner))
    assert _accept(env, revoked["token"]).status_code == 401
    # An existing account joins another tenant only with its own password.
    other = do_signup(env.client, "other@example.com", "Other Co")
    invite = env.client.post(
        "/api/v1/team/invitations", json={"email": "owner@example.com"}, headers=bearer(other)
    ).json()["token"]
    assert _accept(env, invite, password="wrong password!!").status_code == 401
    joined = _accept(env, invite)
    assert joined.status_code == 200
    login = env.client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    assert login.json()["error"]["code"] == "tenant_selection_required"
    hashes = admin_fetch(db, "SELECT token_hash FROM invitations")
    assert all(len(r["token_hash"]) == 64 for r in hashes)  # only hashes are stored


def test_custom_roles_and_no_privilege_escalation(env: Env) -> None:
    role = _post(
        env, "/team/roles", {"name": "Team lead", "permissions": ["team.manage", "calls.place"]}
    )
    assert role.status_code == 201, role.text
    lead_tokens = _member(env, "lead@example.com", custom_role_id=role.json()["id"])
    assert me(env.client, lead_tokens)["permissions"] == ["calls.place", "team.manage"]
    headers = bearer(lead_tokens)

    # The team lead cannot hand out more than they hold...
    wider = {"name": "Wider", "permissions": ["numbers.manage"]}
    assert env.client.post("/api/v1/team/roles", json=wider, headers=headers).status_code == 403
    admin_invite = {"email": "x@example.com", "role": "admin"}
    assert (
        env.client.post("/api/v1/team/invitations", json=admin_invite, headers=headers).status_code
        == 403
    )
    # ...nor manage someone who can do more (the owner).
    owner_id = _membership_id(env, "owner@example.com")
    demote = env.client.patch(
        f"/api/v1/tenant/members/{owner_id}", json={"role": "member"}, headers=headers
    )
    assert demote.status_code == 403
    # But may invite with a role inside their own rights.
    narrow = env.client.post(
        "/api/v1/team/roles",
        json={"name": "Caller", "permissions": ["calls.place"]},
        headers=headers,
    )
    assert narrow.status_code == 201
    # Roles in use cannot be deleted; custom roles go to members only.
    in_use = env.client.delete(f"/api/v1/team/roles/{role.json()['id']}", headers=bearer(env.owner))
    assert in_use.status_code == 409
    lead_id = _membership_id(env, "lead@example.com")
    bad = env.client.patch(
        f"/api/v1/tenant/members/{lead_id}",
        json={"role": "admin", "custom_role_id": role.json()["id"]},
        headers=bearer(env.owner),
    )
    assert bad.status_code == 409


def test_permission_changes_apply_immediately(env: Env) -> None:
    member = _member(env)
    role = _post(env, "/team/roles", {"name": "Viewer", "permissions": ["analytics.read"]}).json()
    membership = _membership_id(env, "member@example.com")
    changed = env.client.patch(
        f"/api/v1/tenant/members/{membership}",
        json={"role": "member", "custom_role_id": role["id"]},
        headers=bearer(env.owner),
    )
    assert changed.status_code == 204
    # The same access token now carries fewer rights.
    created = env.client.post("/api/v1/leads", json={"name": "A"}, headers=bearer(member))
    assert created.status_code == 403


# --- Platform administration, plans and prices -------------------------------------------


def _make_platform_admin(db: PgEnv, email: str = "owner@example.com") -> None:
    _as_owner(db, lambda s: platform_operator.set_admin(s, email, admin=True))


def test_platform_admin_is_granted_only_by_the_operator(env: Env, db: PgEnv) -> None:
    assert env.client.get("/api/v1/platform/tenants", headers=bearer(env.owner)).status_code == 403
    privilege = admin_fetch(
        db,
        "SELECT has_column_privilege($1, 'users', 'is_platform_admin', 'UPDATE') AS admin_flag, "
        "has_column_privilege($1, 'users', 'last_login_at', 'UPDATE') AS last_login",
        db.app_role,
    )[0]
    assert tuple(privilege) == (False, True)
    _make_platform_admin(db)
    assert me(env.client, env.owner)["is_platform_admin"] is True
    do_signup(env.client, "other@example.com", "Other Co")
    tenants = env.client.get("/api/v1/platform/tenants", headers=bearer(env.owner)).json()
    assert sorted(t["name"] for t in tenants) == ["Acme", "Other Co"]


def test_suspension_signs_a_tenant_out_and_is_audited_there(env: Env, db: PgEnv) -> None:
    _make_platform_admin(db)
    other = do_signup(env.client, "other@example.com", "Other Co")
    other_id = me(env.client, other)["tenant"]["id"]
    suspended = env.client.post(
        f"/api/v1/platform/tenants/{other_id}/suspend", headers=bearer(env.owner)
    )
    assert suspended.status_code == 200
    assert env.client.get("/api/v1/leads", headers=bearer(other)).status_code == 401
    refresh = env.client.post(
        "/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]}
    )
    assert refresh.status_code == 401
    actions = admin_fetch(
        db, "SELECT action FROM audit_events WHERE tenant_id = $1::uuid ORDER BY seq", other_id
    )
    assert actions[-1]["action"] == "platform.tenant_suspended"
    resumed = env.client.post(
        f"/api/v1/platform/tenants/{other_id}/resume", headers=bearer(env.owner)
    )
    assert resumed.json()["status"] == "active"


def test_plan_limits_stop_new_calls(env: Env, db: PgEnv) -> None:
    _make_platform_admin(db)
    tenant_id = me(env.client, env.owner)["tenant"]["id"]
    plan = {"plan_name": "tiny", "monthly_call_limit": 1, "max_concurrent_calls": 5}
    assert (
        env.client.put(
            f"/api/v1/platform/tenants/{tenant_id}/plan", json=plan, headers=bearer(env.owner)
        ).status_code
        == 200
    )
    first = env.client.post("/api/v1/voice/sessions", json={}, headers=bearer(env.owner))
    assert first.status_code == 201
    _setup_lines(env)
    blocked = _post(env, "/calls/outbound", {"lead_id": _lead(env)})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["details"]["limits"] == ["monthly_calls"]
    # A plan limit is not a compliance decision: nothing is recorded, nothing dialed.
    assert admin_fetch(db, "SELECT count(*) AS n FROM compliance_decisions")[0]["n"] == 0
    usage = env.client.get("/api/v1/usage", headers=bearer(env.owner)).json()
    assert usage["plan"]["plan_name"] == "tiny" and usage["used"]["calls"] == 1


def test_usage_is_priced_from_versioned_prices(env: Env, db: PgEnv) -> None:
    _make_platform_admin(db)
    tenant_id = me(env.client, env.owner)["tenant"]["id"]
    admin_execute(
        db,
        "INSERT INTO usage_events (id, tenant_id, kind, provider, model, input_tokens, "
        "output_tokens, audio_seconds, characters, interrupted) VALUES "
        f"(gen_random_uuid(), '{tenant_id}', 'llm', 'gemini', 'gemini-3.5-flash', 2000000, "
        "500000, 0, 0, false), "
        f"(gen_random_uuid(), '{tenant_id}', 'tts', 'cartesia', 'sonic', 0, 0, 0, 1200, false)",
    )
    for resource, amount in (("llm_input_tokens", "10"), ("llm_output_tokens", "40")):
        price = {
            "provider": "gemini",
            "resource": resource,
            "currency": "INR",
            "amount": amount,
            "per_quantity": 1_000_000,
            "effective_from": (NOON_IST - timedelta(days=60)).isoformat(),
        }
        created = env.client.post("/api/v1/platform/prices", json=price, headers=bearer(env.owner))
        assert created.status_code == 201, created.text
    usage = env.client.get("/api/v1/usage", headers=bearer(env.owner)).json()
    assert usage["cost"] == {"INR": "40.000000"}  # 2M x 10/M + 0.5M x 40/M
    tts = next(r for r in usage["resources"] if r["resource"] == "tts_characters")
    assert tts["unpriced_quantity"] == "1200" and usage["fully_priced"] is False
    privileges = admin_fetch(
        db,
        "SELECT has_table_privilege($1, 'prices', 'UPDATE') AS u, "
        "has_table_privilege($1, 'prices', 'DELETE') AS d",
        db.app_role,
    )[0]
    assert tuple(privileges) == (False, False)  # past costs never change


def test_phone_minutes_are_recorded_as_telephony_usage(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    call_id = _post(env, "/calls/outbound", {"lead_id": _lead(env)}).json()["call_id"]
    token = json.loads(env.transport.rooms[-1][2])["call_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        env.client.post(f"/internal/v1/calls/{call_id}/start", headers=headers).status_code == 200
    )
    ended = env.client.post(
        f"/internal/v1/calls/{call_id}/end", json={"reason": "hangup"}, headers=headers
    )
    assert ended.status_code in (200, 204), ended.text
    usage = admin_fetch(
        db, "SELECT kind, provider, model FROM usage_events WHERE kind = 'telephony'"
    )
    assert [tuple(u) for u in usage] == [("telephony", "exotel", "outbound")]


# --- Campaign queue, auto-dialer and import ----------------------------------------------


def _campaign(env: Env, **extra: Any) -> str:
    body = {
        "name": "Queue",
        "purpose": "promotional",
        "starts_on": (NOON_IST.date() - timedelta(days=1)).isoformat(),
        **extra,
    }
    campaign_id = str(_post(env, "/campaigns", body).json()["id"])
    assert _post(env, f"/campaigns/{campaign_id}/status", {"status": "active"}).status_code == 200
    return campaign_id


def _queue(env: Env, campaign_id: str) -> dict[str, dict[str, Any]]:
    entries = env.client.get(
        f"/api/v1/campaigns/{campaign_id}/leads", headers=bearer(env.owner)
    ).json()
    return {e["lead_name"]: e for e in entries}


def test_csv_import_into_a_campaign(env: Env, db: PgEnv) -> None:
    campaign_id = _campaign(env)
    csv_text = (
        "Name,Phone,Email,Company\n"
        "Meera,98765 43210,meera@example.com,Iyer Textiles\n"
        ",9811111111,,\n"  # no name
        "Kabir,not-a-phone,,\n"
        "Asha,+91 98222 22222,,\n"
    )
    response = _post(env, "/leads/import", {"csv": csv_text, "campaign_id": campaign_id})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["created"], result["added_to_campaign"]) == (2, 2)
    assert [e["line"] for e in result["errors"]] == [3, 4]
    assert sorted(_queue(env, campaign_id)) == ["Asha", "Meera"]
    bad = _post(env, "/leads/import", {"csv": "phone\n123"})
    assert bad.status_code == 422


def test_call_next_places_skips_and_retries(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    campaign_id = _campaign(env, retry_delay_minutes=30)
    own = _lead(env, name="Own")  # a registered test number
    stranger = _lead(env, phone="+919899999999", name="Stranger")
    _post(env, f"/campaigns/{campaign_id}/leads", {"lead_ids": [own, stranger]})

    first = _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()
    second = _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()
    results = {r["lead_id"]: r for r in (first, second)}
    assert results[own]["status"] == "placed"
    assert results[stranger]["status"] == "blocked"
    queue = _queue(env, campaign_id)
    assert (queue["Own"]["status"], queue["Own"]["last_result"]) == ("done", "answered")
    # Not a test number + no consent will never pass by itself: skipped, not retried.
    assert (queue["Stranger"]["status"], queue["Stranger"]["last_result"]) == (
        "skipped",
        "not_a_test_number",
    )
    assert _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()["status"] == "empty"


def test_unanswered_calls_are_retried_until_attempts_run_out(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    campaign_id = _campaign(env, max_attempts_per_lead=2, retry_delay_minutes=5)
    lead_id = _lead(env, name="Own")
    _post(env, f"/campaigns/{campaign_id}/leads", {"lead_ids": [lead_id]})
    env.telephony.failures += [DialError(DialFailure.NO_ANSWER), DialError(DialFailure.BUSY)]

    assert _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()["status"] == "placed"
    entry = _queue(env, campaign_id)["Own"]
    assert (entry["status"], entry["attempts"], entry["last_result"]) == ("queued", 1, "no_answer")
    # Not due yet: the retry waits for the campaign's delay.
    assert _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()["status"] == "empty"
    admin_execute(db, "UPDATE campaign_leads SET next_attempt_at = now() - interval '1 minute'")
    assert _post(env, f"/campaigns/{campaign_id}/call-next", {}).json()["status"] == "placed"
    entry = _queue(env, campaign_id)["Own"]
    assert (entry["status"], entry["attempts"], entry["last_result"]) == ("failed", 2, "busy")


def _scheduler_deps(env: Env, db: PgEnv) -> tuple[OutboundDeps, Database]:
    database = Database(db.app_url)
    state = env.client.app.state  # type: ignore[attr-defined]
    deps = OutboundDeps(
        settings=state.settings,
        database=database,
        telephony=env.telephony,
        transport=env.transport,
        dnd=env.dnd,
        clock=lambda: env.clock[0],
    )
    return deps, database


def _run_tick(deps: OutboundDeps, database: Database) -> int:
    async def run() -> int:
        tasks = _Tasks()
        try:
            placed = await tick(deps, tasks)
            await asyncio.gather(*tasks._tasks)
            return placed
        finally:
            await database.dispose()

    return asyncio.run(run())


def test_the_auto_dialer_respects_its_switch_and_concurrency(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    _post(env, "/telephony/test-numbers", {"e164": "+919811111111", "label": "Colleague"})
    campaign_id = _campaign(env, max_concurrent_calls=1)
    leads = [_lead(env, name="Own"), _lead(env, phone="+919811111111", name="Colleague")]
    _post(env, f"/campaigns/{campaign_id}/leads", {"lead_ids": leads})

    assert _run_tick(*_scheduler_deps(env, db)) == 0  # auto_dial is off by default
    switch_on = env.client.patch(
        f"/api/v1/campaigns/{campaign_id}", json={"auto_dial": True}, headers=bearer(env.owner)
    )
    assert switch_on.status_code == 200
    # One concurrent call allowed; the dialed call stays "created" until the agent starts.
    assert _run_tick(*_scheduler_deps(env, db)) == 1
    assert _run_tick(*_scheduler_deps(env, db)) == 0
    admin_execute(db, "UPDATE calls SET status = 'completed'")
    assert _run_tick(*_scheduler_deps(env, db)) == 1
    assert len(env.telephony.placed) == 2
    decisions = admin_fetch(db, "SELECT requested_by_user_id FROM compliance_decisions")
    assert all(d["requested_by_user_id"] is None for d in decisions)  # placed by the dialer


def test_the_auto_dialer_skips_suspended_tenants(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    campaign_id = _campaign(env, auto_dial=True)
    _post(env, f"/campaigns/{campaign_id}/leads", {"lead_ids": [_lead(env, name="Own")]})
    admin_execute(db, "UPDATE tenants SET status = 'suspended'")
    assert _run_tick(*_scheduler_deps(env, db)) == 0
    assert env.telephony.placed == []


# --- Analytics and agent setup -----------------------------------------------------------


def test_analytics_summary(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    _post(env, "/calls/outbound", {"lead_id": _lead(env)})
    summary = env.client.get("/api/v1/analytics/summary?days=7", headers=bearer(env.owner))
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert set(data) == {"period", "activity", "sales", "ai_quality", "economics"}
    assert data["activity"]["calls"] == 1 and data["activity"]["phone_answer_rate"] == 1.0
    assert data["sales"]["meetings_booked"] == 0


def test_agent_setup_is_saved(env: Env) -> None:
    agent = env.client.get("/api/v1/agents/default", headers=bearer(env.owner)).json()
    update = {
        key: agent[key]
        for key in ("name", "company_name", "company_description", "objective", "greeting")
    }
    update |= {
        "personality": "Warm and concise.",
        "qualification_questions": ["How many employees?", "When is renewal?"],
        "objection_guidance": "On price, explain the claims support.",
        "escalation_guidance": "Hand over if they ask about a claim in progress.",
    }
    saved = env.client.put("/api/v1/agents/default", json=update, headers=bearer(env.owner))
    assert saved.status_code == 200, saved.text
    assert saved.json()["qualification_questions"] == ["How many employees?", "When is renewal?"]
    too_many = update | {"qualification_questions": [f"Question {i}?" for i in range(11)]}
    rejected = env.client.put("/api/v1/agents/default", json=too_many, headers=bearer(env.owner))
    assert rejected.status_code == 422


def test_phase8_tables_are_isolated(env: Env, db: PgEnv) -> None:
    tables = ("campaign_leads", "custom_roles", "invitations", "tenant_plans")
    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(tables),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in tables]
