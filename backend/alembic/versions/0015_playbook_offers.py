"""Phase 12 (WP-12.7 part 2, built early; off by default): which playbook entries were offered.

One tenant-owned, insert-only table with ``tenant_id``, an index starting with it, and forced
row-level security.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-17 22:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def upgrade() -> None:
    op.create_table(
        "playbook_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("entry_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("retrieval_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_playbook_offers_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_playbook_offers_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["playbook_versions.id"],
            name=op.f("fk_playbook_offers_version_id_playbook_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_offers")),
    )
    op.create_index(
        "ix_playbook_offers_tenant_call", "playbook_offers", ["tenant_id", "call_id", "turn"]
    )
    op.execute("ALTER TABLE playbook_offers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE playbook_offers FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON playbook_offers "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant())"
    )
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT ON playbook_offers TO {role}")


def downgrade() -> None:
    op.drop_table("playbook_offers")
