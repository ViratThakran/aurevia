"""Background memory work: post-call fact extraction and transcript retention."""

from __future__ import annotations

import asyncio
import logging
import uuid

from aurevia.db.session import Database, set_tenant_context
from aurevia.gateway import ModelGateway
from aurevia.memory.extraction import EXTRACTOR_VERSION, extract_facts
from aurevia.memory.service import MemoryService, TranscriptService, purge_expired_transcripts

logger = logging.getLogger(__name__)


async def remember_call(
    database: Database,
    gateway: ModelGateway,
    *,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    lead_id: uuid.UUID,
) -> int:
    """Extract facts from a finished call's transcript and store them for the lead."""
    async with database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        lines = await TranscriptService(session, tenant_id).for_call(call_id)
    if not lines:
        return 0
    facts = await extract_facts(gateway, lines)  # no DB session held while the model runs
    if not facts:
        return 0
    async with database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        stored = await MemoryService(session, tenant_id).add(
            lead_id=lead_id,
            source_call_id=call_id,
            facts=facts,
            extractor=f"{EXTRACTOR_VERSION}/{gateway.model}",
        )
    logger.info(
        "Lead memory updated",
        extra={"fields": {"call_id": str(call_id), "facts": stored}},
    )
    return stored


async def safe_remember_call(
    database: Database, gateway: ModelGateway, **kwargs: uuid.UUID
) -> None:
    try:
        await remember_call(database, gateway, **kwargs)
    except Exception:
        # Memory is best effort: a failure must never affect the call that already ended.
        logger.exception("Post-call memory extraction failed")


async def retention_loop(database: Database, interval_seconds: float) -> None:
    """Purge expired transcript lines now, then every ``interval_seconds``."""
    while True:
        try:
            async with database.sessionmaker() as session:
                removed = await purge_expired_transcripts(session)
            if removed:
                logger.info("Expired transcripts purged", extra={"fields": {"lines": removed}})
        except Exception:
            logger.exception("Transcript purge failed; will retry")
        await asyncio.sleep(interval_seconds)
