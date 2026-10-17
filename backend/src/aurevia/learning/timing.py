"""WP-12.5: a timing profile of how the expert callers talk. Aggregates only, never text.

From the line timings of **call** sources (talks have none and never count), per sales stage
when stage labels exist, otherwise for the whole call:

- **pause before replying**: the expert's turn start minus the prospect's turn end, p10, p50
  and p90, in ms. Negative values mean the expert started before the prospect stopped;
- **overlap rate**: the share of expert turns that start before the prospect has finished;
- **backchannels per minute**: short listening sounds from the expert ("hmm", "haan", "right")
  while the prospect is talking, and where they fall: during the prospect's speech
  (``mid_turn``) or in a gap;
- **speech rate**: the expert's words per minute;
- **turn length**: the expert's turn duration, p50, in ms.

The profile holds counts and percentiles only: no words, no names, no voice fingerprints. The
backchannel engine (WP-11.2, waiting on design approval) is meant to read it for its defaults.

    python -m aurevia.learning.timing --tenant-id UUID --out profile.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKCHANNEL_WORDS = frozenset(
    {
        "hmm",
        "hm",
        "mm",
        "mhm",
        "uh-huh",
        "okay",
        "ok",
        "right",
        "yeah",
        "yes",
        "sure",
        "haan",
        "han",
        "achha",
        "acha",
        "theek",
        "hai",
        "ji",
        "accha",
    }
)
PROFILE_VERSION = 1
ALL = "all"


@dataclass(frozen=True)
class TimedLine:
    speaker: str  # "expert" or "prospect" (others are ignored)
    start_ms: int
    end_ms: int
    words: int  # word count only
    is_backchannel: bool = False
    stage: str | None = None


def is_backchannel_text(text: str) -> bool:
    words = re.findall(r"[a-z-]+", text.lower())
    return 0 < len(words) <= 2 and set(words) <= BACKCHANNEL_WORDS


def _pct(values: Sequence[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


@dataclass
class StageProfile:
    expert_turns: int = 0
    pause_before_reply_p10_ms: int | None = None
    pause_before_reply_p50_ms: int | None = None
    pause_before_reply_p90_ms: int | None = None
    overlap_rate: float | None = None
    backchannels_per_minute: float | None = None
    backchannel_placement: dict[str, int] = field(default_factory=dict)
    speech_rate_wpm: float | None = None
    turn_length_p50_ms: int | None = None
    minutes: float = 0.0


@dataclass
class _Acc:
    pauses: list[int] = field(default_factory=list)
    overlaps: int = 0
    turns: int = 0
    turn_lengths: list[int] = field(default_factory=list)
    words: int = 0
    talk_ms: int = 0
    backchannels: int = 0
    placement: dict[str, int] = field(default_factory=lambda: {"mid_turn": 0, "gap": 0})
    span_ms: int = 0


def _accumulate(acc: dict[str, _Acc], lines: Sequence[TimedLine]) -> None:
    ordered = sorted(lines, key=lambda line: line.start_ms)
    last_prospect: TimedLine | None = None
    if ordered:
        span = max(line.end_ms for line in ordered) - ordered[0].start_ms
        for stage in {ALL, *(line.stage for line in ordered if line.stage)}:
            stage_lines = ordered if stage == ALL else [x for x in ordered if x.stage == stage]
            if stage_lines:
                acc[stage].span_ms += (
                    span
                    if stage == ALL
                    else max(x.end_ms for x in stage_lines) - stage_lines[0].start_ms
                )
    for line in ordered:
        stages = [ALL, *([line.stage] if line.stage else [])]
        if line.speaker == "prospect":
            last_prospect = line
            continue
        if line.speaker != "expert":
            continue
        if line.is_backchannel:
            during = last_prospect is not None and line.start_ms < last_prospect.end_ms
            for stage in stages:
                acc[stage].backchannels += 1
                acc[stage].placement["mid_turn" if during else "gap"] += 1
            continue
        for stage in stages:
            a = acc[stage]
            a.turns += 1
            a.turn_lengths.append(line.end_ms - line.start_ms)
            a.words += line.words
            a.talk_ms += max(0, line.end_ms - line.start_ms)
            if last_prospect is not None:
                pause = line.start_ms - last_prospect.end_ms
                a.pauses.append(pause)
                if pause < 0:
                    a.overlaps += 1
        last_prospect = None  # the next reply waits for new prospect speech


def build_profile(calls: Sequence[Sequence[TimedLine]]) -> dict[str, Any]:
    """The timing profile across calls: one entry per stage, plus ``all``."""
    acc: dict[str, _Acc] = defaultdict(_Acc)
    for lines in calls:
        _accumulate(acc, lines)
    stages: dict[str, dict[str, Any]] = {}
    for stage, a in acc.items():
        minutes = a.span_ms / 60_000
        profile = StageProfile(
            expert_turns=a.turns,
            pause_before_reply_p10_ms=_pct(a.pauses, 0.1),
            pause_before_reply_p50_ms=_pct(a.pauses, 0.5),
            pause_before_reply_p90_ms=_pct(a.pauses, 0.9),
            overlap_rate=round(a.overlaps / len(a.pauses), 3) if a.pauses else None,
            backchannels_per_minute=round(a.backchannels / minutes, 2) if minutes else None,
            backchannel_placement=dict(a.placement),
            speech_rate_wpm=round(a.words / (a.talk_ms / 60_000), 1) if a.talk_ms else None,
            turn_length_p50_ms=_pct(a.turn_lengths, 0.5),
            minutes=round(minutes, 2),
        )
        stages[stage] = asdict(profile)
    return {"version": PROFILE_VERSION, "calls": len(calls), "stages": stages}


def load_profile(path: Path) -> dict[str, Any]:
    """Read a saved profile (for the WP-11.2 backchannel defaults)."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != PROFILE_VERSION or "stages" not in data:
        raise ValueError("not a timing profile of a known version")
    return data


def lines_for_profile(
    rows: Sequence[Any], stage_by_seq: Mapping[int, str] | None = None
) -> list[TimedLine]:
    """Timed lines from stored transcript rows; lines without timings are left out."""
    stages = stage_by_seq or {}
    current: str | None = None
    out = []
    for row in sorted(rows, key=lambda r: r.seq):
        current = stages.get(row.seq, current)  # a stage label holds until the next one
        if row.start_ms is None or row.end_ms is None:
            continue
        out.append(
            TimedLine(
                speaker=row.speaker,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                words=len(row.text.split()),
                is_backchannel=row.speaker == "expert" and is_backchannel_text(row.text),
                stage=current,
            )
        )
    return out


async def profile_for_tenant(session: Any, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Build the profile from one tenant's **call** sources. Talks never count."""
    from sqlalchemy import select

    from aurevia.learning.models import (
        LabelKind,
        LearningLabel,
        LearningSource,
        LearningTranscript,
        ReviewStatus,
        SourceType,
    )

    sources = (
        await session.scalars(
            select(LearningSource).where(
                LearningSource.tenant_id == tenant_id,
                LearningSource.source_type == SourceType.CALL.value,
            )
        )
    ).all()
    calls = []
    for source in sources:
        rows = (
            await session.scalars(
                select(LearningTranscript).where(LearningTranscript.source_id == source.id)
            )
        ).all()
        labels = (
            await session.scalars(
                select(LearningLabel).where(
                    LearningLabel.source_id == source.id,
                    LearningLabel.kind == LabelKind.STAGE.value,
                    LearningLabel.review_status != ReviewStatus.REJECTED.value,
                    LearningLabel.line_seq.is_not(None),
                )
            )
        ).all()
        stage_by_seq = {
            label.line_seq: str(label.value.get("stage"))
            for label in labels
            if isinstance(label.value, dict) and label.value.get("stage")
        }
        calls.append(lines_for_profile(rows, stage_by_seq))
    return build_profile(calls)


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
            profile = await profile_for_tenant(session, tenant_id)
    finally:
        await database.dispose()
    text = json.dumps(profile, indent=2)
    await asyncio.to_thread(Path(args.out).write_text, text, encoding="utf-8")
    print(json.dumps(profile["stages"].get(ALL, {}), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.learning.timing")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--out", required=True, help="where to write the profile (JSON)")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
