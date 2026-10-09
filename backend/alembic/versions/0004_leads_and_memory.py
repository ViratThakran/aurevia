"""Memory: leads, call transcripts (time-limited) and durable lead facts; calls.lead_id.

All new tables are tenant-owned with forced row-level security. The application role may
add and edit leads, add transcript lines (never edit or delete them: they expire), and add or
remove lead memories (correction). Expired transcript lines are removed only by
``purge_expired_transcripts()``, a SECURITY DEFINER function that can delete nothing but rows
past their ``expires_at``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TENANT_TABLES = ("leads", "conversation_messages", "lead_memories")


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_leads_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_leads_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )
    op.create_index(op.f("ix_leads_tenant_id"), "leads", ["tenant_id"])

    op.add_column("calls", sa.Column("lead_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_calls_lead_id_leads"), "calls", "leads", ["lead_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(op.f("ix_calls_lead_id"), "calls", ["lead_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "speaker IN ('prospect', 'agent')", name=op.f("ck_conversation_messages_speaker")
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_conversation_messages_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversation_messages_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
        sa.UniqueConstraint("call_id", "seq", name=op.f("uq_conversation_messages_call_id")),
    )
    op.create_index(
        op.f("ix_conversation_messages_tenant_id"), "conversation_messages", ["tenant_id"]
    )
    op.create_index("ix_conversation_messages_expires_at", "conversation_messages", ["expires_at"])

    op.create_table(
        "lead_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("source_call_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("fact", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor", sa.String(100), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "kind IN ('need', 'objection', 'preference', 'promise', 'business', 'personal')",
            name=op.f("ck_lead_memories_kind"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name=op.f("ck_lead_memories_confidence")
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_lead_memories_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            name=op.f("fk_lead_memories_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_lead_memories_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_memories")),
    )
    op.create_index(op.f("ix_lead_memories_lead_id"), "lead_memories", ["lead_id"])
    op.create_index(op.f("ix_lead_memories_tenant_id"), "lead_memories", ["tenant_id"])

    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    # Retention: a second policy lets the purge function delete expired rows across tenants.
    # It applies only to the schema owner (the function runs as the owner; the application
    # role can never use it), only inside the function (which sets app.purge) and only to
    # expired rows. FOR ALL because a DELETE ... WHERE also needs the rows to be readable.
    op.execute(
        "CREATE POLICY purge_expired ON conversation_messages FOR ALL TO CURRENT_USER "
        "USING (expires_at < now() AND current_setting('app.purge', true) = 'on')"
    )
    op.execute(
        """
        CREATE FUNCTION purge_expired_transcripts() RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE removed integer;
        BEGIN
            PERFORM set_config('app.purge', 'on', true);
            DELETE FROM conversation_messages WHERE expires_at < now();
            GET DIAGNOSTICS removed = ROW_COUNT;
            PERFORM set_config('app.purge', 'off', true);
            RETURN removed;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_expired_transcripts() FROM PUBLIC")

    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON leads TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON conversation_messages TO {role}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON lead_memories TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION purge_expired_transcripts() TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS purge_expired_transcripts()")
    op.drop_table("lead_memories")
    op.drop_table("conversation_messages")
    op.drop_index(op.f("ix_calls_lead_id"), table_name="calls")
    op.drop_constraint(op.f("fk_calls_lead_id_leads"), "calls", type_="foreignkey")
    op.drop_column("calls", "lead_id")
    op.drop_table("leads")
