"""Phase 12 (WP-12.3, built early; API off by default): learning sources, transcripts, labels.

Three tenant-owned tables, each with ``tenant_id``, an index starting with it, and forced
row-level security. Only redacted text is stored. The application role may read and add rows;
labels may also be updated (their review status). Nothing may be deleted by the app.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 18:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TABLES = ("learning_sources", "learning_transcripts", "learning_labels")


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _ts(name: str, *, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.text("now()"),
        nullable=nullable,
    )


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"), ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "learning_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("caller_permission", sa.Boolean(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("redaction_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "source_type IN ('call', 'talk')", name=op.f("ck_learning_sources_source_type")
        ),
        sa.CheckConstraint(
            "outcome IN ('booked', 'not_booked', 'unknown')",
            name=op.f("ck_learning_sources_outcome"),
        ),
        sa.CheckConstraint("caller_permission", name=op.f("ck_learning_sources_caller_permission")),
        _fk("learning_sources", "tenant_id", "tenants", "CASCADE"),
        _fk("learning_sources", "created_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_sources")),
    )
    op.create_index(op.f("ix_learning_sources_tenant_id"), "learning_sources", ["tenant_id"])
    op.create_index(
        "ix_learning_sources_tenant_created", "learning_sources", ["tenant_id", "created_at"]
    )

    op.create_table(
        "learning_transcripts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("word_times_ms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "speaker IN ('expert', 'prospect', 'other')",
            name=op.f("ck_learning_transcripts_speaker"),
        ),
        sa.CheckConstraint(
            "start_ms IS NULL OR (start_ms >= 0 AND (end_ms IS NULL OR end_ms >= start_ms))",
            name=op.f("ck_learning_transcripts_timing"),
        ),
        _fk("learning_transcripts", "tenant_id", "tenants", "CASCADE"),
        _fk("learning_transcripts", "source_id", "learning_sources", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_transcripts")),
        sa.UniqueConstraint("source_id", "seq", name=op.f("uq_learning_transcripts_source_id")),
    )
    op.create_index(
        "ix_learning_transcripts_tenant_source",
        "learning_transcripts",
        ["tenant_id", "source_id", "seq"],
    )

    op.create_table(
        "learning_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("line_seq", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proposed_by", sa.String(length=10), nullable=False),
        sa.Column("review_status", sa.String(length=10), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        _ts("reviewed_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "kind IN ('stage', 'objection', 'outcome', 'qualification', 'next_step', "
            "'talk_ratio', 'question_count')",
            name=op.f("ck_learning_labels_kind"),
        ),
        sa.CheckConstraint(
            "proposed_by IN ('model', 'person')", name=op.f("ck_learning_labels_proposed_by")
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed', 'approved', 'rejected')",
            name=op.f("ck_learning_labels_review_status"),
        ),
        _fk("learning_labels", "tenant_id", "tenants", "CASCADE"),
        _fk("learning_labels", "source_id", "learning_sources", "CASCADE"),
        _fk("learning_labels", "reviewed_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_labels")),
    )
    op.create_index(
        "ix_learning_labels_tenant_source", "learning_labels", ["tenant_id", "source_id"]
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT ON learning_sources, learning_transcripts TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON learning_labels TO {role}")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
