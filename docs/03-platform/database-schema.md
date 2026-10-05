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
