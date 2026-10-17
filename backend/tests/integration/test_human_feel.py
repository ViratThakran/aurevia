"""WP-11.7: the scorecard reads one tenant's stored calls, inside that tenant's RLS scope."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aurevia.db.session import set_tenant_context
from aurevia.evaluation.human_feel import CallScorecard, scorecards
from tests.integration.conftest import PgEnv, me, signup
from tests.integration.test_sales_tools import Env, _call, _lead
from tests.integration.test_sales_tools import env as env  # the fixture


def _cards(db: PgEnv, tenant_id: str) -> list[CallScorecard]:
    async def run() -> list[CallScorecard]:
        engine = create_async_engine(db.app_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await set_tenant_context(session, uuid.UUID(tenant_id))
                since = datetime.now(UTC) - timedelta(days=1)
                return await scorecards(session, uuid.UUID(tenant_id), since)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_scorecard_reads_a_stored_call_and_stays_in_its_tenant(env: Env, db: PgEnv) -> None:
    call_id, token = _call(env, _lead(env))
    headers = {"Authorization": f"Bearer {token}"}
    lines = [
        {"seq": 0, "speaker": "agent", "text": "Hello, this is Meera, an AI assistant."},
        {"seq": 1, "speaker": "prospect", "text": "Hi, go ahead."},
        {"seq": 2, "speaker": "agent", "text": "Hm, okay. How many people are on your team?"},
    ]
    sent = env.client.post(
        f"/internal/v1/calls/{call_id}/transcript", json={"lines": lines}, headers=headers
    )
    assert sent.status_code in (200, 201, 204), sent.text
    metrics = {
        "turns": [
            {"seq": 0, "role": "agent", "e2e_latency_ms": 1100},
            {"seq": 1, "role": "agent", "e2e_latency_ms": 1300},
        ]
    }
    env.client.post(f"/internal/v1/calls/{call_id}/turn-metrics", json=metrics, headers=headers)
    env.client.post(f"/internal/v1/calls/{call_id}/end", json={"reason": "done"}, headers=headers)

    tenant_id = me(env.client, env.owner)["tenant"]["id"]
    cards = _cards(db, tenant_id)
    assert [c.call_id for c in cards] == [call_id]
    card = cards[0]
    assert card.agent_turns == 2 and card.pause_before_reply_p50_ms in (1100, 1300)
    assert card.talk_ratio is not None and card.talk_ratio > 0.5
    assert card.backchannels_per_minute is None

    other = signup(env.client, "other@example.com", "Other Co")
    assert _cards(db, me(env.client, other)["tenant"]["id"]) == []
