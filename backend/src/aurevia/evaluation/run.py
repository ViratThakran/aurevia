"""Run the sales scenarios against the real backend and model (no audio, no phone).

    python -m aurevia.evaluation.run [--only NAME ...] [--report report.json]

Uses the configured database and model (e.g. inside the API container). Each run creates a
throwaway workspace (``eval-<random>@example.com``), so it never touches real tenants. The voice
transport is a fake: no LiveKit room is opened and nothing is dialed. Exit code 1 if any
scenario fails.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys
import time
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from aurevia.api.internal.calls import PENDING_BOOKKEEPING
from aurevia.config import Settings
from aurevia.conversation.prompt import PROMPT_VERSION
from aurevia.db.session import set_tenant_context
from aurevia.evaluation.scenarios import SCENARIOS, Scenario, ScenarioResult, judge
from aurevia.evaluation.style import measure
from aurevia.main import create_app
from aurevia.providers.fakes import FakeVoiceTransport
from aurevia.sales.models import ToolExecution

AGENT = {
    "name": "Aria",
    "company_name": "Sunrise Insurance Brokers",
    "company_description": (
        "Sunrise Insurance Brokers helps businesses in Pune with 10 to 200 employees buy group "
        "health insurance. We compare plans from several insurers, handle paperwork and support "
        "claims. Prices depend on the team and the insurer; a specialist prepares quotes."
    ),
    "objective": "Understand team size and renewal date, then book a call with a specialist.",
    "greeting": "Hi, this is Aria, an AI assistant calling from Sunrise Insurance Brokers. "
    "Is now a good time for a quick chat?",
    "language": "en-IN",
    "voice": None,
}


def _turn(
    client: TestClient, call_id: str, headers: dict[str, str], history: list[dict[str, str]]
) -> tuple[str, list[dict[str, Any]], int]:
    started = time.monotonic()
    first_ms = -1
    text: list[str] = []
    tools: list[dict[str, Any]] = []
    with client.stream(
        "POST", f"/internal/v1/calls/{call_id}/turns", json={"history": history}, headers=headers
    ) as response:
        if response.status_code != 200:
            response.read()
            raise RuntimeError(f"turn failed: {response.status_code} {response.text[:200]}")
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event["type"] == "delta":
                if first_ms < 0:
                    first_ms = int((time.monotonic() - started) * 1000)
                text.append(event["text"])
            elif event["type"] == "tool":
                tools.append(event)
            elif event["type"] == "error":
                raise RuntimeError(f"model error: {event.get('code')}")
    return "".join(text).strip(), tools, first_ms


async def _tools_run(client: TestClient, call_id: str) -> list[dict[str, Any]]:
    """Every tool run on the call, including the bookkeeping pass after each reply (those are
    not in the turn stream), once the pending passes have finished."""
    for _ in range(300):  # up to 30 s for the passes still running
        if not PENDING_BOOKKEEPING:
            break
        await asyncio.sleep(0.1)
    database = client.app.state.database  # type: ignore[attr-defined]
    tenant_id = uuid.UUID(client.app.state.eval_tenant_id)  # type: ignore[attr-defined]
    async with database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        rows = await session.execute(
            select(ToolExecution.tool, ToolExecution.status)
            .where(ToolExecution.call_id == uuid.UUID(call_id))
            .order_by(ToolExecution.created_at)
        )
        return [{"name": tool, "ok": status == "ok"} for tool, status in rows]


RATE_LIMIT_WAITS = (20, 40, 60)  # seconds; model quotas are per minute


def _turn_with_retry(
    client: TestClient, call_id: str, headers: dict[str, str], history: list[dict[str, str]]
) -> tuple[str, list[dict[str, Any]], int]:
    """The provider's per-minute quota is not the agent's fault: wait and try again."""
    for wait in (*RATE_LIMIT_WAITS, None):
        try:
            return _turn(client, call_id, headers, history)
        except RuntimeError as exc:
            if "rate_limited" not in str(exc) or wait is None:
                raise
            print(f"      (model rate limit: waiting {wait}s)")
            time.sleep(wait)
    raise AssertionError("unreachable")


def run_scenario(
    client: TestClient, transport: FakeVoiceTransport, owner: dict[str, str], scenario: Scenario
) -> ScenarioResult:
    lead = client.post(
        "/api/v1/leads",
        json={"name": "Ravi Kumar", "company": "Kumar Textiles", "phone": "+919800000001"},
        headers=owner,
    ).json()
    session = client.post("/api/v1/voice/sessions", json={"lead_id": lead["id"]}, headers=owner)
    session.raise_for_status()
    call_id = session.json()["call_id"]
    token = json.loads(transport.rooms[-1][2])["call_token"]
    headers = {"Authorization": f"Bearer {token}"}
    opening = client.post(f"/internal/v1/calls/{call_id}/start", headers=headers).json()

    history = [{"role": "agent", "text": opening["greeting"]}]
    result = ScenarioResult(name=scenario.name, passed=False)
    try:
        for line in scenario.prospect_lines:
            history.append({"role": "prospect", "text": line})
            reply, tools, first_ms = _turn_with_retry(client, call_id, headers, history)
            history.append({"role": "agent", "text": reply})
            result.replies.append(reply)
            result.tools.extend(tools)
            result.reply_ms.append(first_ms)
        assert client.portal is not None  # noqa: S101 - the client runs inside "with"
        # The database is the full record: tools before the reply and those run after it.
        result.tools = client.portal.call(_tools_run, client, call_id)
        result.failures = judge(scenario, result.replies, result.tools)
    except RuntimeError as exc:
        result.failures = [str(exc)]
    finally:
        client.post(
            f"/internal/v1/calls/{call_id}/end", json={"reason": "evaluation"}, headers=headers
        )
    result.passed = not result.failures
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.evaluation.run")
    parser.add_argument("--only", nargs="*", help="scenario names to run")
    parser.add_argument("--report", help="write a JSON report here")
    args = parser.parse_args(argv)
    scenarios = [s for s in SCENARIOS if not args.only or s.name in args.only]

    app = create_app(Settings())
    transport = FakeVoiceTransport()
    app.state.voice_transport = transport  # no LiveKit rooms, no agent dispatch
    results: list[ScenarioResult] = []
    with TestClient(app) as client:
        email = f"eval-{secrets.token_hex(4)}@example.com"
        tokens = client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": secrets.token_urlsafe(18),
                "tenant_name": "Evaluation (throwaway)",
            },
        )
        tokens.raise_for_status()
        access = tokens.json()["access_token"]
        owner = {"Authorization": f"Bearer {access}"}
        claims = json.loads(base64.urlsafe_b64decode(access.split(".")[1] + "=="))
        app.state.eval_tenant_id = claims["tid"]
        client.put("/api/v1/agents/default", json=AGENT, headers=owner).raise_for_status()
        for scenario in scenarios:
            result = run_scenario(client, transport, owner, scenario)
            results.append(result)
            mark = "PASS" if result.passed else "FAIL"
            timing = [ms for ms in result.reply_ms if ms >= 0]
            median = sorted(timing)[len(timing) // 2] if timing else -1
            print(f"{mark}  {scenario.name:<38} first-word median {median} ms")
            for failure in result.failures:
                print(f"      - {failure}")

    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} scenarios passed")
    style = measure([r.replies for r in results])
    timings = sorted(ms for r in results for ms in r.reply_ms if ms >= 0)
    p50 = timings[len(timings) // 2] if timings else -1
    p95 = timings[min(len(timings) - 1, int(len(timings) * 0.95))] if timings else -1
    print(f"first word over text: p50 {p50} ms, p95 {p95} ms")
    print("style: " + ", ".join(f"{k}={v}" for k, v in style.as_dict().items()))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "prompt_version": PROMPT_VERSION,
                    "style": style.as_dict(),
                    "first_word_ms": {"p50": p50, "p95": p95},
                    "scenarios": [r.__dict__ for r in results],
                },
                handle,
                indent=2,
                default=str,
            )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
