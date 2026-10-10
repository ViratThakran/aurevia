"""Repeatable latency / model-request / token benchmark for agent turns (text path, no audio).

    python scripts/voice_benchmark.py --runs 2 --out report.json [--label new]

Runs inside the API container (real database, real model and key, real provider limits).
Each run uses a throwaway workspace; no LiveKit room is opened and nothing is dialed.

It deliberately uses only APIs that exist both before and after the speak-first change, so the
same script measures either version (put the other version's ``src`` first on PYTHONPATH).

Per scenario it reports:
- first word per turn (ms): request sent -> first text delta (backend + model; no STT/TTS)
- model requests per turn, including failed attempts and the bookkeeping pass
- input / output tokens per turn
- rate-limited requests (provider refused) and harness retries
- failed turns
- cost per scenario at the given per-1M-token prices (the platform price table is empty)
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from aurevia.config import Settings
from aurevia.db.session import set_tenant_context
from aurevia.main import create_app
from aurevia.providers.fakes import FakeVoiceTransport
from aurevia.usage.models import UsageEvent

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

# (name, prospect lines). Same lines for every version measured.
SCENARIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ordinary",
        (
            "Yes, I have a couple of minutes.",
            "We are a textile company with about forty staff.",
            "Our current policy renews in March.",
        ),
    ),
    (
        "objection",
        (
            "Honestly it sounds expensive, and we already have a broker.",
            "Why would we switch? What do you do differently?",
        ),
    ),
    ("slot_lookup", ("Sure, what times do you have next week for the specialist?",)),
    (
        "booking",
        (
            "Yes, we have forty people and renewal is in March. Let's set up a call.",
            "What times do you have on Monday or Tuesday?",
            "The first one works. Please book it.",
        ),
    ),
    ("handoff", ("I'd rather speak to a real person from your team, please.",)),
    ("do_not_call", ("Please don't call this number again.",)),
)

RATE_LIMIT_WAITS = (20, 40, 60)


@dataclass
class Turn:
    first_word_ms: int = -1
    error: str | None = None
    retries: int = 0


@dataclass
class ScenarioRun:
    name: str
    turns: list[Turn] = field(default_factory=list)
    requests: int = 0
    rate_limited_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tools: list[str] = field(default_factory=list)


def _stream_turn(
    client: TestClient, call_id: str, headers: dict[str, str], history: list[dict[str, str]]
) -> tuple[str, int, str | None, list[str]]:
    started = time.monotonic()
    first = -1
    text: list[str] = []
    tools: list[str] = []
    with client.stream(
        "POST", f"/internal/v1/calls/{call_id}/turns", json={"history": history}, headers=headers
    ) as response:
        if response.status_code != 200:
            response.read()
            return "", -1, f"http_{response.status_code}", tools
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            if event["type"] == "delta":
                if first < 0:
                    first = int((time.monotonic() - started) * 1000)
                text.append(event["text"])
            elif event["type"] == "tool":
                tools.append(f"{event['name']}:{'ok' if event['ok'] else 'failed'}")
            elif event["type"] == "error":
                return "".join(text), first, event.get("code", "error"), tools
    return "".join(text).strip(), first, None, tools


async def _usage(client: TestClient, tenant_id: uuid.UUID, call_id: str) -> list[Any]:
    database = client.app.state.database  # type: ignore[attr-defined]
    async with database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        rows = await session.execute(
            select(
                UsageEvent.served_model, UsageEvent.input_tokens, UsageEvent.output_tokens
            ).where(UsageEvent.call_id == uuid.UUID(call_id), UsageEvent.kind == "llm")
        )
        return list(rows)


def _settled_usage(client: TestClient, tenant_id: uuid.UUID, call_id: str) -> list[Any]:
    """Wait until background model calls (the bookkeeping pass) have been recorded."""
    assert client.portal is not None  # noqa: S101 - the client runs inside "with"
    previous, stable_since = -1, time.monotonic()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        rows = client.portal.call(_usage, client, tenant_id, call_id)
        if len(rows) != previous:
            previous, stable_since = len(rows), time.monotonic()
        elif time.monotonic() - stable_since > 4:
            return rows
        time.sleep(0.25)
    return client.portal.call(_usage, client, tenant_id, call_id)


def run_scenario(
    client: TestClient,
    transport: FakeVoiceTransport,
    owner: dict[str, str],
    tenant_id: uuid.UUID,
    name: str,
    lines: tuple[str, ...],
) -> ScenarioRun:
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
    result = ScenarioRun(name=name)
    for line in lines:
        history.append({"role": "prospect", "text": line})
        turn = Turn()
        for wait in (*RATE_LIMIT_WAITS, None):
            reply, first, error, tools = _stream_turn(client, call_id, headers, history)
            if error == "rate_limited" and wait is not None:
                turn.retries += 1
                time.sleep(wait)
                continue
            break
        turn.first_word_ms, turn.error = first, error
        result.tools.extend(tools)
        result.turns.append(turn)
        history.append({"role": "agent", "text": reply or "(no reply)"})
        time.sleep(3)  # the prospect's next words come seconds later in a real call
    rows = _settled_usage(client, tenant_id, call_id)
    client.post(f"/internal/v1/calls/{call_id}/end", json={"reason": "benchmark"}, headers=headers)
    result.requests = len(rows)
    result.rate_limited_requests = sum(1 for r in rows if r[0] is None)
    result.input_tokens = sum(r[1] or 0 for r in rows)
    result.output_tokens = sum(r[2] or 0 for r in rows)
    return result


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarize(runs: list[ScenarioRun], price_in: float, price_out: float) -> dict[str, Any]:
    by_name: dict[str, list[ScenarioRun]] = {}
    for run in runs:
        by_name.setdefault(run.name, []).append(run)
    out: dict[str, Any] = {}
    for name, group in by_name.items():
        turns = [t for r in group for t in r.turns]
        ms = [t.first_word_ms for t in turns if t.first_word_ms >= 0 and not t.error]
        n_turns = len(turns)
        tokens_in = sum(r.input_tokens for r in group)
        tokens_out = sum(r.output_tokens for r in group)
        cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
        out[name] = {
            "runs": len(group),
            "turns": n_turns,
            "first_word_ms_p50": _pct(ms, 0.5),
            "first_word_ms_p95": _pct(ms, 0.95),
            "model_requests_per_turn": round(sum(r.requests for r in group) / n_turns, 2),
            "rate_limited_requests": sum(r.rate_limited_requests for r in group),
            "harness_retries": sum(t.retries for t in turns),
            "failed_turns": sum(1 for t in turns if t.error),
            "input_tokens_per_turn": round(tokens_in / n_turns),
            "output_tokens_per_turn": round(tokens_out / n_turns),
            "cost_usd_per_scenario": round(cost / len(group), 6),
            "tools": sorted({tool for r in group for tool in r.tools}),
        }
    all_ms = [
        t.first_word_ms for r in runs for t in r.turns if t.first_word_ms >= 0 and not t.error
    ]
    out["_all"] = {
        "turns": sum(len(r.turns) for r in runs),
        "first_word_ms_p50": _pct(all_ms, 0.5),
        "first_word_ms_p95": _pct(all_ms, 0.95),
        "model_requests_per_turn": round(
            sum(r.requests for r in runs) / max(1, sum(len(r.turns) for r in runs)), 2
        ),
        "failed_turns": sum(1 for r in runs for t in r.turns if t.error),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--only", nargs="*")
    # Gemini 3.5 Flash-Lite paid tier, USD per 1M tokens (ai.google.dev/gemini-api/docs/pricing).
    parser.add_argument("--price-in", type=float, default=0.30)
    parser.add_argument("--price-out", type=float, default=2.50)
    args = parser.parse_args()

    app = create_app(Settings())
    transport = FakeVoiceTransport()
    app.state.voice_transport = transport
    runs: list[ScenarioRun] = []
    with TestClient(app) as client:
        tokens = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"bench-{secrets.token_hex(4)}@example.com",
                "password": secrets.token_urlsafe(18),
                "tenant_name": "Benchmark (throwaway)",
            },
        )
        tokens.raise_for_status()
        access = tokens.json()["access_token"]
        owner = {"Authorization": f"Bearer {access}"}
        tenant_id = uuid.UUID(
            json.loads(base64.urlsafe_b64decode(access.split(".")[1] + "=="))["tid"]
        )
        client.put("/api/v1/agents/default", json=AGENT, headers=owner).raise_for_status()
        for repeat in range(args.runs):
            for name, lines in SCENARIOS:
                if args.only and name not in args.only:
                    continue
                run = run_scenario(client, transport, owner, tenant_id, name, lines)
                runs.append(run)
                print(
                    f"[{args.label}] run {repeat + 1} {name}: first word "
                    f"{[t.first_word_ms for t in run.turns]} ms, {run.requests} model requests, "
                    f"errors {[t.error for t in run.turns if t.error]}",
                    flush=True,
                )
    report = {
        "label": args.label,
        "prices_per_million": {"input": args.price_in, "output": args.price_out},
        "summary": summarize(runs, args.price_in, args.price_out),
        "runs": [r.__dict__ | {"turns": [t.__dict__ for t in r.turns]} for r in runs],
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
