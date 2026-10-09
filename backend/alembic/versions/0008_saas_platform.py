"""Phase 8a SaaS platform: custom roles, invitations, plans, prices, campaign queue, agent setup.

Three SECURITY DEFINER functions, each reading only what it returns:
- ``resolve_invitation(hash)``: which tenant an invitation token belongs to (before sign-in).
- ``platform_tenants()``: the tenant list for platform administrators.
- ``due_auto_campaigns()``: campaigns the automatic dialer should work on.
They read through policies that apply only to the schema owner while the function runs.
The application may no longer change ``users.is_platform_admin`` (column-level UPDATE grant).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10 10:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TENANT_TABLES = ("custom_roles", "invitations", "tenant_plans", "campaign_leads")
_PLATFORM_LOOKUP_TABLES = ("tenants", "memberships", "calls", "campaigns", "campaign_leads")


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
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    role = _app_role()  # validated identifier: safe to interpolate

    # --- Platform administrators ----------------------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.execute(f"REVOKE UPDATE ON users FROM {role}")
    op.execute(
        "GRANT UPDATE (email, password_hash, full_name, status, last_login_at, updated_at) "
        f"ON users TO {role}"
    )

    # --- Custom roles and invitations ------------------------------------------------------
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String(length=40)), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("custom_roles", "tenant_id", "tenants", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_roles")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_custom_roles_tenant_id")),
    )
    op.create_index(op.f("ix_custom_roles_tenant_id"), "custom_roles", ["tenant_id"])
    op.add_column("memberships", sa.Column("custom_role_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_memberships_custom_role_id_custom_roles"),
        "memberships",
        "custom_roles",
        ["custom_role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("custom_role_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("accepted_at", nullable=True),
        _ts("revoked_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name=op.f("ck_invitations_role")
        ),
        _fk("invitations", "tenant_id", "tenants", "CASCADE"),
        _fk("invitations", "custom_role_id", "custom_roles", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(op.f("ix_invitations_tenant_id"), "invitations", ["tenant_id"])

    # --- Plans and prices --------------------------------------------------------------------
    op.create_table(
        "tenant_plans",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plan_name", sa.String(length=50), nullable=False),
        sa.Column("monthly_call_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_minute_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_cost_limit", sa.Numeric(14, 2), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column("max_concurrent_calls", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        _ts("updated_at"),
        sa.CheckConstraint(
            "max_concurrent_calls BETWEEN 1 AND 100", name=op.f("ck_tenant_plans_concurrency")
        ),
        sa.CheckConstraint(
            "monthly_cost_limit IS NULL OR cost_currency IS NOT NULL",
            name=op.f("ck_tenant_plans_cost_currency"),
        ),
        _fk("tenant_plans", "tenant_id", "tenants", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_tenant_plans_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_plans")),
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("resource", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("per_quantity", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "resource IN ('llm_input_tokens', 'llm_output_tokens', 'stt_seconds', "
            "'tts_characters', 'telephony_seconds')",
            name=op.f("ck_prices_resource"),
        ),
        sa.CheckConstraint("amount >= 0 AND per_quantity > 0", name=op.f("ck_prices_amount")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_prices_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prices")),
    )
    op.create_index(
        "ix_prices_lookup", "prices", ["provider", "resource", "model", "effective_from"]
    )

    # --- Campaign queue -------------------------------------------------------------------
    op.add_column(
        "campaigns",
        sa.Column("retry_delay_minutes", sa.Integer(), server_default="60", nullable=False),
    )
    op.add_column(
        "campaigns",
        sa.Column("auto_dial", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "campaigns",
        sa.Column("max_concurrent_calls", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_campaigns_retry_delay"), "campaigns", "retry_delay_minutes BETWEEN 5 AND 10080"
    )
    op.create_check_constraint(
        op.f("ck_campaigns_concurrency"), "campaigns", "max_concurrent_calls BETWEEN 1 AND 5"
    )
    op.create_table(
        "campaign_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_call_id", sa.Uuid(), nullable=True),
        sa.Column("last_result", sa.String(length=50), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('queued', 'calling', 'done', 'failed', 'skipped')",
            name=op.f("ck_campaign_leads_status"),
        ),
        _fk("campaign_leads", "tenant_id", "tenants", "CASCADE"),
        _fk("campaign_leads", "campaign_id", "campaigns", "CASCADE"),
        _fk("campaign_leads", "lead_id", "leads", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_call_id"],
            ["calls.id"],
            name=op.f("fk_campaign_leads_last_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_leads")),
        sa.UniqueConstraint("campaign_id", "lead_id", name=op.f("uq_campaign_leads_campaign_id")),
    )
    op.create_index(op.f("ix_campaign_leads_tenant_id"), "campaign_leads", ["tenant_id"])
    op.create_index(op.f("ix_campaign_leads_lead_id"), "campaign_leads", ["lead_id"])
    op.create_index(
        "ix_campaign_leads_due", "campaign_leads", ["campaign_id", "status", "next_attempt_at"]
    )

    # --- Agent setup ------------------------------------------------------------------------
    op.add_column(
        "agents",
        sa.Column("personality", sa.String(length=300), server_default="", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column(
            "qualification_questions",
            postgresql.ARRAY(sa.String(length=200)),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "agents", sa.Column("objection_guidance", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "agents", sa.Column("escalation_guidance", sa.Text(), server_default="", nullable=False)
    )

    # --- Tenant isolation -------------------------------------------------------------------
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    # --- Definer lookups --------------------------------------------------------------------
    op.execute(
        "CREATE POLICY definer_lookup ON invitations FOR SELECT TO CURRENT_USER "
        "USING (current_setting('app.definer_lookup', true) = 'invitations')"
    )
    for table in _PLATFORM_LOOKUP_TABLES:
        op.execute(
            f"CREATE POLICY platform_lookup ON {table} FOR SELECT TO CURRENT_USER "
            "USING (current_setting('app.definer_lookup', true) = 'platform')"
        )
    op.execute(
        """
        CREATE FUNCTION resolve_invitation(p_hash text)
        RETURNS TABLE(invitation_id uuid, tenant_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            PERFORM set_config('app.definer_lookup', 'invitations', true);
            RETURN QUERY SELECT i.id, i.tenant_id FROM invitations i WHERE i.token_hash = p_hash;
            PERFORM set_config('app.definer_lookup', '', true);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_tenants()
        RETURNS TABLE(id uuid, name text, slug text, status text, created_at timestamptz,
                      members bigint, calls_this_month bigint, last_call_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            PERFORM set_config('app.definer_lookup', 'platform', true);
            RETURN QUERY
                SELECT t.id, t.name::text, t.slug::text, t.status::text, t.created_at,
                    (SELECT count(*) FROM memberships m
                        WHERE m.tenant_id = t.id AND m.status = 'active'),
                    (SELECT count(*) FROM calls c WHERE c.tenant_id = t.id
                        AND c.created_at >= date_trunc('month', now() AT TIME ZONE 'UTC')
                                            AT TIME ZONE 'UTC'),
                    (SELECT max(c.created_at) FROM calls c WHERE c.tenant_id = t.id)
                FROM tenants t ORDER BY t.created_at;
            PERFORM set_config('app.definer_lookup', '', true);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION due_auto_campaigns()
        RETURNS TABLE(tenant_id uuid, campaign_id uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        BEGIN
            PERFORM set_config('app.definer_lookup', 'platform', true);
            RETURN QUERY
                SELECT c.tenant_id, c.id FROM campaigns c JOIN tenants t ON t.id = c.tenant_id
                WHERE c.status = 'active' AND c.auto_dial AND t.status = 'active'
                  AND EXISTS (
                    SELECT 1 FROM campaign_leads e
                    WHERE e.campaign_id = c.id AND e.status = 'queued'
                      AND e.next_attempt_at <= now()
                  );
            PERFORM set_config('app.definer_lookup', '', true);
        END
        $$
        """
    )
    for function in ("resolve_invitation(text)", "platform_tenants()", "due_auto_campaigns()"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {role}")

    # --- Privileges -------------------------------------------------------------------------
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON custom_roles, campaign_leads TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON invitations, tenant_plans TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON prices TO {role}")  # price versions are insert-only


def downgrade() -> None:
    role = _app_role()
    for function in ("due_auto_campaigns()", "platform_tenants()", "resolve_invitation(text)"):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    for table in _PLATFORM_LOOKUP_TABLES:
        op.execute(f"DROP POLICY IF EXISTS platform_lookup ON {table}")
    for column in (
        "escalation_guidance",
        "objection_guidance",
        "qualification_questions",
        "personality",
    ):
        op.drop_column("agents", column)
    op.drop_table("campaign_leads")
    op.drop_constraint(op.f("ck_campaigns_concurrency"), "campaigns", type_="check")
    op.drop_constraint(op.f("ck_campaigns_retry_delay"), "campaigns", type_="check")
    for column in ("max_concurrent_calls", "auto_dial", "retry_delay_minutes"):
        op.drop_column("campaigns", column)
    op.drop_table("prices")
    op.drop_table("tenant_plans")
    op.drop_table("invitations")
    op.drop_constraint(
        op.f("fk_memberships_custom_role_id_custom_roles"), "memberships", type_="foreignkey"
    )
    op.drop_column("memberships", "custom_role_id")
    op.drop_table("custom_roles")
    op.execute(f"GRANT UPDATE ON users TO {role}")
    op.drop_column("users", "is_platform_admin")
