"""Phase 12 (WP-12.6, built early; off by default): technique candidates and their review.

One tenant-owned table with ``tenant_id``, an index starting with it, and forced row-level
security. The app role may read, add and update the reviewable columns; it cannot delete.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17 23:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _fk(column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_learning_techniques_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_table(
        "learning_techniques",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("situation", sa.String(length=300), nullable=False),
        sa.Column("says", sa.String(length=500), nullable=False),
        sa.Column("tone", sa.String(length=100), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=False),
        sa.Column("conditions", sa.String(length=300), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("source_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("booked_count", sa.Integer(), nullable=False),
        sa.Column("unbooked_count", sa.Integer(), nullable=False),
        sa.Column("proposed_by", sa.String(length=10), nullable=False),
        sa.Column("policy_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("playbook_entry_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected')",
            name=op.f("ck_learning_techniques_status"),
        ),
        sa.CheckConstraint(
            "proposed_by IN ('model', 'person')", name=op.f("ck_learning_techniques_proposed_by")
        ),
        _fk("tenant_id", "tenants", "CASCADE"),
        _fk("reviewed_by_user_id", "users", "SET NULL"),
        _fk("playbook_entry_id", "playbook_entries", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_techniques")),
    )
    op.create_index(
        "ix_learning_techniques_tenant_status",
        "learning_techniques",
        ["tenant_id", "status", "created_at"],
    )
    op.execute("ALTER TABLE learning_techniques ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_techniques FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON learning_techniques "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant())"
    )
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT ON learning_techniques TO {role}")
    op.execute(
        "GRANT UPDATE (stage, situation, says, tone, goal, conditions, policy_flags, status, "
        f"reviewed_by_user_id, reviewed_at, playbook_entry_id) ON learning_techniques TO {role}"
    )


def downgrade() -> None:
    op.drop_table("learning_techniques")
