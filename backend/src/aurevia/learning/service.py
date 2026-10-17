"""Import and read learning sources (WP-12.3) and label them (WP-12.4). Everything is redacted
before it is stored."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import AureviaError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.learning.labels import LabelIn
from aurevia.learning.models import (
    LabelSource,
    LearningLabel,
    LearningSource,
    LearningTranscript,
    ReviewStatus,
)
from aurevia.learning.redaction import Detector, redact_lines
from aurevia.learning.schemas import LabelAccuracyOut, SourceImportIn


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

    async def _source(self, source_id: uuid.UUID) -> LearningSource:
        source = await self._session.scalar(
            select(LearningSource).where(
                LearningSource.id == source_id, LearningSource.tenant_id == self._tenant_id
            )
        )
        if source is None:
            raise NotFoundError("Learning source not found")
        return source

    async def labels(self, source_id: uuid.UUID) -> list[LearningLabel]:
        await self._source(source_id)
        rows = await self._session.scalars(
            select(LearningLabel)
            .where(
                LearningLabel.source_id == source_id,
                LearningLabel.tenant_id == self._tenant_id,
            )
            .order_by(LearningLabel.line_seq.nulls_last(), LearningLabel.created_at)
        )
        return list(rows)

    async def add_label(
        self, source_id: uuid.UUID, body: LabelIn, *, actor_user_id: uuid.UUID | None
    ) -> LearningLabel:
        """A person's label. It is their own check, so it is stored as approved by them."""
        source = await self._source(source_id)
        if body.line_seq is not None and body.line_seq >= source.line_count:
            raise AureviaError(
                "That line is not in the transcript", status_code=422, code="invalid_line"
            )
        label = LearningLabel(
            tenant_id=self._tenant_id,
            source_id=source.id,
            line_seq=body.line_seq,
            kind=body.kind.value,
            value=body.value,
            proposed_by=LabelSource.PERSON.value,
            review_status=ReviewStatus.APPROVED.value,
            reviewed_by_user_id=actor_user_id,
            reviewed_at=datetime.now(UTC),
        )
        self._session.add(label)
        await self._session.flush()
        self._audit_label("learning.label_added", label, actor_user_id)
        await self._session.commit()
        return label

    async def review_label(
        self, label_id: uuid.UUID, status: ReviewStatus, *, actor_user_id: uuid.UUID | None
    ) -> LearningLabel:
        label = await self._session.scalar(
            select(LearningLabel)
            .where(LearningLabel.id == label_id, LearningLabel.tenant_id == self._tenant_id)
            .with_for_update()
        )
        if label is None:
            raise NotFoundError("Label not found")
        label.review_status = status.value
        label.reviewed_by_user_id = actor_user_id
        label.reviewed_at = datetime.now(UTC)
        self._audit_label("learning.label_reviewed", label, actor_user_id)
        await self._session.commit()
        return label

    async def label_accuracy(self) -> LabelAccuracyOut:
        rows = await self._session.execute(
            select(LearningLabel.review_status, func.count())
            .where(
                LearningLabel.tenant_id == self._tenant_id,
                LearningLabel.proposed_by == LabelSource.MODEL.value,
            )
            .group_by(LearningLabel.review_status)
        )
        counts = {status: int(n) for status, n in rows.all()}
        approved = counts.get(ReviewStatus.APPROVED.value, 0)
        rejected = counts.get(ReviewStatus.REJECTED.value, 0)
        checked = approved + rejected
        return LabelAccuracyOut(
            model_labels=sum(counts.values()),
            waiting=counts.get(ReviewStatus.PROPOSED.value, 0),
            approved=approved,
            rejected=rejected,
            accuracy=round(approved / checked, 3) if checked else None,
        )

    def _audit_label(
        self, action: str, label: LearningLabel, actor_user_id: uuid.UUID | None
    ) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action=action,
            actor_user_id=actor_user_id,
            target_type="learning_label",
            target_id=label.id,
            details={
                "source_id": str(label.source_id),
                "kind": label.kind,
                "status": label.review_status,
            },
        )
