"""Playbook versions, entries and per-turn offers (WP-12.7, 12.A). Tenant-owned, forced
row-level security.

A playbook belongs to one agent and is versioned. A version starts as a ``draft``; only a draft
can change. Activating it freezes it (``active``) and retires the agent's previous active
version, so an agent has at most one active version. A retired version never comes back: to
change an active playbook, copy it into a new draft. The database backs this up: a trigger
refuses entry changes outside a draft, and the app role may update only a version's status
columns.

An entry has the fixed format from the plan: situation, what the agent says, tone, goal,
source, and status ``proposed`` or ``approved``. Only approved entries of the active version are
ever offered to the agent (WP-12.7 retrieval), and only a person approves them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from aurevia.db.base import Base, UUIDPrimaryKey, one_of
from aurevia.sales.state import SalesState


class PlaybookStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class EntryStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"


class PlaybookVersion(UUIDPrimaryKey, Base):
    __tablename__ = "playbook_versions"
    __table_args__ = (
        CheckConstraint(one_of("status", PlaybookStatus), name="status"),
        UniqueConstraint("tenant_id", "agent_id", "version"),
        # At most one active version per agent.
        Index(
            "uq_playbook_versions_one_active",
            "tenant_id",
            "agent_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default=PlaybookStatus.DRAFT)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    activated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlaybookEntry(UUIDPrimaryKey, Base):
    __tablename__ = "playbook_entries"
    __table_args__ = (
        CheckConstraint(one_of("status", EntryStatus), name="status"),
        CheckConstraint(f"stage IS NULL OR {one_of('stage', SalesState)}", name="stage"),
        Index("ix_playbook_entries_tenant_version", "tenant_id", "version_id", "position"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playbook_versions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    # The sales stage the entry is for; None means any stage.
    stage: Mapped[str | None] = mapped_column(String(20))
    situation: Mapped[str] = mapped_column(String(300))
    says: Mapped[str] = mapped_column(String(500))  # what the agent says
    tone: Mapped[str] = mapped_column(String(100))
    goal: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default=EntryStatus.PROPOSED)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PlaybookOffer(UUIDPrimaryKey, Base):
    """Which approved entries were offered to the model on a turn (WP-12.7 part 2), and how
    long retrieval took. Insert-only; WP-12.8 evaluation reads it."""

    __tablename__ = "playbook_offers"
    __table_args__ = (Index("ix_playbook_offers_tenant_call", "tenant_id", "call_id", "turn"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playbook_versions.id", ondelete="CASCADE")
    )
    turn: Mapped[int] = mapped_column(Integer)
    entry_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))
    retrieval_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
