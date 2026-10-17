"""Playbook retrieval for a turn (WP-12.7 part 2, off unless ``AUREVIA_PLAYBOOKS_ENABLED``).

Each turn, at most three **approved** entries of the agent's **active** playbook are offered to
the model as guidance. They sit in the turn part of the prompt, below the honesty rules, and
are framed as suggestions, never as facts or instructions that override the rules. Which
entries were offered is recorded per turn (``playbook_offers``), with how long retrieval took.

Scoring is deliberately simple and fast: an entry for the current stage beats one for any
stage, and words shared between the entry's situation and the prospect's last words break
ties. Entries for another stage are never offered.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.playbooks.models import (
    EntryStatus,
    PlaybookEntry,
    PlaybookStatus,
    PlaybookVersion,
)
from aurevia.sales.state import SalesState

MAX_OFFERED = 3
STAGE_MATCH = 2.0
ANY_STAGE = 1.0
_STOP = frozenset(
    {
        "the",
        "and",
        "but",
        "for",
        "with",
        "are",
        "was",
        "its",
        "this",
        "that",
        "they",
        "them",
        "their",
        "you",
        "your",
        "our",
        "she",
        "his",
        "her",
        "has",
        "have",
        "had",
        "does",
        "did",
        "not",
        "then",
        "than",
        "from",
        "about",
        "just",
        "said",
        "says",
        "say",
    }
)


class _Entry(Protocol):
    @property
    def stage(self) -> str | None: ...
    @property
    def situation(self) -> str: ...
    @property
    def position(self) -> int: ...


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 2 and w not in _STOP}


def rank[E: _Entry](
    entries: Sequence[E], state: SalesState, prospect_said: str, limit: int = MAX_OFFERED
) -> list[E]:
    """The entries to offer, best first. Pure and in memory: no I/O."""
    said = _words(prospect_said)
    scored: list[tuple[float, int, E]] = []
    for entry in entries:
        if entry.stage is not None and entry.stage != state.value:
            continue
        base = STAGE_MATCH if entry.stage == state.value else ANY_STAGE
        situation = _words(entry.situation)
        overlap = len(said & situation) / len(situation) if situation else 0.0
        scored.append((base + overlap, entry.position, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


@dataclass(frozen=True)
class Offer:
    version_id: uuid.UUID
    entries: list[PlaybookEntry]


async def offer_for_turn(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    state: SalesState,
    prospect_said: str,
) -> Offer | None:
    """The entries to offer this turn, or None when the agent has no active playbook."""
    version_id = await session.scalar(
        select(PlaybookVersion.id).where(
            PlaybookVersion.tenant_id == tenant_id,
            PlaybookVersion.agent_id == agent_id,
            PlaybookVersion.status == PlaybookStatus.ACTIVE.value,
        )
    )
    if version_id is None:
        return None
    entries = (
        await session.scalars(
            select(PlaybookEntry).where(
                PlaybookEntry.tenant_id == tenant_id,
                PlaybookEntry.version_id == version_id,
                PlaybookEntry.status == EntryStatus.APPROVED.value,
            )
        )
    ).all()
    return Offer(version_id=version_id, entries=rank(entries, state, prospect_said))
