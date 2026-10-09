"""Voice quality: per-turn latency metrics (timings only, no transcript text).

Tenant-owned: forced row-level security; append-only for the application role.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
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
        "turn_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("transcription_delay_ms", sa.Integer(), nullable=True),
        sa.Column("end_of_turn_delay_ms", sa.Integer(), nullable=True),
        sa.Column("e2e_latency_ms", sa.Integer(), nullable=True),
        sa.Column("llm_ttft_ms", sa.Integer(), nullable=True),
        sa.Column("tts_ttfb_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('prospect', 'agent')", name=op.f("ck_turn_metrics_role")),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_turn_metrics_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_turn_metrics_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turn_metrics")),
        sa.UniqueConstraint("call_id", "seq", name=op.f("uq_turn_metrics_call_id")),
    )
    op.create_index(op.f("ix_turn_metrics_tenant_id"), "turn_metrics", ["tenant_id"])

    op.execute("ALTER TABLE turn_metrics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE turn_metrics FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON turn_metrics "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant())"
    )
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT ON turn_metrics TO {role}")


def downgrade() -> None:
    op.drop_table("turn_metrics")
