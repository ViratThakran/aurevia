"""Voice: agents, calls and usage events.

All three are tenant-owned: forced row-level security, ``tenant_id`` indexed. The application
role may not delete anything, and ``usage_events`` is append-only.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_SALES_STATES = (
    "'new', 'opening', 'discovery', 'qualification', 'pitch', 'objection', 'next_step', "
    "'follow_up', 'meeting_booked', 'human_handoff', 'completed'"
)


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("company_description", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("greeting", sa.String(500), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("voice", sa.String(100), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_agents_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index(op.f("ix_agents_tenant_id"), "agents", ["tenant_id"])
    op.create_index(
        "uq_agents_default_per_tenant",
        "agents",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sales_state", sa.String(30), nullable=False),
        sa.Column("room", sa.String(100), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(100), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("channel IN ('browser', 'phone')", name=op.f("ck_calls_channel")),
        sa.CheckConstraint(
            "status IN ('created', 'in_progress', 'completed', 'failed')",
            name=op.f("ck_calls_status"),
        ),
        sa.CheckConstraint(f"sales_state IN ({_SALES_STATES})", name=op.f("ck_calls_sales_state")),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_calls_agent_id_agents"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_calls_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_calls_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calls")),
        sa.UniqueConstraint("room", name=op.f("uq_calls_room")),
    )
    op.create_index(op.f("ix_calls_tenant_id"), "calls", ["tenant_id"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("served_model", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("audio_seconds", sa.Float(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("interrupted", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("provider_request_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('llm', 'stt', 'tts', 'telephony')", name=op.f("ck_usage_events_kind")
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_usage_events_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_usage_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_call_id"), "usage_events", ["call_id"])
    op.create_index(op.f("ix_usage_events_tenant_id"), "usage_events", ["tenant_id"])

    for table in ("agents", "calls", "usage_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON agents, calls TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON usage_events TO {role}")


def downgrade() -> None:
    for table in ("usage_events", "calls", "agents"):
        op.drop_table(table)
