"""Phase 12 (WP-12.7 and 12.A, built early; off by default): playbook versions and entries.

Two tenant-owned tables, each with ``tenant_id``, an index starting with it, and forced
row-level security. At most one active version per agent (a partial unique index). Versions
are immutable once they leave draft: the app role may update only a version's status columns,
and a trigger refuses any entry insert or update unless its version is a draft. Nothing may
be deleted by the app.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-17 21:00:00
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TABLES = ("playbook_versions", "playbook_entries")
_STAGES = (
    "'new', 'opening', 'discovery', 'qualification', 'pitch', 'objection', 'next_step', "
    "'follow_up', 'meeting_booked', 'human_handoff', 'completed'"
)


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
        "playbook_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_by_user_id", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("activated_at", nullable=True),
        _ts("retired_at", nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name=op.f("ck_playbook_versions_status")
        ),
        _fk("playbook_versions", "tenant_id", "tenants", "CASCADE"),
        _fk("playbook_versions", "agent_id", "agents", "CASCADE"),
        _fk("playbook_versions", "created_by_user_id", "users", "SET NULL"),
        _fk("playbook_versions", "activated_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_versions")),
        sa.UniqueConstraint(
            "tenant_id", "agent_id", "version", name=op.f("uq_playbook_versions_tenant_id")
        ),
    )
    op.create_index(op.f("ix_playbook_versions_tenant_id"), "playbook_versions", ["tenant_id"])
    op.create_index(
        "uq_playbook_versions_one_active",
        "playbook_versions",
        ["tenant_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "playbook_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("situation", sa.String(length=300), nullable=False),
        sa.Column("says", sa.String(length=500), nullable=False),
        sa.Column("tone", sa.String(length=100), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        _ts("approved_at", nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved')", name=op.f("ck_playbook_entries_status")
        ),
        sa.CheckConstraint(
            f"stage IS NULL OR stage IN ({_STAGES})", name=op.f("ck_playbook_entries_stage")
        ),
        _fk("playbook_entries", "tenant_id", "tenants", "CASCADE"),
        _fk("playbook_entries", "version_id", "playbook_versions", "CASCADE"),
        _fk("playbook_entries", "approved_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_entries")),
    )
    op.create_index(
        "ix_playbook_entries_tenant_version",
        "playbook_entries",
        ["tenant_id", "version_id", "position"],
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )

    # Entries change only while their version is a draft (backs up the service check).
    op.execute(
        """
        CREATE FUNCTION playbook_entries_draft_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM playbook_versions
                WHERE id = NEW.version_id AND status = 'draft'
            ) THEN
                RAISE EXCEPTION 'playbook version is not a draft' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.version_id <> OLD.version_id THEN
                RAISE EXCEPTION 'an entry cannot move between versions' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER playbook_entries_draft_only BEFORE INSERT OR UPDATE ON playbook_entries "
        "FOR EACH ROW EXECUTE FUNCTION playbook_entries_draft_only()"
    )

    # A version's status only moves forward: draft -> active -> retired (or draft -> retired).
    op.execute(
        """
        CREATE FUNCTION playbook_versions_forward_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'draft' AND NEW.status IN ('active', 'retired'))
                OR (OLD.status = 'active' AND NEW.status = 'retired')
            ) THEN
                RAISE EXCEPTION 'playbook status cannot go from % to %', OLD.status, NEW.status
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER playbook_versions_forward_only BEFORE UPDATE ON playbook_versions "
        "FOR EACH ROW EXECUTE FUNCTION playbook_versions_forward_only()"
    )

    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT, INSERT ON playbook_versions, playbook_entries TO {role}")
    op.execute(
        "GRANT UPDATE (status, activated_by_user_id, activated_at, retired_at) "
        f"ON playbook_versions TO {role}"
    )
    op.execute(
        "GRANT UPDATE (stage, situation, says, tone, goal, source, status, "
        f"approved_by_user_id, approved_at) ON playbook_entries TO {role}"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS playbook_entries_draft_only ON playbook_entries")
    op.execute("DROP FUNCTION IF EXISTS playbook_entries_draft_only()")
    op.execute("DROP TRIGGER IF EXISTS playbook_versions_forward_only ON playbook_versions")
    op.execute("DROP FUNCTION IF EXISTS playbook_versions_forward_only()")
    for table in reversed(_TABLES):
        op.drop_table(table)
