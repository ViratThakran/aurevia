"""Phase 6 telephony + compliance gate: numbers, consent, do-not-call, decisions, phone calls.

Two SECURITY DEFINER lookups serve the media-server webhooks, which arrive without a tenant:
``resolve_call_room`` (room -> call, tenant) and ``resolve_inbound_number`` (dialed number ->
tenant, line, agent). Each can only read the one row it is asked about, through a policy that
applies only to the schema owner and only while the function has set ``app.definer_lookup``.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09 14:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TENANT_TABLES = (
    "phone_numbers",
    "test_numbers",
    "consents",
    "do_not_call",
    "compliance_decisions",
)


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="CASCADE",
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def _created() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("e164", sa.String(length=20), nullable=False),
        sa.Column("carrier", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("dlt_registered", sa.Boolean(), nullable=False),
        sa.Column("inbound_enabled", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        _created(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('promotional', 'service')", name=op.f("ck_phone_numbers_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_phone_numbers_agent_id_agents"),
            ondelete="SET NULL",
        ),
        _tenant_fk("phone_numbers"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_numbers")),
        sa.UniqueConstraint("e164", name=op.f("uq_phone_numbers_e164")),
    )
    op.create_index(op.f("ix_phone_numbers_tenant_id"), "phone_numbers", ["tenant_id"])

    op.create_table(
        "test_numbers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("e164", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=True),
        _created(),
        _user_fk("test_numbers", "added_by_user_id"),
        _tenant_fk("test_numbers"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_numbers")),
        sa.UniqueConstraint("tenant_id", "e164", name=op.f("uq_test_numbers_tenant_id")),
    )
    op.create_index(op.f("ix_test_numbers_tenant_id"), "test_numbers", ["tenant_id"])

    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("evidence", sa.String(length=1000), nullable=True),
        sa.Column("obtained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by_user_id", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint("kind IN ('express', 'inquiry')", name=op.f("ck_consents_kind")),
        sa.CheckConstraint(
            "purpose IN ('promotional', 'service')", name=op.f("ck_consents_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_consents_lead_id_leads"), ondelete="CASCADE"
        ),
        _user_fk("consents", "recorded_by_user_id"),
        _tenant_fk("consents"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_tenant_id"), "consents", ["tenant_id"])
    op.create_index(op.f("ix_consents_lead_id"), "consents", ["lead_id"])
    op.create_index("ix_consents_tenant_phone", "consents", ["tenant_id", "phone"])

    op.create_table(
        "do_not_call",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("source_call_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint(
            "reason IN ('prospect_request', 'manual', 'complaint')",
            name=op.f("ck_do_not_call_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            name=op.f("fk_do_not_call_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        _user_fk("do_not_call", "created_by_user_id"),
        _tenant_fk("do_not_call"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_do_not_call")),
        sa.UniqueConstraint("tenant_id", "phone", name=op.f("uq_do_not_call_tenant_id")),
    )
    op.create_index(op.f("ix_do_not_call_tenant_id"), "do_not_call", ["tenant_id"])

    op.create_table(
        "compliance_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("to_number", sa.String(length=20), nullable=True),
        sa.Column("from_number", sa.String(length=20), nullable=True),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("policy_pack", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason_code", sa.String(length=50), nullable=False),
        _created(),
        sa.CheckConstraint(
            "decision IN ('allow', 'block')", name=op.f("ck_compliance_decisions_decision")
        ),
        sa.CheckConstraint("mode IN ('test', 'live')", name=op.f("ck_compliance_decisions_mode")),
        sa.CheckConstraint(
            "purpose IN ('promotional', 'service')",
            name=op.f("ck_compliance_decisions_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_compliance_decisions_lead_id_leads"),
            ondelete="SET NULL",
        ),
        _user_fk("compliance_decisions", "requested_by_user_id"),
        _tenant_fk("compliance_decisions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_decisions")),
    )
    op.create_index(
        op.f("ix_compliance_decisions_tenant_id"), "compliance_decisions", ["tenant_id"]
    )
    op.create_index(op.f("ix_compliance_decisions_lead_id"), "compliance_decisions", ["lead_id"])
    op.create_index(
        "ix_compliance_decisions_tenant_created",
        "compliance_decisions",
        ["tenant_id", "created_at"],
    )

    # --- Phone columns on calls ----------------------------------------------------------
    op.add_column("calls", sa.Column("direction", sa.String(length=10), nullable=True))
    op.add_column("calls", sa.Column("to_number", sa.String(length=20), nullable=True))
    op.add_column("calls", sa.Column("from_number", sa.String(length=20), nullable=True))
    op.add_column("calls", sa.Column("dial_status", sa.String(length=20), nullable=True))
    op.add_column("calls", sa.Column("provider_call_id", sa.String(length=100), nullable=True))
    op.add_column("calls", sa.Column("compliance_decision_id", sa.Uuid(), nullable=True))
    op.add_column("calls", sa.Column("phone_number_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_calls_compliance_decision_id"), "calls", ["compliance_decision_id"]
    )
    op.create_foreign_key(
        op.f("fk_calls_compliance_decision_id_compliance_decisions"),
        "calls",
        "compliance_decisions",
        ["compliance_decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_calls_phone_number_id_phone_numbers"),
        "calls",
        "phone_numbers",
        ["phone_number_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_calls_tenant_to_number_created", "calls", ["tenant_id", "to_number", "created_at"]
    )
    op.create_check_constraint(
        op.f("ck_calls_direction"),
        "calls",
        "direction IS NULL OR direction IN ('outbound', 'inbound')",
    )
    op.create_check_constraint(
        op.f("ck_calls_dial_status"),
        "calls",
        "dial_status IS NULL OR dial_status IN "
        "('queued', 'answered', 'no_answer', 'busy', 'failed')",
    )
    op.create_check_constraint(
        op.f("ck_calls_outbound_has_decision"),
        "calls",
        "direction IS DISTINCT FROM 'outbound' OR compliance_decision_id IS NOT NULL",
    )

    # --- Tenant isolation ----------------------------------------------------------------
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    # --- Webhook lookups (see module docstring) ------------------------------------------
    op.execute(
        "CREATE POLICY definer_lookup ON calls FOR SELECT TO CURRENT_USER "
        "USING (current_setting('app.definer_lookup', true) = 'calls')"
    )
    op.execute(
        "CREATE POLICY definer_lookup ON phone_numbers FOR SELECT TO CURRENT_USER "
        "USING (current_setting('app.definer_lookup', true) = 'phone_numbers')"
    )
    op.execute(
        """
        CREATE FUNCTION resolve_call_room(p_room text)
        RETURNS TABLE(call_id uuid, tenant_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            PERFORM set_config('app.definer_lookup', 'calls', true);
            RETURN QUERY SELECT c.id, c.tenant_id FROM calls c WHERE c.room = p_room;
            PERFORM set_config('app.definer_lookup', '', true);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION resolve_inbound_number(p_e164 text)
        RETURNS TABLE(tenant_id uuid, phone_number_id uuid, agent_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            PERFORM set_config('app.definer_lookup', 'phone_numbers', true);
            RETURN QUERY
                SELECT n.tenant_id, n.id, n.agent_id FROM phone_numbers n
                WHERE n.e164 = p_e164 AND n.active AND n.inbound_enabled;
            PERFORM set_config('app.definer_lookup', '', true);
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION resolve_call_room(text) FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION resolve_inbound_number(text) FROM PUBLIC")

    # --- Application-role privileges -----------------------------------------------------
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON phone_numbers TO {role}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON test_numbers TO {role}")
    # Consent: recorded once; only revocation may change it afterwards.
    op.execute(f"GRANT SELECT, INSERT ON consents TO {role}")
    op.execute(f"GRANT UPDATE (revoked_at) ON consents TO {role}")
    # The do-not-call list and the decision record are append-only for the application.
    op.execute(f"GRANT SELECT, INSERT ON do_not_call, compliance_decisions TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION resolve_call_room(text) TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION resolve_inbound_number(text) TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS resolve_inbound_number(text)")
    op.execute("DROP FUNCTION IF EXISTS resolve_call_room(text)")
    op.execute("DROP POLICY IF EXISTS definer_lookup ON calls")
    op.drop_constraint(op.f("ck_calls_outbound_has_decision"), "calls", type_="check")
    op.drop_constraint(op.f("ck_calls_dial_status"), "calls", type_="check")
    op.drop_constraint(op.f("ck_calls_direction"), "calls", type_="check")
    op.drop_index("ix_calls_tenant_to_number_created", table_name="calls")
    op.drop_constraint(op.f("fk_calls_phone_number_id_phone_numbers"), "calls", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_calls_compliance_decision_id_compliance_decisions"), "calls", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_calls_compliance_decision_id"), "calls", type_="unique")
    for column in (
        "phone_number_id",
        "compliance_decision_id",
        "provider_call_id",
        "dial_status",
        "from_number",
        "to_number",
        "direction",
    ):
        op.drop_column("calls", column)
    op.drop_table("compliance_decisions")
    op.drop_table("do_not_call")
    op.drop_table("consents")
    op.drop_table("test_numbers")
    op.drop_table("phone_numbers")
