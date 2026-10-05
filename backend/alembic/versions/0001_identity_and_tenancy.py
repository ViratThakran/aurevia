"""Identity and tenancy: tenants, users, memberships, refresh tokens, audit events.

Tenant-owned tables get row-level security that is FORCED (it applies to the table owner too).
The application role gets only the privileges Phase 1 needs: no DELETE anywhere, and
``audit_events`` is append-only.

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


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
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'suspended')", name=op.f("ck_tenants_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_users_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name=op.f("ck_memberships_role")
        ),
        sa.CheckConstraint("status IN ('active', 'removed')", name=op.f("ck_memberships_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_memberships_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("tenant_id", "user_id", name=op.f("uq_memberships_tenant_id")),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"])
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_refresh_tokens_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"])
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_events_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"])

    # --- Row-level security -------------------------------------------------------------
    # Unset or empty settings yield NULL, and NULL matches no row: no context, no data.
    op.execute(
        "CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$"
    )
    for table in ("tenants", "memberships", "audit_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # A user also sees their own memberships (and those tenants) while signing in.
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenants
            USING (id = app_current_tenant()
                   OR id IN (SELECT tenant_id FROM memberships WHERE user_id = app_current_user()))
            WITH CHECK (id = app_current_tenant())
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON memberships
            USING (tenant_id = app_current_tenant() OR user_id = app_current_user())
            WITH CHECK (tenant_id = app_current_tenant())
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_events
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
        """
    )

    # --- Application role privileges ----------------------------------------------------
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                RAISE EXCEPTION 'Application role "{role}" does not exist; create it first '
                    '(see backend/README.md)';
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON tenants, users, memberships, refresh_tokens TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON audit_events TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_tenant(), app_current_user() TO {role}")


def downgrade() -> None:
    for table in ("audit_events", "refresh_tokens", "memberships", "users", "tenants"):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant()")
    op.execute("DROP FUNCTION IF EXISTS app_current_user()")
