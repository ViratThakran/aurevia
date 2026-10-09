"""Phase 7 compliance hardening: policy versions, campaigns, audit chain, DPDP erasure.

- ``policy_versions``: immutable pack versions (platform reference data; the app only reads).
  A trigger forbids changing rules and allows only draft -> reviewed -> retired. Seeded with
  the built-in India draft.
- ``tenant_compliance_settings``: a tenant's pinned version and stricter-only overrides.
- ``campaigns`` (minimal): limits the gate enforces; calls and decisions reference them.
- ``audit_events``: per-tenant hash chain (seq, prev_hash, hash), computed by a trigger on
  insert; existing events are chained in order.
- ``erasure_requests`` + ``erase_lead()``: erase a person's data on request (SECURITY DEFINER,
  current tenant only), keeping the do-not-call entry and the compliance records.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 18:00:00
"""

import hashlib
import json
import re
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from aurevia.compliance.policy import INDIA_DRAFT_FILE, load_builtin

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TENANT_TABLES = ("tenant_compliance_settings", "campaigns", "erasure_requests")


def _app_role() -> str:
    role = op.get_context().config.attributes["app_role"]  # type: ignore[union-attr]
    if not isinstance(role, str) or not _ROLE_PATTERN.fullmatch(role):
        raise ValueError("invalid application role name")
    return role


def _now() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    # --- Policy versions -----------------------------------------------------------------
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pack", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("review_reference", sa.String(length=200), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        _now(),
        sa.CheckConstraint(
            "status IN ('draft', 'reviewed', 'retired')", name=op.f("ck_policy_versions_status")
        ),
        sa.CheckConstraint(
            "status <> 'reviewed' OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL "
            "AND review_reference IS NOT NULL)",
            name=op.f("ck_policy_versions_review_recorded"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_versions")),
        sa.UniqueConstraint("version", name=op.f("uq_policy_versions_version")),
    )
    op.create_index(op.f("ix_policy_versions_pack"), "policy_versions", ["pack"])
    op.execute(
        """
        CREATE FUNCTION policy_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'policy versions are never deleted (retire them instead)';
            END IF;
            IF NEW.pack <> OLD.pack OR NEW.version <> OLD.version OR NEW.rules <> OLD.rules
               OR NEW.source_sha256 <> OLD.source_sha256 OR NEW.created_at <> OLD.created_at
               OR NEW.notes IS DISTINCT FROM OLD.notes THEN
                RAISE EXCEPTION 'policy version % cannot change; publish a new version',
                    OLD.version;
            END IF;
            IF OLD.status = 'retired' AND NEW.status <> 'retired' THEN
                RAISE EXCEPTION 'a retired policy version stays retired';
            END IF;
            IF OLD.status = 'reviewed' AND NEW.status = 'draft' THEN
                RAISE EXCEPTION 'a reviewed policy version cannot return to draft';
            END IF;
            IF OLD.status IN ('reviewed', 'retired')
               AND (NEW.reviewed_at, NEW.reviewed_by, NEW.review_reference)
                   IS DISTINCT FROM (OLD.reviewed_at, OLD.reviewed_by, OLD.review_reference) THEN
                RAISE EXCEPTION 'a recorded review cannot be changed';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER policy_versions_guard BEFORE UPDATE OR DELETE ON policy_versions "
        "FOR EACH ROW EXECUTE FUNCTION policy_versions_guard()"
    )
    builtin = load_builtin(INDIA_DRAFT_FILE)
    india_id = uuid.uuid4()
    op.get_bind().execute(
        sa.text(
            "INSERT INTO policy_versions (id, pack, version, rules, source_sha256, notes, status) "
            "VALUES (:id, :pack, :version, CAST(:rules AS jsonb), :sha, :notes, 'draft')"
        ),
        {
            "id": india_id,
            "pack": builtin.pack,
            "version": builtin.version,
            "rules": json.dumps(builtin.rules.model_dump(mode="json")),
            "sha": hashlib.sha256(builtin.raw.encode("utf-8")).hexdigest(),
            "notes": builtin.notes,
        },
    )

    # --- Tenant settings ----------------------------------------------------------------
    op.create_table(
        "tenant_compliance_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=True),
        sa.Column("overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            name=op.f("fk_tenant_compliance_settings_policy_version_id_policy_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_compliance_settings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_tenant_compliance_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenant_compliance_settings")),
    )

    # --- Campaigns ----------------------------------------------------------------------
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("window_start", sa.Time(), nullable=True),
        sa.Column("window_end", sa.Time(), nullable=True),
        sa.Column("max_attempts_per_lead", sa.Integer(), nullable=False),
        sa.Column("daily_call_cap", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _now(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'ended')", name=op.f("ck_campaigns_status")
        ),
        sa.CheckConstraint(
            "purpose IN ('promotional', 'service')", name=op.f("ck_campaigns_purpose")
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on", name=op.f("ck_campaigns_dates")
        ),
        sa.CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start < window_end",
            name=op.f("ck_campaigns_window"),
        ),
        sa.CheckConstraint(
            "max_attempts_per_lead BETWEEN 1 AND 10", name=op.f("ck_campaigns_attempts")
        ),
        sa.CheckConstraint(
            "daily_call_cap IS NULL OR daily_call_cap >= 1", name=op.f("ck_campaigns_daily_cap")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_campaigns_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_campaigns_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_index(op.f("ix_campaigns_tenant_id"), "campaigns", ["tenant_id"])
    op.add_column("calls", sa.Column("campaign_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_calls_campaign_id_campaigns"),
        "calls",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_calls_campaign_id"), "calls", ["campaign_id"])

    # --- Decisions reference their policy version and campaign ---------------------------
    op.add_column("compliance_decisions", sa.Column("policy_version_id", sa.Uuid(), nullable=True))
    op.add_column("compliance_decisions", sa.Column("campaign_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_compliance_decisions_policy_version_id_policy_versions"),
        "compliance_decisions",
        "policy_versions",
        ["policy_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_compliance_decisions_campaign_id_campaigns"),
        "compliance_decisions",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- Erasure ------------------------------------------------------------------------
    op.add_column("leads", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f("ck_do_not_call_reason"), "do_not_call", type_="check")
    op.create_check_constraint(
        op.f("ck_do_not_call_reason"),
        "do_not_call",
        "reason IN ('prospect_request', 'manual', 'complaint', 'erasure_request')",
    )
    op.create_table(
        "erasure_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("received_via", sa.String(length=200), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _now(),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_erasure_requests_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_erasure_requests_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_erasure_requests_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erasure_requests")),
    )
    op.create_index(op.f("ix_erasure_requests_tenant_id"), "erasure_requests", ["tenant_id"])
    op.create_index(op.f("ix_erasure_requests_lead_id"), "erasure_requests", ["lead_id"])
    op.execute(
        """
        CREATE FUNCTION erase_lead(p_lead uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
            t uuid := app_current_tenant();
            n_lines int; n_memories int; n_notes int; n_objections int; n_followups int;
            n_handoffs int; n_tools int; n_appointments int;
        BEGIN
            IF t IS NULL THEN
                RAISE EXCEPTION 'erase_lead needs a tenant in scope';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM leads WHERE id = p_lead AND tenant_id = t) THEN
                RAISE EXCEPTION 'lead not found';
            END IF;
            DELETE FROM conversation_messages m USING calls c
                WHERE m.call_id = c.id AND c.lead_id = p_lead AND c.tenant_id = t
                  AND m.tenant_id = t;
            GET DIAGNOSTICS n_lines = ROW_COUNT;
            DELETE FROM lead_memories WHERE lead_id = p_lead AND tenant_id = t;
            GET DIAGNOSTICS n_memories = ROW_COUNT;
            DELETE FROM lead_notes WHERE lead_id = p_lead AND tenant_id = t;
            GET DIAGNOSTICS n_notes = ROW_COUNT;
            DELETE FROM objections WHERE lead_id = p_lead AND tenant_id = t;
            GET DIAGNOSTICS n_objections = ROW_COUNT;
            DELETE FROM followups WHERE lead_id = p_lead AND tenant_id = t;
            GET DIAGNOSTICS n_followups = ROW_COUNT;
            UPDATE handoffs SET reason = '[erased]' WHERE lead_id = p_lead AND tenant_id = t;
            GET DIAGNOSTICS n_handoffs = ROW_COUNT;
            UPDATE tool_executions te
                SET arguments = '{}'::jsonb, result = '{"redacted": true}'::jsonb
                FROM calls c
                WHERE te.call_id = c.id AND c.lead_id = p_lead AND c.tenant_id = t
                  AND te.tenant_id = t;
            GET DIAGNOSTICS n_tools = ROW_COUNT;
            UPDATE appointments SET status = 'cancelled'
                WHERE lead_id = p_lead AND tenant_id = t AND status = 'booked'
                  AND starts_at > now();
            GET DIAGNOSTICS n_appointments = ROW_COUNT;
            UPDATE leads
                SET name = 'Erased person', phone = NULL, email = NULL, company = NULL,
                    interest_reason = NULL, qualification = '{}'::jsonb, status = 'archived',
                    erased_at = now()
                WHERE id = p_lead AND tenant_id = t;
            RETURN jsonb_build_object(
                'transcript_lines', n_lines, 'memories', n_memories, 'notes', n_notes,
                'objections', n_objections, 'followups', n_followups,
                'handoffs_redacted', n_handoffs, 'tool_records_redacted', n_tools,
                'future_appointments_cancelled', n_appointments
            );
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION erase_lead(uuid) FROM PUBLIC")

    # --- Audit hash chain ---------------------------------------------------------------
    op.add_column("audit_events", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_events", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_events", sa.Column("hash", sa.String(length=64), nullable=True))
    op.execute(
        """
        CREATE FUNCTION audit_event_hash(e audit_events) RETURNS text
        LANGUAGE sql STABLE AS $$
            SELECT encode(sha256(convert_to(concat_ws('|',
                e.seq, e.prev_hash, e.id, e.tenant_id, coalesce(e.actor_user_id::text, ''),
                e.action, coalesce(e.target_type, ''), coalesce(e.target_id::text, ''),
                coalesce(e.request_id, ''), e.details::text,
                to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')
            ), 'UTF8')), 'hex')
        $$
        """
    )
    # Chain the events that already exist, per tenant, in the order they were written. The
    # owner reads past row-level security only for this backfill.
    op.execute("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        DECLARE r audit_events; prev text; last_tenant uuid; n bigint;
        BEGIN
            FOR r IN SELECT * FROM audit_events ORDER BY tenant_id, created_at, id LOOP
                IF last_tenant IS DISTINCT FROM r.tenant_id THEN
                    prev := repeat('0', 64); n := 0; last_tenant := r.tenant_id;
                END IF;
                n := n + 1;
                r.seq := n;
                r.prev_hash := prev;
                r.hash := audit_event_hash(r);
                UPDATE audit_events SET seq = r.seq, prev_hash = r.prev_hash, hash = r.hash
                    WHERE id = r.id;
                prev := r.hash;
            END LOOP;
        END
        $$
        """
    )
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    for column in ("seq", "prev_hash", "hash"):
        op.alter_column("audit_events", column, nullable=False)
    op.create_unique_constraint(
        op.f("uq_audit_events_tenant_id"), "audit_events", ["tenant_id", "seq"]
    )
    # Runs as the inserting role, inside its tenant scope: it sees exactly that tenant's chain.
    op.execute(
        """
        CREATE FUNCTION audit_events_chain() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE last audit_events;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit:' || NEW.tenant_id::text));
            SELECT * INTO last FROM audit_events
                WHERE tenant_id = NEW.tenant_id ORDER BY seq DESC LIMIT 1;
            NEW.seq := coalesce(last.seq, 0) + 1;
            NEW.prev_hash := coalesce(last.hash, repeat('0', 64));
            NEW.hash := audit_event_hash(NEW);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_chain BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_chain()"
    )

    # --- Tenant isolation and privileges ------------------------------------------------
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = app_current_tenant()) "
            "WITH CHECK (tenant_id = app_current_tenant())"
        )
    role = _app_role()  # validated identifier: safe to interpolate
    op.execute(f"GRANT SELECT ON policy_versions TO {role}")  # reference data: read only
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenant_compliance_settings, campaigns TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON erasure_requests TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION erase_lead(uuid) TO {role}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_chain ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_chain()")
    op.drop_constraint(op.f("uq_audit_events_tenant_id"), "audit_events", type_="unique")
    op.execute("DROP FUNCTION IF EXISTS audit_event_hash(audit_events)")
    for column in ("hash", "prev_hash", "seq"):
        op.drop_column("audit_events", column)
    op.execute("DROP FUNCTION IF EXISTS erase_lead(uuid)")
    op.drop_table("erasure_requests")
    op.drop_constraint(op.f("ck_do_not_call_reason"), "do_not_call", type_="check")
    op.create_check_constraint(
        op.f("ck_do_not_call_reason"),
        "do_not_call",
        "reason IN ('prospect_request', 'manual', 'complaint')",
    )
    op.drop_column("leads", "erased_at")
    op.drop_constraint(
        op.f("fk_compliance_decisions_campaign_id_campaigns"),
        "compliance_decisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_compliance_decisions_policy_version_id_policy_versions"),
        "compliance_decisions",
        type_="foreignkey",
    )
    op.drop_column("compliance_decisions", "campaign_id")
    op.drop_column("compliance_decisions", "policy_version_id")
    op.drop_index(op.f("ix_calls_campaign_id"), table_name="calls")
    op.drop_constraint(op.f("fk_calls_campaign_id_campaigns"), "calls", type_="foreignkey")
    op.drop_column("calls", "campaign_id")
    op.drop_table("campaigns")
    op.drop_table("tenant_compliance_settings")
    op.execute("DROP TRIGGER IF EXISTS policy_versions_guard ON policy_versions")
    op.execute("DROP FUNCTION IF EXISTS policy_versions_guard()")
    op.drop_table("policy_versions")
