"""WP-11.7 human-feel scorecard: the numbers the plan compares with the expert callers.

From what each call already stores (the transcript and per-turn timings), per call:

- **pause before replying**: end of the prospect's speech to the agent's first audio, p10, p50
  and p90 of the agent turns (``turn_metrics.e2e_latency_ms``);
- **talk ratio**: the agent's share of all words spoken (no audio durations are stored, so
  words stand in for talk time);
- **words per agent turn** and **questions per agent turn**;
- **reactions per minute**: replies opening with a short reaction (WP-11.3's measure);
- **backchannels per minute**: always None for now. The backchannel engine (WP-11.2) is not
  built, so there is nothing to count.

Read-only. The listening test, ten listeners' scores and Gate 11 are separate and need Virat
(``docs/06-testing/human-feel-scorecard.md``). Expert numbers come from Phase 12's timing
profile.

    python -m aurevia.evaluation.human_feel --tenant-id UUID [--days 7] [--out report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.evaluation.style import reaction_of


@dataclass(frozen=True)
class Line:
    speaker: str  # "prospect" or "agent"
    text: str


@dataclass(frozen=True)
class CallScorecard:
    call_id: str
    minutes: float | None
    agent_turns: int
    talk_ratio: float | None  # agent words / all words
    agent_words_per_turn: float | None
    questions_per_agent_turn: float | None
    pause_before_reply_p10_ms: int | None
    pause_before_reply_p50_ms: int | None
    pause_before_reply_p90_ms: int | None
    reactions_per_minute: float | None
    backchannels_per_minute: float | None = None  # WP-11.2 not built


def _words(text: str) -> int:
    return len(text.split())


def _percentile(values: Sequence[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def score_call(
    call_id: str,
    lines: Sequence[Line],
    reply_pauses_ms: Sequence[int],
    duration_seconds: float | None,
) -> CallScorecard:
    agent = [ln.text for ln in lines if ln.speaker == "agent" and ln.text.strip()]
    prospect = [ln.text for ln in lines if ln.speaker == "prospect" and ln.text.strip()]
    agent_words = sum(_words(t) for t in agent)
    all_words = agent_words + sum(_words(t) for t in prospect)
    minutes = duration_seconds / 60 if duration_seconds and duration_seconds > 0 else None
    reactions = sum(reaction_of(t) is not None for t in agent)
    pauses = [p for p in reply_pauses_ms if p >= 0]
    return CallScorecard(
        call_id=call_id,
        minutes=round(minutes, 2) if minutes else None,
        agent_turns=len(agent),
        talk_ratio=round(agent_words / all_words, 3) if all_words else None,
        agent_words_per_turn=round(agent_words / len(agent), 1) if agent else None,
        questions_per_agent_turn=(
            round(sum(t.count("?") for t in agent) / len(agent), 2) if agent else None
        ),
        pause_before_reply_p10_ms=_percentile(pauses, 0.1),
        pause_before_reply_p50_ms=_percentile(pauses, 0.5),
        pause_before_reply_p90_ms=_percentile(pauses, 0.9),
        reactions_per_minute=round(reactions / minutes, 2) if minutes else None,
    )


def summarize(cards: Sequence[CallScorecard]) -> dict[str, Any]:
    """Medians across calls; a measure no call has stays None."""

    def median(name: str) -> float | None:
        values = [getattr(c, name) for c in cards if getattr(c, name) is not None]
        return round(statistics.median(values), 3) if values else None

    fields = [f for f in CallScorecard.__dataclass_fields__ if f not in ("call_id", "agent_turns")]
    return {"calls": len(cards), **{f"median_{name}": median(name) for name in fields}}


async def scorecards(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> list[CallScorecard]:
    """Read one tenant's calls since a time. The session must carry that tenant's RLS context."""
    from aurevia.memory.models import ConversationMessage
    from aurevia.voice.metrics import TurnMetric
    from aurevia.voice.models import Call

    calls = (
        await session.scalars(
            select(Call).where(Call.tenant_id == tenant_id, Call.created_at >= since)
        )
    ).all()
    cards = []
    for call in calls:
        lines = [
            Line(m.speaker, m.text)
            for m in await session.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.call_id == call.id)
                .order_by(ConversationMessage.seq)
            )
        ]
        pauses = [
            int(ms)
            for ms in await session.scalars(
                select(TurnMetric.e2e_latency_ms).where(
                    TurnMetric.call_id == call.id,
                    TurnMetric.role == "agent",
                    TurnMetric.e2e_latency_ms.is_not(None),
                )
            )
            if ms is not None
        ]
        duration = (
            (call.ended_at - call.started_at).total_seconds()
            if call.started_at and call.ended_at
            else None
        )
        cards.append(score_call(str(call.id), lines, pauses, duration))
    return cards


async def _run(args: argparse.Namespace) -> int:
    from aurevia.config import Settings
    from aurevia.db.session import Database, set_tenant_context

    settings = Settings()
    if settings.database_url is None:
        print("error: set AUREVIA_DATABASE_URL (the application role)", file=sys.stderr)
        return 1
    tenant_id = uuid.UUID(args.tenant_id)
    database = Database(settings.database_url.get_secret_value())
    try:
        async with database.sessionmaker() as session:
            await set_tenant_context(session, tenant_id)
            since = datetime.now(UTC) - timedelta(days=args.days)
            cards = await scorecards(session, tenant_id, since)
    finally:
        await database.dispose()
    report = {"summary": summarize(cards), "calls": [asdict(c) for c in cards]}
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        await asyncio.to_thread(Path(args.out).write_text, text, encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.evaluation.human_feel")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default=None, help="also write per-call numbers to this file")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
