"""Learning tables (WP-12.3): sources, their redacted transcripts, and labels. All tenant-owned
and protected by forced row-level security. Built early; the API is off by default
(``AUREVIA_LEARNING_ENABLED``).

Only redacted text is stored (WP-12.2). Original audio and text are never stored here: the
import redacts in memory and keeps the result. Word timings are kept as numbers only, no
words, so a timing profile (WP-12.5) can be built without any text. A ``talk`` source (an
interview or a talk about cold calling) has no timings: talks never feed the timing profile.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, UUIDPrimaryKey, one_of
from aurevia.playbooks import models as _playbook_models  # noqa: F401  (techniques -> entries)


class SourceType(StrEnum):
    CALL = "call"  # a real call: techniques and the timing profile
    TALK = "talk"  # a talk or interview about calling: techniques only, never timing


class SourceOutcome(StrEnum):
    BOOKED = "booked"
    NOT_BOOKED = "not_booked"
    UNKNOWN = "unknown"


class LineSpeaker(StrEnum):
    EXPERT = "expert"  # the caller being learned from (or the talk's speaker)
    PROSPECT = "prospect"
    OTHER = "other"


class LabelKind(StrEnum):
    STAGE = "stage"
    OBJECTION = "objection"
    OUTCOME = "outcome"
    QUALIFICATION = "qualification"
    NEXT_STEP = "next_step"
    TALK_RATIO = "talk_ratio"
    QUESTION_COUNT = "question_count"


class LabelSource(StrEnum):
    MODEL = "model"
    PERSON = "person"


class ReviewStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class LearningSource(UUIDPrimaryKey, Base):
    __tablename__ = "learning_sources"
    __table_args__ = (
        CheckConstraint(one_of("source_type", SourceType), name="source_type"),
        CheckConstraint(one_of("outcome", SourceOutcome), name="outcome"),
        # Nothing is imported without the caller's permission on file (WP-12.0 inventory).
        CheckConstraint("caller_permission", name="caller_permission"),
        Index("ix_learning_sources_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))  # redacted, like the text
    language: Mapped[str] = mapped_column(String(10))
    industry: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20), default=SourceOutcome.UNKNOWN)
    caller_permission: Mapped[bool] = mapped_column(Boolean)
    line_count: Mapped[int] = mapped_column(Integer)
    # Counts of what redaction replaced, by kind; never values.
    redaction_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LearningTranscript(UUIDPrimaryKey, Base):
    """One redacted line of a source."""

    __tablename__ = "learning_transcripts"
    __table_args__ = (
        CheckConstraint(one_of("speaker", LineSpeaker), name="speaker"),
        CheckConstraint(
            "start_ms IS NULL OR (start_ms >= 0 AND (end_ms IS NULL OR end_ms >= start_ms))",
            name="timing",
        ),
        UniqueConstraint("source_id", "seq"),
        Index("ix_learning_transcripts_tenant_source", "tenant_id", "source_id", "seq"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learning_sources.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)  # redacted
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    # Word timings as [start_ms, end_ms] pairs, numbers only (WP-12.5). Calls only.
    word_times_ms: Mapped[list[list[int]] | None] = mapped_column(JSONB)


class LearningLabel(UUIDPrimaryKey, Base):
    """A label on a source (WP-12.4): proposed by the model or a person, then reviewed."""

    __tablename__ = "learning_labels"
    __table_args__ = (
        CheckConstraint(one_of("kind", LabelKind), name="kind"),
        CheckConstraint(one_of("proposed_by", LabelSource), name="proposed_by"),
        CheckConstraint(one_of("review_status", ReviewStatus), name="review_status"),
        Index("ix_learning_labels_tenant_source", "tenant_id", "source_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learning_sources.id", ondelete="CASCADE")
    )
    line_seq: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    proposed_by: Mapped[str] = mapped_column(String(10))
    review_status: Mapped[str] = mapped_column(String(10), default=ReviewStatus.PROPOSED)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TechniqueStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class LearningTechnique(UUIDPrimaryKey, Base):
    """A technique candidate (WP-12.6): what an expert does in a situation, from the sources.

    It enters the review queue as ``proposed`` after the automatic policy check; a person
    approves, edits or rejects it. Only an approved technique can be copied into a draft
    playbook, where it is again ``proposed`` until someone with ``learning.publish`` approves it.
    """

    __tablename__ = "learning_techniques"
    __table_args__ = (
        CheckConstraint(one_of("status", TechniqueStatus), name="status"),
        CheckConstraint(one_of("proposed_by", LabelSource), name="proposed_by"),
        Index("ix_learning_techniques_tenant_status", "tenant_id", "status", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    stage: Mapped[str | None] = mapped_column(String(20))
    situation: Mapped[str] = mapped_column(String(300))
    says: Mapped[str] = mapped_column(String(500))
    tone: Mapped[str] = mapped_column(String(100))
    goal: Mapped[str] = mapped_column(String(200))
    conditions: Mapped[str] = mapped_column(String(300), default="")
    # A short redacted excerpt from a source that shows the technique.
    excerpt: Mapped[str] = mapped_column(Text, default="")
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()), default=list)
    # How often it was seen in booked and in unbooked calls.
    booked_count: Mapped[int] = mapped_column(Integer, default=0)
    unbooked_count: Mapped[int] = mapped_column(Integer, default=0)
    proposed_by: Mapped[str] = mapped_column(String(10))
    policy_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(10), default=TechniqueStatus.PROPOSED)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    playbook_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("playbook_entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
