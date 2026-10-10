"""Phase 5: model tool requests go through validation, rules and audit; failures stay failures."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aurevia.api.internal import calls as calls_api
from aurevia.gateway import ModelGateway
from aurevia.main import create_app
from aurevia.providers.fakes import FakeModelProvider, FakeTurn, FakeVoiceTransport
from aurevia.providers.model import ToolCall
from aurevia.sales.state import STATE_GOALS, SalesState
from tests.conftest import TEST_JWT_SECRET, SettingsFactory
from tests.integration.conftest import PgEnv, admin_fetch, bearer, signup


@dataclass
class Env:
    client: TestClient
    transport: FakeVoiceTransport
    model: FakeModelProvider
    owner: dict[str, Any]


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
        owner = signup(client, "owner@example.com", "Acme")
        yield Env(client, transport, model, owner)


def _lead(env: Env, name: str = "Ravi") -> str:
    response = env.client.post("/api/v1/leads", json={"name": name}, headers=bearer(env.owner))
    return str(response.json()["id"])


def _call(env: Env, lead_id: str | None) -> tuple[str, str]:
    body = {"lead_id": lead_id} if lead_id else {}
    call_id = env.client.post(
        "/api/v1/voice/sessions", json=body, headers=bearer(env.owner)
    ).json()["call_id"]
    token = json.loads(env.transport.rooms[-1][2])["call_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        env.client.post(f"/internal/v1/calls/{call_id}/start", headers=headers).status_code == 200
    )
    return call_id, token


def _turn(env: Env, call_id: str, token: str, said: str = "Okay.") -> list[dict[str, Any]]:
    response = env.client.post(
        f"/internal/v1/calls/{call_id}/turns",
        json={"history": [{"role": "prospect", "text": said}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line]


def _tool(name: str, call_id: str = "c1", **arguments: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _tool_results_seen_by_model(env: Env) -> list[dict[str, Any]]:
    last = env.model.requests[-1].messages[-1]
    return [dict(result.content) for result in last.tool_results]


def test_rejected_booking_reaches_the_model_as_not_ok(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    env.model.replies += [
        FakeTurn(
            text="Let me book that.",
            tool_calls=(_tool("book_meeting", start="2020-01-01T10:00:00+00:00"),),
        ),
        "Sorry, that time is not available.",
    ]
    lines = _turn(env, call_id, token, "Book me in for then.")

    assert {"type": "tool", "name": "book_meeting", "ok": False} in lines
    seen = _tool_results_seen_by_model(env)
    assert seen[0]["ok"] is False and seen[0]["error"] == "slot_unavailable"
    assert admin_fetch(db, "SELECT count(*) AS n FROM appointments")[0]["n"] == 0
    audit = admin_fetch(db, "SELECT tool, status, error_code FROM tool_executions")
    assert [(r["tool"], r["status"], r["error_code"]) for r in audit] == [
        ("book_meeting", "rejected", "slot_unavailable")
    ]
    # The prompt tells the model the rule it must follow.
    assert "unless the tool result says ok is true" in env.model.requests[0].system


def test_slots_then_booking_then_no_double_booking(env: Env, db: PgEnv) -> None:
    lead_a, lead_b = _lead(env, "Asha"), _lead(env, "Bala")
    call_a, token_a = _call(env, lead_a)

    env.model.replies += [
        FakeTurn(tool_calls=(_tool("get_available_slots", days=7),)),
        "Tuesday works?",
    ]
    _turn(env, call_a, token_a, "When are you free?")
    slots = _tool_results_seen_by_model(env)[0]["slots"]
    assert slots and "spoken" in slots[0]
    start = slots[0]["start"]

    env.model.replies += [
        FakeTurn(tool_calls=(_tool("book_meeting", "c2", start=start),)),
        "Booked.",
    ]
    lines = _turn(env, call_a, token_a, "Yes, the first one.")
    assert {"type": "tool", "name": "book_meeting", "ok": True} in lines
    assert _tool_results_seen_by_model(env)[0]["ok"] is True

    # The very same request again (e.g. a retry) reports the first result and books nothing new.
    env.model.replies += [FakeTurn(tool_calls=(_tool("book_meeting", "c3", start=start),)), "Done."]
    _turn(env, call_a, token_a, "Book it.")
    assert admin_fetch(db, "SELECT count(*) AS n FROM appointments")[0]["n"] == 1

    # Another prospect cannot take the same slot.
    call_b, token_b = _call(env, lead_b)
    env.model.replies += [FakeTurn(tool_calls=(_tool("book_meeting", start=start),)), "Sorry."]
    _turn(env, call_b, token_b, "Same time for me.")
    assert _tool_results_seen_by_model(env)[0]["error"] == "slot_unavailable"
    assert admin_fetch(db, "SELECT count(*) AS n FROM appointments")[0]["n"] == 1


def test_recording_tools_and_validation(env: Env, db: PgEnv) -> None:
    lead_id = _lead(env)
    call_id, token = _call(env, lead_id)
    env.model.replies += [
        FakeTurn(
            tool_calls=(
                _tool("qualify_lead", "q", need="cover for 40 staff", company_size=40),
                _tool("mark_interested", "i", note="wants a quote"),
                _tool("log_objection", "o", category="price", detail="premiums too high"),
                _tool("add_note", "n", text="Prefers WhatsApp."),
                _tool(
                    "schedule_followup",
                    "f",
                    due_at="2020-01-01T10:00:00+05:30",
                    channel="call",
                    note="call back",
                ),
                _tool("log_objection", "bad", category="weather", detail="??"),
                _tool("send_email", "u", to="x@example.com"),
            ),
        ),
        "Got it.",
    ]
    _turn(env, call_id, token)
    results = _tool_results_seen_by_model(env)
    assert [(r["ok"], r.get("error")) for r in results] == [
        (True, None),
        (True, None),
        (True, None),
        (True, None),
        (False, "in_the_past"),
        (False, "invalid_arguments"),
        (False, "unknown_tool"),
    ]

    lead = admin_fetch(
        db, "SELECT interest, qualification FROM leads WHERE id = $1::uuid", lead_id
    )[0]
    assert lead["interest"] == "interested"
    assert json.loads(lead["qualification"]) == {"need": "cover for 40 staff", "company_size": 40}
    assert admin_fetch(db, "SELECT category FROM objections")[0]["category"] == "price"
    assert admin_fetch(db, "SELECT count(*) AS n FROM lead_notes")[0]["n"] == 1
    assert admin_fetch(db, "SELECT count(*) AS n FROM followups")[0]["n"] == 0


def test_call_without_lead_and_handoff(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, None)
    env.model.replies += [
        FakeTurn(
            tool_calls=(
                _tool("qualify_lead", "q", need="x"),
                _tool("flag_for_handoff", "h", reason="asked for a person", urgency="high"),
            )
        ),
        "A colleague will call you.",
    ]
    lines = _turn(env, call_id, token, "Can I talk to a human?")
    seen = _tool_results_seen_by_model(env)
    assert (seen[0]["ok"], seen[0]["error"]) == (False, "no_lead")
    assert seen[1]["ok"] is True
    assert lines[-1] == {"type": "done", "sales_state": "human_handoff"}
    handoff = admin_fetch(db, "SELECT urgency, status, lead_id FROM handoffs")[0]
    assert (handoff["urgency"], handoff["status"], handoff["lead_id"]) == ("high", "open", None)


def test_stage_changes_follow_the_state_machine(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    env.model.replies += [FakeTurn(tool_calls=(_tool("set_stage", stage="follow_up"),)), "Hmm."]
    lines = _turn(env, call_id, token)
    assert _tool_results_seen_by_model(env)[0]["error"] == "transition_not_allowed"
    assert lines[-1]["sales_state"] == "discovery"

    env.model.replies += [FakeTurn(tool_calls=(_tool("set_stage", "s2", stage="pitch"),)), "So..."]
    lines = _turn(env, call_id, token)
    assert lines[-1]["sales_state"] == "pitch"


def test_tool_loop_is_bounded(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    env.model.replies += [
        FakeTurn(tool_calls=(_tool("add_note", f"n{i}", text=f"note {i}"),)) for i in range(3)
    ] + ["Final words."]
    lines = _turn(env, call_id, token)
    assert lines[-1]["type"] == "done"
    assert env.model.requests[-1].tools == ()  # the last round offers no tools
    text = "".join(line.get("text", "") for line in lines if line["type"] == "delta")
    assert text.strip() == "Final words."


def test_sales_tables_are_rls_protected(env: Env, db: PgEnv) -> None:
    tables = (
        "appointments",
        "followups",
        "handoffs",
        "lead_notes",
        "objections",
        "scheduling_settings",
        "tool_executions",
    )
    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY($1::text[]) ORDER BY relname",
        list(tables),
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [(t, True, True) for t in tables]


def test_spoken_reply_with_successful_record_only_tools_ends_the_turn(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    env.model.replies += [
        FakeTurn(
            text="Forty staff, got it.",
            tool_calls=(_tool("qualify_lead", company_size=40), _tool("add_note", "n", text="hi")),
        ),
    ]
    lines = _turn(env, call_id, token)
    assert len(env.model.requests) == 1  # no extra model round of silence
    assert [line["ok"] for line in lines if line["type"] == "tool"] == [True, True]
    assert lines[-1]["type"] == "done"


def _wait_for(condition: Any, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the bookkeeping pass"
        time.sleep(0.05)


def test_speech_first_then_bookkeeping_after_the_reply(env: Env, db: PgEnv) -> None:
    """The reply never waits for bookkeeping tools; they run in a second call afterwards."""
    call_id, token = _call(env, _lead(env))
    env.model.replies += ["Forty people, renewal in March. Who handles claims today?"]
    env.model.bookkeeping_replies += [
        FakeTurn(tool_calls=(_tool("qualify_lead", company_size=40), _tool("book_meeting", "b"))),
    ]
    lines = _turn(env, call_id, token, said="We are forty people, renewal in March.")

    assert [line["type"] for line in lines][-1] == "done"
    speech = env.model.requests[-1]
    offered = {t.name for t in speech.tools}
    assert "qualify_lead" not in offered and "set_stage" not in offered
    # Actions the agent talks about, or that stop future calls, are never deferred.
    assert {
        "get_available_slots",
        "book_meeting",
        "cancel_meeting",
        "schedule_followup",
        "flag_for_handoff",
        "request_do_not_call",
        "mark_not_interested",
    } <= offered

    _wait_for(lambda: env.model.bookkeeping_requests)
    _wait_for(
        lambda: admin_fetch(
            db, "SELECT 1 FROM tool_executions WHERE tool = 'qualify_lead' AND status = 'ok'"
        )
    )
    bookkeeping = env.model.bookkeeping_requests[-1]
    assert {t.name for t in bookkeeping.tools} == {
        "set_stage",
        "qualify_lead",
        "mark_interested",
        "log_objection",
        "add_note",
    }
    # It sees what was actually said, and cannot slip in a side effect such as a booking.
    said = [m.content for m in bookkeeping.messages]
    assert "Forty people, renewal in March. Who handles claims today?" in said
    assert not admin_fetch(db, "SELECT 1 FROM tool_executions WHERE tool = 'book_meeting'")


def test_bookkeeping_failure_never_breaks_the_spoken_reply(
    env: Env, db: PgEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls_api, "BOOKKEEPING_RETRY_SECONDS", 0)
    call_id, token = _call(env, _lead(env))
    env.model.replies += ["We have forty people.", "Tuesday works?"]
    env.model.bookkeeping_errors += ["rate_limited", "rate_limited"]  # first try and retry
    env.model.bookkeeping_replies += [
        FakeTurn(tool_calls=(_tool("qualify_lead", company_size=40),))
    ]

    lines = _turn(env, call_id, token, said="We are forty people.")
    assert [line["type"] for line in lines] == ["delta"] * 4 + ["done"]
    _wait_for(lambda: len(env.model.bookkeeping_requests) == 2)
    # The next turn still works, and nothing was recorded from the lost pass.
    assert _turn(env, call_id, token)[-1]["type"] == "done"
    assert not admin_fetch(db, "SELECT 1 FROM tool_executions WHERE tool = 'qualify_lead'")


def test_bookkeeping_retries_once_after_a_transient_failure(
    env: Env, db: PgEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls_api, "BOOKKEEPING_RETRY_SECONDS", 0)
    call_id, token = _call(env, _lead(env))
    env.model.replies += ["Forty people, noted."]
    env.model.bookkeeping_errors += ["rate_limited"]
    env.model.bookkeeping_replies += [
        FakeTurn(tool_calls=(_tool("qualify_lead", company_size=40),))
    ]
    _turn(env, call_id, token, said="We are forty people.")
    _wait_for(
        lambda: admin_fetch(
            db, "SELECT 1 FROM tool_executions WHERE tool = 'qualify_lead' AND status = 'ok'"
        )
    )
    assert len(env.model.bookkeeping_requests) == 2


def test_next_turn_waits_for_the_previous_bookkeeping(env: Env, db: PgEnv) -> None:
    """The stage recorded after reply 1 is in the prompt for reply 2, never one turn late."""
    call_id, token = _call(env, _lead(env))
    env.model.bookkeeping_delay = 0.5  # still running when the prospect answers
    env.model.replies += ["Tell me about your team.", "And when is the renewal?"]
    env.model.bookkeeping_replies += [
        FakeTurn(tool_calls=(_tool("set_stage", stage="qualification"),))
    ]
    _turn(env, call_id, token, said="Sure, go ahead.")
    _turn(env, call_id, token, said="We have forty people.")
    assert STATE_GOALS[SalesState.QUALIFICATION] in env.model.requests[-1].system


def test_required_actions_happen_in_the_spoken_turn(env: Env, db: PgEnv) -> None:
    """Do-not-call is executed before the turn ends, not left to the bookkeeping pass."""
    call_id, token = _call(env, _lead(env))
    env.model.replies += [
        FakeTurn(
            text="Understood, we will not call you again.",
            tool_calls=(_tool("request_do_not_call", note="prospect asked"),),
        )
    ]
    lines = _turn(env, call_id, token, said="Please don't call me again.")
    tool_lines = [line for line in lines if line["type"] == "tool"]
    assert tool_lines == [{"type": "tool", "name": "request_do_not_call", "ok": True}]
    assert lines.index(tool_lines[0]) < len(lines) - 1  # before "done"


def test_bookkeeping_tools_are_validated_scoped_and_audited(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    env.model.replies += ["Got it."]
    env.model.bookkeeping_replies += [
        FakeTurn(
            tool_calls=(
                _tool("qualify_lead", "q", company_size=40),
                _tool("set_stage", "s", stage="no_such_stage"),
            )
        )
    ]
    _turn(env, call_id, token, said="Forty people.")
    _wait_for(lambda: len(admin_fetch(db, "SELECT 1 FROM tool_executions")) == 2)
    rows = admin_fetch(
        db,
        "SELECT t.tool, t.status, t.tenant_id = c.tenant_id AS same_tenant "
        "FROM tool_executions t JOIN calls c ON c.id = t.call_id ORDER BY t.created_at",
    )
    assert [(r["tool"], r["status"], r["same_tenant"]) for r in rows] == [
        ("qualify_lead", "ok", True),
        ("set_stage", "rejected", True),  # invalid arguments are rejected, still audited
    ]


def test_results_the_model_must_see_get_a_follow_up_round(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    # A failed record-only call: the model hears about it.
    env.model.replies += [
        FakeTurn(
            text="Noted.", tool_calls=(_tool("log_objection", category="weather", detail="x"),)
        ),
        "Sorry, let me rephrase.",
    ]
    _turn(env, call_id, token)
    assert len(env.model.requests) == 2
    # A lookup: the model needs the answer before it can speak about it.
    env.model.replies += [
        FakeTurn(text="Let me check.", tool_calls=(_tool("get_available_slots", "s"),)),
        "Tuesday at ten?",
    ]
    _turn(env, call_id, token)
    assert len(env.model.requests) == 4


def test_a_past_start_date_searches_from_today(env: Env, db: PgEnv) -> None:
    """Models guess past dates (even the wrong year); that must not return 'nothing free'."""
    call_id, token = _call(env, _lead(env))
    env.model.replies += [
        FakeTurn(tool_calls=(_tool("get_available_slots", from_date="2025-10-13", days=3),)),
        "Monday works?",
    ]
    _turn(env, call_id, token)
    result = _tool_results_seen_by_model(env)[0]
    assert result["ok"] is True and result["slots"]
    assert "in the past" in result["note"] and result["today"]
