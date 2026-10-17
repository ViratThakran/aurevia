"""Import and read learning sources (WP-12.3). Everything is redacted before it is stored."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.learning.models import LearningSource, LearningTranscript
from aurevia.learning.redaction import Detector, redact_lines
from aurevia.learning.schemas import SourceImportIn


class LearningService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def import_source(
        self, body: SourceImportIn, *, detector: Detector, actor_user_id: uuid.UUID | None
    ) -> LearningSource:
        """Redact the title and every line together (one placeholder per value across the
        transcript), then store only the redacted result. The request's original text is
        never written anywhere. A redaction failure stores nothing."""
        lines = body.lines or []
        redacted, counts = await redact_lines(
            [body.title, *(line.text for line in lines)], detector
        )
        source = LearningSource(
            tenant_id=self._tenant_id,
            source_type=body.source_type.value,
            title=redacted[0][:200],
            language=body.language,
            industry=body.industry,
            outcome=body.outcome.value,
            caller_permission=True,
            line_count=len(lines),
            redaction_counts=counts,
            created_by_user_id=actor_user_id,
        )
        self._session.add(source)
        await self._session.flush()
        for seq, (line, text) in enumerate(zip(lines, redacted[1:], strict=True)):
            self._session.add(
                LearningTranscript(
                    tenant_id=self._tenant_id,
                    source_id=source.id,
                    seq=seq,
                    speaker=line.speaker.value,
                    text=text,
                    start_ms=line.start_ms,
                    end_ms=line.end_ms,
                    word_times_ms=[list(pair) for pair in line.word_times_ms]
                    if line.word_times_ms
                    else None,
                )
            )
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action="learning.source_imported",
            actor_user_id=actor_user_id,
            target_type="learning_source",
            target_id=source.id,
            details={
                "source_type": source.source_type,
                "lines": len(lines),
                "redacted": counts,  # counts by kind only, never values
            },
        )
        await self._session.commit()
        return source

    async def list_sources(self, limit: int = 100) -> list[LearningSource]:
        rows = await self._session.scalars(
            select(LearningSource)
            .where(LearningSource.tenant_id == self._tenant_id)
            .order_by(LearningSource.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def get_source(
        self, source_id: uuid.UUID
    ) -> tuple[LearningSource, list[LearningTranscript]]:
        source = await self._session.scalar(
            select(LearningSource).where(
                LearningSource.id == source_id, LearningSource.tenant_id == self._tenant_id
            )
        )
        if source is None:
            raise NotFoundError("Learning source not found")
        lines = await self._session.scalars(
            select(LearningTranscript)
            .where(
                LearningTranscript.source_id == source_id,
                LearningTranscript.tenant_id == self._tenant_id,
            )
            .order_by(LearningTranscript.seq)
        )
        return source, list(lines)
