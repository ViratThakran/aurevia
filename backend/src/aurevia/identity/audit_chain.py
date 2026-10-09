"""Reading and verifying the tamper-evident audit log (Phase 7).

The database computes each event's hash on insert (trigger ``audit_events_chain``, migration
0007) from the event's content and the previous event's hash in the same tenant. Verification
recomputes every hash with the same SQL function and checks the links, so any edited, deleted
or inserted-out-of-order event is found. The head hash can be stored outside Aurevia
periodically: a full rewrite of the chain would then show too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.identity.models import AuditEvent

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class ChainReport:
    events: int
    ok: bool
    first_broken_seq: int | None
    head_hash: str | None


async def verify_chain(session: AsyncSession, tenant_id: uuid.UUID) -> ChainReport:
    rows = (
        await session.execute(
            text(
                "SELECT seq, prev_hash, hash, audit_event_hash(e) AS expected "
                "FROM audit_events e WHERE tenant_id = :tenant ORDER BY seq"
            ),
            {"tenant": tenant_id},
        )
    ).all()
    previous, expected_seq = GENESIS_HASH, 1
    for seq, prev_hash, hash_, expected in rows:
        if seq != expected_seq or prev_hash != previous or hash_ != expected:
            return ChainReport(len(rows), False, seq, rows[-1][2])
        previous, expected_seq = hash_, expected_seq + 1
    return ChainReport(len(rows), True, None, rows[-1][2] if rows else None)


async def list_events(
    session: AsyncSession, tenant_id: uuid.UUID, *, after_seq: int, limit: int
) -> list[AuditEvent]:
    rows = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.seq > after_seq)
        .order_by(AuditEvent.seq)
        .limit(limit)
    )
    return list(rows)
