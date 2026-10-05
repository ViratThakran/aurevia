# AGENTS.md — Aurevia Engineering Rules

Source of truth: `00-foundation/master-brief.md`, including its approved amendments.

1. Read the documentation tree before changing code.
2. Do not redesign architecture without approval: stop, explain, propose, wait.
3. The LLM is not the application controller.
4. LLMs cannot directly access PostgreSQL.
5. External side effects use validated tools/services.
6. Provider SDKs stay behind adapters (`backend/src/aurevia/providers/`; enforced by
   `backend/tests/test_architecture.py`).
7. Tenant isolation is enforced server-side: services filter by the principal's tenant, and
   Postgres row-level security backs them up. Every new tenant-owned table gets a `tenant_id`,
   an index starting with it, and a forced RLS policy in its migration.
8. Browser clients never receive provider secrets.
9. Compliance gates are deterministic server-side controls. No real call without the gate.
10. Add tests and migrations with meaningful changes. Never edit an applied migration.
11. Do not implement future phases prematurely.

## Voice rules
- Never claim to be human.
- Answer honestly if directly asked whether AI.
- Never invent product information.
- Handle interruption appropriately.
- Never claim a failed tool action succeeded.

## Current milestone
Phase 1 — Foundation: PostgreSQL + Alembic, tenants/users/memberships, thin RBAC
(owner/admin/member), authentication with refresh-token rotation, row-level security, provider
interfaces with fakes, CI. Next: Phase 2 — browser voice prototype (no telephony).
