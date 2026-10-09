# Database Schema

## Core entities
tenants, users, memberships, agents, leads, campaigns, calls, conversation_messages, memories, knowledge_documents, appointments, tool_executions, usage_events, audit_events.

## Tenant isolation
Every tenant-owned resource must be tenant-scoped through an enforceable ownership relationship. Never trust a client-supplied tenant ID alone.

Memory belongs to a lead within a tenant. Security-sensitive and consequential actions produce audit events.

## Implemented (Phase 1, migration `0001`)

| Table | Tenant-scoped | Notes |
| --- | --- | --- |
| `tenants` | RLS on `id` | Visible to its members; during login also via the user's memberships |
| `users` | No (global) | A person can belong to several tenants; email stored lower-cased |
| `memberships` | RLS | Role `owner` / `admin` / `member`; status `active` / `removed` |
| `refresh_tokens` | No (user-bound) | SHA-256 hashes only; rotation within a `family_id` |
| `audit_events` | RLS | Append-only for the application role |

Row-level security is enabled and forced on every tenant-scoped table. Policies compare
`tenant_id` with `app_current_tenant()`, the transaction-local `app.tenant_id` setting. The
application role has no `DELETE` privilege in Phase 1; removal is a status change.

Every later tenant-owned table follows the same pattern: `tenant_id NOT NULL`, an index starting
with `tenant_id`, a forced RLS policy, and grants to the application role in its migration.

## Added in Phase 4 (migration `0004`)

| Table | Notes |
| --- | --- |
| `leads` | Name, phone, email, company, status. `calls.lead_id` links a call to its lead |
| `conversation_messages` | Spoken lines per call; `expires_at` = written + 90 days; app role can insert, never edit or delete |
| `lead_memories` | Extracted facts: kind, fact, confidence, `source_call_id` (provenance), extractor version; app role may delete (correction) |

Expired transcript lines are removed only by `purge_expired_transcripts()` (SECURITY DEFINER,
run hourly by the API), through a policy limited to the schema owner and to expired rows.

## Added in Phase 5 (migration `0005`)

| Table | Notes |
| --- | --- |
| `leads` (columns) | `interest` (unknown / interested / not_interested), `interest_reason`, `qualification` JSONB |
| `lead_notes` | Notes the agent recorded during a call; insert-only |
| `objections` | Category (allow-listed) and detail per call; insert-only |
| `followups` | Due time, channel, note, status |
| `scheduling_settings` | One row per tenant: time zone, work days, hours, slot length, notice, horizon (defaults apply without a row) |
| `appointments` | Booked meetings; unique partial index `uq_appointments_booked_slot` on (`tenant_id`, `starts_at`) where `status = 'booked'` prevents double booking |
| `handoffs` | Requests for a human: reason, urgency, status |
| `tool_executions` | Audit of every tool call: tool, arguments, result, status (ok / rejected / failed), error code, duration; `idempotency_key` unique |

All are tenant-scoped with forced RLS. The app role cannot delete from any of them; audit,
note and objection rows cannot be updated either.

## Added in Phase 6 (migration `0006`)

| Table | Notes |
| --- | --- |
| `phone_numbers` | The tenant's carrier numbers: E.164 (unique across tenants), carrier, purpose (promotional / service), DLT flag, inbound flag, agent |
| `test_numbers` | The tenant's own phones; the only numbers test mode may dial |
| `consents` | Consent per lead and number: kind (express / inquiry), purpose, source, evidence, obtained / expires / revoked; the app may update only `revoked_at` |
| `do_not_call` | Numbers never to call (prospect request, manual, complaint); unique per tenant; insert-only |
| `compliance_decisions` | Every gate decision: checks, facts, policy pack and version, mode, decision, reason code; insert-only |
| `calls` (columns) | `direction`, `to_number`, `from_number`, `dial_status`, `provider_call_id`, `phone_number_id`, `compliance_decision_id` (unique; required for outbound calls by a check constraint) |

Webhooks arrive without a tenant, so two SECURITY DEFINER functions resolve exactly one row:
`resolve_call_room(room)` and `resolve_inbound_number(e164)`. They read through policies that
apply only to the schema owner, and only while the function is running.

## Added in Phase 7 (migration `0007`)

| Table | Notes |
| --- | --- |
| `policy_versions` | Platform-wide (not tenant-owned) immutable pack versions: rules JSONB, source hash, status draft / reviewed / retired, review record. The app can only read it. A trigger forbids rule changes, deletion and un-reviewing |
| `tenant_compliance_settings` | One row per tenant: pinned version (optional) and stricter-only overrides |
| `campaigns` | Purpose, status, dates, calling hours, attempts per lead, daily cap; `calls.campaign_id` and `compliance_decisions.campaign_id` reference it |
| `erasure_requests` | Who asked to be forgotten, how, and what was removed; insert-only |
| `audit_events` (columns) | `seq`, `prev_hash`, `hash`: per-tenant hash chain set by trigger `audit_events_chain` with `audit_event_hash()` |
| `compliance_decisions` (column) | `policy_version_id`: the exact version applied |
| `leads` (column) | `erased_at`; an erased lead stays as an anonymous stub |

`erase_lead(lead)` (SECURITY DEFINER, current tenant only) performs an erasure in one step.
