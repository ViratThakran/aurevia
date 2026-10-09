"""Phase 6: phone calls behind the compliance gate. Gate: zero bypasses; test numbers only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import (
    FakeDndRegistry,
    FakeModelProvider,
    FakeTelephonyProvider,
    FakeTurn,
    FakeVoiceTransport,
)
from aurevia.providers.model import ToolCall
from aurevia.providers.telephony import DialError, DialFailure
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PgEnv, admin_fetch, bearer, signup

OWN_PHONE = "+919876543210"
CALLER_ID = "+918045671234"
# 12:00 India time today: inside the calling window whenever the tests run.
NOON_IST = datetime.now(UTC).replace(hour=6, minute=30, second=0, microsecond=0)


@dataclass
class Env:
    client: TestClient
    transport: FakeVoiceTransport
    telephony: FakeTelephonyProvider
    dnd: FakeDndRegistry
    model: FakeModelProvider
    owner: dict[str, Any]
    clock: list[datetime]


def _make_env(db: PgEnv, make_settings: SettingsFactory, **overrides: Any) -> Iterator[Env]:
    app = create_app(
        make_settings(
            database_url=db.app_url,
            jwt_secret=TEST_JWT_SECRET,
            database_app_role=db.app_role,
            **overrides,
        )
    )
    transport, telephony = FakeVoiceTransport(), FakeTelephonyProvider()
    dnd, model = FakeDndRegistry(), FakeModelProvider(replies=[])
    clock = [NOON_IST]
    app.state.voice_transport = transport
    app.state.telephony = telephony
    app.state.dnd_registry = dnd
    app.state.clock = lambda: clock[0]
    app.state.model_gateway = ModelGateway(
        model,
        model="test-model",
        max_tokens=256,
        first_token_timeout_seconds=5,
        total_timeout_seconds=10,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        owner = signup(client, "owner@example.com", "Acme")
        yield Env(client, transport, telephony, dnd, model, owner, clock)


@pytest.fixture
def env(db: PgEnv, make_settings: SettingsFactory) -> Iterator[Env]:
    yield from _make_env(db, make_settings, max_test_numbers=2)


def _post(env: Env, path: str, body: dict[str, Any]) -> Any:
    return env.client.post(f"/api/v1{path}", json=body, headers=bearer(env.owner))


def _lead(env: Env, phone: str | None = "98765 43210", name: str = "Meera") -> str:
    response = _post(env, "/leads", {"name": name, "phone": phone})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _setup_lines(env: Env, *, test_number: str | None = OWN_PHONE) -> None:
    number = {"e164": CALLER_ID, "purpose": "promotional", "inbound_enabled": True}
    assert _post(env, "/telephony/numbers", number).status_code == 201
    if test_number:
        body = {"e164": test_number, "label": "My phone"}
        assert _post(env, "/telephony/test-numbers", body).status_code == 201


def _call_out(env: Env, lead_id: str) -> Any:
    return _post(env, "/calls/outbound", {"lead_id": lead_id})


# --- The gate ----------------------------------------------------------------------------


def test_a_number_that_is_not_a_test_number_is_never_dialed(env: Env, db: PgEnv) -> None:
    _setup_lines(env, test_number=None)
    response = _call_out(env, _lead(env))

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "call_blocked"
    # Every failing check is reported; the first one is the decision's reason code.
    assert error["details"]["reasons"] == ["not_a_test_number", "no_valid_consent"]
    assert env.telephony.placed == [] and env.transport.rooms == []
    assert admin_fetch(db, "SELECT count(*) AS n FROM calls")[0]["n"] == 0
    decision = admin_fetch(
        db, "SELECT decision, reason_code, mode, policy_version FROM compliance_decisions"
    )
    assert [tuple(d) for d in decision] == [
        ("block", "not_a_test_number", "test", "india-2026-10-draft-1")
    ]


def test_a_test_call_to_an_own_phone_is_dialed_and_answered(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env)
    response = _call_out(env, lead_id)

    assert response.status_code == 202, response.text
    body = response.json()
    [placed] = env.telephony.placed
    assert (placed.to_number, placed.from_number) == (OWN_PHONE, CALLER_ID)
    assert str(placed.compliance_decision_id) == body["decision_id"]
    room, _, metadata = env.transport.rooms[0]
    assert placed.room == room and json.loads(metadata)["channel"] == "phone"

    call = admin_fetch(
        db,
        "SELECT direction, dial_status, status, to_number, compliance_decision_id::text AS d, "
        "provider_call_id FROM calls WHERE id = $1::uuid",
        body["call_id"],
    )[0]
    assert (call["direction"], call["dial_status"], call["status"]) == (
        "outbound",
        "answered",
        "created",  # in progress once the agent hears the phone answered
    )
    assert call["d"] == body["decision_id"] and call["provider_call_id"].startswith("fake-call")
    decision = admin_fetch(db, "SELECT decision, checks FROM compliance_decisions")[0]
    assert decision["decision"] == "allow"
    assert all(check["passed"] for check in json.loads(decision["checks"]))
    assert env.dnd.lookups == []  # own test numbers are not scrubbed against the DND registry


@pytest.mark.parametrize(
    ("failure", "status"),
    [(DialFailure.BUSY, "busy"), (DialFailure.NO_ANSWER, "no_answer")],
)
def test_an_unanswered_call_fails_and_frees_the_agent(
    env: Env, db: PgEnv, failure: DialFailure, status: str
) -> None:
    _setup_lines(env)
    env.telephony.failures.append(DialError(failure, sip_status=486))
    call_id = _call_out(env, _lead(env)).json()["call_id"]

    call = admin_fetch(
        db, "SELECT dial_status, status, end_reason, room FROM calls WHERE id = $1::uuid", call_id
    )[0]
    assert (call["dial_status"], call["status"], call["end_reason"]) == (
        status,
        "failed",
        f"dial_{status}",
    )
    assert env.transport.closed == [call["room"]]


def test_outside_the_calling_window_nothing_is_dialed(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    env.clock[0] = NOON_IST + timedelta(hours=10)  # 22:00 India time
    response = _call_out(env, _lead(env))
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reasons"] == ["outside_calling_window"]
    assert env.telephony.placed == []


def test_attempts_per_number_are_limited(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env)
    assert _call_out(env, lead_id).status_code == 202
    tenant, agent = admin_fetch(db, "SELECT tenant_id, agent_id FROM calls")[0]
    for i in range(19):  # test mode allows 20 calls a day to one number
        admin_fetch(
            db,
            "WITH d AS (INSERT INTO compliance_decisions (id, tenant_id, action, purpose, mode, "
            "policy_pack, policy_version, checks, facts, decision, reason_code) VALUES "
            "(gen_random_uuid(), $1, 'outbound_call', 'promotional', 'test', 'india', 'v', "
            "'[]', '{}', 'allow', 'allowed') RETURNING id) "
            "INSERT INTO calls (id, tenant_id, agent_id, channel, status, sales_state, room, "
            "turn_count, direction, to_number, compliance_decision_id) "
            "SELECT gen_random_uuid(), $1, $2, 'phone', 'completed', 'completed', $3, 0, "
            "'outbound', $4, d.id FROM d",
            tenant,
            agent,
            f"room-{i}",
            OWN_PHONE,
        )
    response = _call_out(env, lead_id)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reasons"] == ["attempt_limit_reached"]


def test_live_mode_is_blocked_until_counsel_reviews_the_policy(
    db: PgEnv, make_settings: SettingsFactory
) -> None:
    for env in _make_env(db, make_settings, telephony_mode="live"):
        _post(
            env,
            "/telephony/numbers",
            {"e164": "+911401234567", "purpose": "promotional", "dlt_registered": True},
        )
        lead_id = _lead(env)
        consent = {
            "kind": "express",
            "purpose": "promotional",
            "source": "website form",
            "obtained_at": (NOON_IST - timedelta(days=1)).isoformat(),
        }
        assert _post(env, f"/leads/{lead_id}/consents", consent).status_code == 201
        response = _call_out(env, lead_id)
        assert response.status_code == 403
        # Everything else about this call is compliant; only the unreviewed pack stops it.
        assert response.json()["error"]["details"]["reasons"] == ["policy_not_reviewed"]
        assert env.dnd.lookups == [OWN_PHONE] and env.telephony.placed == []


def test_phone_calls_are_unavailable_until_configured(env: Env) -> None:
    env.client.app.state.telephony = None  # type: ignore[attr-defined]
    response = _call_out(env, _lead(env))
    assert response.status_code == 503


# --- During the call ---------------------------------------------------------------------


def test_a_do_not_call_request_on_the_phone_blocks_every_later_call(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env)
    call_id = _call_out(env, lead_id).json()["call_id"]
    token = json.loads(env.transport.rooms[-1][2])["call_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        env.client.post(f"/internal/v1/calls/{call_id}/start", headers=headers).status_code == 200
    )

    env.model.replies += [
        FakeTurn(
            text="Of course, I'm sorry to bother you.",
            tool_calls=(ToolCall(id="d1", name="request_do_not_call", arguments={}),),
        )
    ]
    turn = env.client.post(
        f"/internal/v1/calls/{call_id}/turns",
        json={"history": [{"role": "prospect", "text": "Please never call me again."}]},
        headers=headers,
    )
    assert {"type": "tool", "name": "request_do_not_call", "ok": True} in [
        json.loads(line) for line in turn.text.splitlines() if line
    ]
    entry = admin_fetch(db, "SELECT phone, reason, source_call_id::text AS c FROM do_not_call")
    assert [tuple(e) for e in entry] == [(OWN_PHONE, "prospect_request", call_id)]

    response = _call_out(env, lead_id)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reasons"] == ["on_do_not_call_list"]
    assert len(env.telephony.placed) == 1


# --- Numbers -----------------------------------------------------------------------------


def test_number_registration_rules(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    assert _post(env, "/telephony/test-numbers", {"e164": "12", "label": "x"}).status_code == 422
    second = {"e164": "+919811111111", "label": "Colleague"}
    assert _post(env, "/telephony/test-numbers", second).status_code == 201
    third = _post(env, "/telephony/test-numbers", {"e164": "+919822222222", "label": "Third"})
    assert third.status_code == 409 and third.json()["error"]["code"] == "too_many_test_numbers"

    # A number belongs to one tenant; another tenant cannot claim it.
    other = signup(env.client, "other@example.com", "Other Co")
    claim = env.client.post(
        "/api/v1/telephony/numbers",
        json={"e164": CALLER_ID, "purpose": "promotional"},
        headers=bearer(other),
    )
    assert claim.status_code == 409
    listed = env.client.get("/api/v1/telephony/numbers", headers=bearer(other)).json()
    assert listed == []


def test_consent_records(env: Env, db: PgEnv) -> None:
    lead_id = _lead(env)
    body = {"kind": "inquiry", "purpose": "promotional", "source": "inbound enquiry"}
    created = _post(env, f"/leads/{lead_id}/consents", body)
    assert created.status_code == 201 and created.json()["phone"] == OWN_PHONE
    consent_id = created.json()["id"]
    revoked = _post(env, f"/leads/{lead_id}/consents/{consent_id}/revoke", {})
    assert revoked.json()["revoked_at"] is not None
    future = {**body, "obtained_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
    assert _post(env, f"/leads/{lead_id}/consents", future).status_code == 422
    no_phone = _lead(env, phone=None, name="No Phone")
    assert _post(env, f"/leads/{no_phone}/consents", body).status_code == 422


# --- Webhooks ----------------------------------------------------------------------------


def _webhook(env: Env, event: dict[str, Any], *, signed: bool = True) -> Any:
    return env.client.post(
        "/webhooks/livekit",
        content=json.dumps(event),
        headers={"Authorization": "signed" if signed else "forged"},
    )


def test_webhooks_must_be_signed(env: Env) -> None:
    assert _webhook(env, {"kind": "room_finished", "room": "x"}, signed=False).status_code == 401


def test_a_room_that_ends_closes_its_open_call(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    call_id = _call_out(env, _lead(env)).json()["call_id"]
    room = env.transport.rooms[-1][0]
    assert _webhook(env, {"kind": "room_finished", "room": room}).status_code == 200
    call = admin_fetch(db, "SELECT status, end_reason FROM calls WHERE id = $1::uuid", call_id)[0]
    assert (call["status"], call["end_reason"]) == ("failed", "room_closed")
    # Repeated deliveries and unknown rooms are harmless.
    assert _webhook(env, {"kind": "room_finished", "room": room}).status_code == 200
    assert _webhook(env, {"kind": "room_finished", "room": "nope"}).status_code == 200


def test_an_inbound_call_reaches_the_agent_with_the_callers_lead(env: Env, db: PgEnv) -> None:
    _setup_lines(env)
    lead_id = _lead(env, phone="09876543210")
    event = {
        "kind": "participant_joined",
        "room": "aurevia-in-_+919876543210_abc",
        "identity": "sip_caller",
        "is_phone": True,
        "attributes": {"sip.trunkPhoneNumber": CALLER_ID, "sip.phoneNumber": OWN_PHONE},
    }
    assert _webhook(env, event).status_code == 200
    assert _webhook(env, event).status_code == 200  # retried delivery

    [(room, agent_name, metadata)] = env.transport.dispatches
    assert room == event["room"] and agent_name == "aurevia-voice"
    call = admin_fetch(
        db, "SELECT id::text AS id, direction, lead_id::text AS lead, from_number FROM calls"
    )
    assert [(c["direction"], c["lead"], c["from_number"]) for c in call] == [
        ("inbound", lead_id, OWN_PHONE)
    ]
    # The worker can use the dispatched credentials like any other call.
    data = json.loads(metadata)
    start = env.client.post(
        f"/internal/v1/calls/{data['call_id']}/start",
        headers={"Authorization": f"Bearer {data['call_token']}"},
    )
    assert start.status_code == 200 and data["call_id"] == call[0]["id"]


def test_an_inbound_call_to_an_unknown_number_is_dropped(env: Env, db: PgEnv) -> None:
    event = {
        "kind": "participant_joined",
        "room": "aurevia-in-x",
        "is_phone": True,
        "attributes": {"sip.trunkPhoneNumber": "+918000000000", "sip.phoneNumber": OWN_PHONE},
    }
    assert _webhook(env, event).status_code == 200
    assert env.transport.closed == ["aurevia-in-x"] and env.transport.dispatches == []
    assert admin_fetch(db, "SELECT count(*) AS n FROM calls")[0]["n"] == 0


# --- Storage rules -----------------------------------------------------------------------


def test_compliance_tables_are_isolated_and_append_only(env: Env, db: PgEnv) -> None:
    tables = ("compliance_decisions", "consents", "do_not_call", "phone_numbers", "test_numbers")
    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(tables),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in tables]
    privileges = admin_fetch(
        db,
        "SELECT has_table_privilege($1, 'compliance_decisions', 'UPDATE') AS d_upd, "
        "has_table_privilege($1, 'compliance_decisions', 'DELETE') AS d_del, "
        "has_table_privilege($1, 'do_not_call', 'DELETE') AS dnc_del, "
        "has_column_privilege($1, 'consents', 'kind', 'UPDATE') AS kind_upd, "
        "has_column_privilege($1, 'consents', 'revoked_at', 'UPDATE') AS revoke",
        db.app_role,
    )[0]
    assert tuple(privileges) == (False, False, False, False, True)


def test_decision_history_is_per_tenant(env: Env, db: PgEnv) -> None:
    _setup_lines(env, test_number=None)
    _call_out(env, _lead(env))
    mine = env.client.get("/api/v1/compliance/decisions", headers=bearer(env.owner)).json()
    assert [d["reason_code"] for d in mine] == ["not_a_test_number"]
    other = signup(env.client, "other@example.com", "Other Co")
    assert env.client.get("/api/v1/compliance/decisions", headers=bearer(other)).json() == []
