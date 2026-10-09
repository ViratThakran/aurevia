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
Phase 5 (sales tools) built on top of Phase 4; Phase 3 latency gate still deferred until a
faster model or key (Anthropic planned). Next: Phase 6 (telephony + compliance gate).

Tool rules: the model only requests actions; `tools/framework.py` (`ToolExecutor`) validates,
authorizes, executes, audits and reports every one. New tools subclass `Tool`, declare a
pydantic argument model, return `ToolOutcome.ok/rejected`, and never let a failure read as
success.

Previous milestone notes:
Phase 2 — Browser voice: LiveKit voice worker (Deepgram STT, Cartesia TTS), backend Model
Gateway (Gemini in development, Anthropic selectable by configuration), server-built prompt with honesty rules, opening sales states, calls and
usage events, browser test page. Phase 1 (foundation) is complete. Gate for Phase 2: a full
spoken conversation works end to end in the browser.

## Voice architecture (approved 2026-10-05)
Speech vendor plugins (STT/TTS) live only in `voice-worker/`, which is the voice layer's
provider boundary. The LLM, prompt, sales rules, transcripts and usage stay in the backend
behind the Model Gateway; the worker never calls a model directly.
