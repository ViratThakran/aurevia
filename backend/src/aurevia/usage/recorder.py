"""Writing usage events.

LLM usage is recorded after a streamed reply ends, which may be after the HTTP request that
started it was cancelled (barge-in). The write therefore uses its own session and is shielded
from cancellation, so an interrupted reply is still recorded.
"""

from __future__ import annotations

import logging
import uuid

import anyio

from aurevia.db.session import Database, set_tenant_context
from aurevia.gateway import GenerationRecord
from aurevia.logging import request_id_var
from aurevia.usage.models import UsageEvent, UsageKind

logger = logging.getLogger(__name__)


async def record_llm_usage(
    database: Database, *, tenant_id: uuid.UUID, call_id: uuid.UUID, record: GenerationRecord
) -> None:
    event = UsageEvent(
        tenant_id=tenant_id,
        call_id=call_id,
        kind=UsageKind.LLM,
        provider=record.provider,
        model=record.requested_model,
        served_model=record.served_model,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        first_token_ms=record.first_token_ms,
        interrupted=record.interrupted,
        request_id=request_id_var.get(),
        provider_request_id=record.provider_request_id,
    )
    with anyio.CancelScope(shield=True):
        try:
            async with database.sessionmaker() as session:
                await set_tenant_context(session, tenant_id)
                session.add(event)
                await session.commit()
        except Exception:
            # Losing a usage row must never break a live call; it is logged for follow-up.
            logger.exception(
                "Failed to record LLM usage", extra={"fields": {"call_id": str(call_id)}}
            )
