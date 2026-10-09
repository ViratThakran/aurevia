# Implementation Plan

Each phase ends at an exit gate; the next phase starts only when it passes. The amendments
approved on 2026-10-05 are reflected below (see `master-brief.md`).

## Phase 1 — Foundation
Repository, services, PostgreSQL/Alembic migrations, auth (access tokens + rotating refresh
tokens), tenant/user/membership model, thin RBAC (owner/admin/member), row-level security,
provider interfaces with fakes, health checks, tests, CI.
Gate: tenant-isolation and auth test suites pass in CI against a real Postgres.

## Phase 2 — Browser Voice
Voice worker, browser test page, Model Gateway, one STT/TTS/LLM adapter each, basic sales
states, transcript, usage events.
Gate: a full spoken conversation works end to end in the browser.

## Phase 3 — Voice Quality
Per-step latency tracing, interruption/barge-in and cancellation, silence handling, backchannel
experiments, simulated-prospect evaluation and regression tests.
Gate: latency and barge-in targets met on the regression set (median < 1.0 s, p95 < 1.8 s,
prospect stops speaking -> agent's first audio).
Status (2026-10-09): built and measured with the simulated-prospect suite. Barge-in is
detected. Pipeline overhead is ~0.8 s (end-of-turn wait ~0.58 s, TTS ~0.2 s, backend hop
<0.1 s; end-of-turn ceiling cut from 3.0 s to 1.5 s). The rest is the model: Gemini on the
development key gives ~1.1-1.9 s to first token with occasional stalls (handled by fallback +
circuit breaker). Decision (2026-10-09): the latency gate is deferred until a faster model or
key is available (planned: Anthropic); development continues with Phase 4.

## Phase 4 — Memory
Transcript persistence, post-call fact extraction, durable lead facts, retrieval, confidence,
correction/deletion, tenant-safe memory.
Gate: a second call recalls the first, tenant-safe.
Status (2026-10-09): built. Leads; calls linked to a lead; transcripts kept 90 days
(`transcript_retention_days`) then purged by `purge_expired_transcripts()`; post-call fact
extraction (validated JSON, provenance + confidence) into `lead_memories`; confident facts are
added to later calls' prompts as notes, never instructions; facts can be deleted (correction).
Gate met in integration tests and verified live with Gemini.

## Phase 5 — Sales Tools
Tool framework, qualification, lead updates, objections, follow-ups, calendar slots and
booking, human handoff.
Gate: no failed tool is ever reported as success in simulations.

## Phase 6 — Telephony + Compliance Gate
Telephony abstraction and one adapter, SIP into the voice worker, inbound/outbound lifecycle,
webhooks, recordings/transcripts, reconnect/failure handling, and the pre-call compliance gate
with decision records.
Gate: zero gate bypasses; test calls to own numbers only.

## Phase 7 — Compliance Hardening
Versioned policies, India policy pack (DLT, 140/160 series, calling window, DND scrubbing, DPDP,
IRDAI), campaign restrictions, full audit trail, counsel review.
Gate: compliance test suite passes; counsel review done.

## Phase 8 — SaaS Platform
Dashboard, agent setup, campaigns, analytics, usage/cost, billing boundaries, custom roles and
team management, multi-tenant administration.
Gate: a tenant goes from signup to first call without help.

## Phase 9 — Pilot
Acceptance tests, controlled pilots with 2–3 friendly customers, voice-quality and
sales-outcome evaluation, cost review, incident process.
Gate: pilot acceptance tests pass; go/no-go decision.
