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
Status (2026-10-09): built. Native function calling through the Model Gateway (Gemini and
Anthropic adapters; provider-neutral `ToolSpec` / `ToolCall` / `ToolResult`). The backend runs
the tool loop (at most 3 tool rounds per turn; the last round offers no tools). Every call goes
through `ToolExecutor`: schema validation, lead requirement, business rules, a savepoint, an
audit row in `tool_executions`, and idempotency (the same request in a call is reported, never
repeated). Tools: set_stage, qualify_lead, mark_interested, mark_not_interested, log_objection,
add_note, schedule_followup, get_available_slots, book_meeting, cancel_meeting,
flag_for_handoff. Built-in calendar (per-tenant hours, default Mon-Fri 10:00-18:00
Asia/Kolkata, 30-minute slots, 2 h notice, 14-day horizon); a unique index makes double booking
impossible. Record-only tools that succeed alongside a spoken reply end the turn without an
extra model round. Live transfer (`transfer_to_human`) moves to Phase 6 with telephony; Phase 5
flags handoffs. Gate met in integration tests (a rejected booking reaches the model as
`ok: false`, and the prompt forbids claiming success without it) and verified live with
Gemini: slots looked up, the prospect's choice booked, confirmed only after `ok: true`.

## Phase 6 — Telephony + Compliance Gate
Telephony abstraction and one adapter, SIP into the voice worker, inbound/outbound lifecycle,
webhooks, recordings/transcripts, reconnect/failure handling, and the pre-call compliance gate
with decision records.
Gate: zero gate bypasses; test calls to own numbers only.
Status (2026-10-09): built and verified locally; the real phone call waits for hosting.
Decisions (2026-10-09): build now and host later (a carrier cannot reach a laptop's SIP
server); Exotel is the first carrier; no audio recording in Phase 6 (transcripts only).
Built:
- Telephony through LiveKit SIP (one adapter; the carrier is SIP-trunk configuration).
- The pre-call gate (`compliance/`): pure rule engine plus the India draft pack. It covers
  consent, the tenant do-not-call list, DND (adapter; no registry yet, so unknown means
  blocked), the 09:00-21:00 window, attempt limits, lead status and a DLT 140/160 caller id.
  Every request writes a decision record (checks, facts, policy version).
- Test mode (default) dials only registered own numbers; live mode is blocked until counsel
  reviews the pack.
- Outbound lifecycle: queued, then answered / busy / no_answer / failed; failures end the call
  and free the agent. Inbound routing by dialed number, with the caller matched to a lead.
- Signed LiveKit webhooks (room ended: open calls are closed; phone line joined: inbound
  call). The agent greets only after the phone is answered.
- `request_do_not_call` tool; consent and do-not-call APIs.
Gate met in tests: the architecture tests prove `place_call` is reachable only with a gate
`Approval`, and 49 rule tests cover the compliance-test matrix. Also verified against the real
LiveKit SIP service with an unroutable trunk. See docs/02-voice/telephony.md for the first real
call.

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
