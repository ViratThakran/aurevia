# Aurevia AI Sales Agent — Master Product & Engineering Brief

This is the source of truth for what Aurevia is and how it is built. The shorter documents in
this folder tree elaborate parts of it; where they disagree, this brief wins and they must be
updated.

## Amendments approved on 2026-10-05

These replace the original text where they conflict:

1. **Compliance gate ships with telephony.** The pre-call compliance gate is built inside
   Phase 6 (Telephony). No call is placed to a real number until the gate passes its test
   suite. Phase 7 becomes *Compliance hardening* (versioned policies, campaign restrictions,
   full audit trail, counsel review).
2. **Thin RBAC in Phase 1.** Three fixed roles (owner, admin, member) checked server-side.
   Custom roles and team-management UI move to Phase 8.
3. **India policy pack.** The compliance engine stays generic; Indian rules (DLT registration,
   140/160 number series, 9am–9pm calling window, real-time DND scrubbing, DPDP Act data
   handling, IRDAI telemarketing rules) live in a configurable policy pack for the first
   customers. Exact requirements are confirmed with counsel before production.
4. **Documentation.** This brief lives in `docs/`; `AGENTS.md`, the implementation plan and the
   outline docs are kept consistent with it.

## Amendment approved on 2026-10-10

5. **Campaign dialing, Phase 8.** Campaigns get both an assisted queue ("call next") and an
   opt-in automatic dialer, ahead of §27's "no large-scale campaigns now". The guard rails:
   - The dialer is off unless enabled on the server **and** on the campaign.
   - At most 5 concurrent calls per campaign.
   - Every call goes through plan limits and the compliance gate.
   - Until counsel review and hosting exist, only a tenant's own test numbers can be reached.

Open question: whether insurance brokers remain the first market or Aurevia launches
horizontally. It affects the Phase 9 pilot list and the priority of the India policy pack.

---

## 1. What we are building

Aurevia AI Sales Agent is a multi-tenant SaaS platform that gives companies an AI-powered sales
workforce capable of real-time voice conversations with leads and customers. It is not a simple
chatbot or a basic "LLM connected to a phone call"; it is a complete AI sales-agent platform.

The system should eventually be able to:

- Call leads automatically and have natural, real-time conversations.
- Introduce the company and its services; understand what the prospect needs.
- Ask discovery questions, qualify leads and identify buying intent.
- Present relevant services/projects and explain value propositions.
- Handle objections and answer questions using approved business knowledge.
- Remember important information from previous conversations.
- Update the lead/CRM; schedule, cancel or reschedule meetings and follow-ups where authorized.
- Escalate difficult or high-value conversations to humans, and transfer calls where supported.
- Record structured outcomes and follow compliance rules.
- Operate for multiple companies/tenants.
- Track usage, costs, calls, outcomes and performance.
- Eventually run campaigns involving large numbers of leads.

The long-term product is an AI Sales Workforce Platform, not merely a voice bot.

## 2. Core philosophy

**The LLM is an intelligence component, not the application controller.**

The model can understand language, reason, generate responses and propose actions. It must not
directly write to PostgreSQL, modify a lead, book a calendar event, change a lead's status, send
arbitrary external requests, bypass compliance, transfer a call without authorization, or claim
that an action succeeded when it failed.

```
User/Lead → Voice Runtime → Conversation / AI → LLM → Proposed Action
→ Sales Control Engine → Tool Validation → Authorization → Business Rules
→ Action Service → Database / CRM / Calendar / Telephony
```

## 3. High-level architecture

Main components:

1. AI Model Gateway
2. Sales Control Engine
3. Tool & Action Framework
4. Conversation Memory
5. Voice Runtime
6. Voice Provider Abstraction
7. Platform API
8. Multi-Tenancy
9. Compliance Engine
10. Observability
11. Cost & Usage Engine
12. SaaS Dashboard
13. Testing/Evaluation infrastructure

See `architecture.md` for the diagram and boundaries.

## 4. AI Model Gateway

Aurevia must not be tightly coupled to one AI provider. The gateway (`ModelGateway` with
`generate`, `stream`, `health`) handles provider abstraction, model selection, request
configuration, streaming, timeouts, retries, explicit fallback, provider health, token usage,
cost tracking, prompt and model version tracking, request correlation, and per-tenant model
configuration where authorized.

Fallback must be explicit: never silently switch models and change behaviour, quality or cost.
Provider API keys remain server-side secrets.

## 5. Sales Control Engine

The LLM is good at conversation; the Sales Control Engine controls the sales workflow.

```
NEW → OPENING → DISCOVERY → QUALIFICATION → PITCH → OBJECTION → NEXT_STEP → FOLLOW_UP
→ MEETING_BOOKED | HUMAN_HANDOFF → COMPLETED
```

It tracks current sales state, lead intent, qualification fields, objections, conversation
goals, allowed actions, business rules, guardrails, tool permissions, human handoff and
termination reason. When the LLM says "the prospect wants a meeting next Tuesday at 3 PM", the
engine decides whether the prospect is qualified, booking is allowed, the calendar has the slot,
the time is valid, the tenant permits booking, the lead may be contacted, and the request
satisfies business rules. Only then can the booking happen.

## 6. Tool & Action Framework

```
LLM → Tool Request → Schema Validation → Authorization → Business Validation
→ Action Service → Database / CRM / Calendar → Tool Result → Conversation
```

Potential tools — lead: `get_lead`, `update_lead`, `add_note`, `change_status`; sales:
`mark_interested`, `mark_not_interested`, `log_objection`, `qualify_lead`; follow-up:
`schedule_followup`, `cancel_followup`; calendar: `get_available_slots`, `book_meeting`,
`cancel_meeting`; human escalation: `flag_for_handoff`, `transfer_to_human`.

Every tool needs an input schema, output schema, authorization rules, tenant scope,
idempotency, validation, audit requirements and failure behaviour.

**A tool failure must never be represented to the prospect as a successful action.**

## 7. Conversation Memory

- **In-call memory:** current transcript, intent, objections, qualification, sales state and
  context.
- **Durable memory:** lead facts, business information, preferences, previous objections,
  promises, previous discussions, follow-up context.

Only useful information becomes durable memory. Memory eventually includes provenance,
confidence, tenant isolation, retrieval, correction and deletion/retention policies. Durable
cross-call memory is not part of the foundation phase.

## 8. Voice Runtime

```
Microphone / RTP → VAD → Turn Detection → Streaming STT → Conversation Engine
→ Model Gateway → Streaming TTS → Audio
```

Handles audio lifecycle, voice activity detection, turn detection, partial transcripts,
streaming recognition, streaming model responses, streaming TTS, interruptions, barge-in,
cancellation, silence, reconnection and cleanup.

## 9. Barge-in / interruption

If the prospect interrupts: detect speech → stop TTS playback → cancel/invalidate the old model
generation → capture the new utterance → process the new turn. The system must not talk over
the prospect. This is tested heavily.

## 10. Voice provider abstraction

Business logic must not depend directly on one STT, TTS or telephony provider. One provider per
capability initially, behind adapters; no speculative adapters.

## 11. Telephony

Outbound and inbound calls, call lifecycle, provider webhooks, connection and termination,
reconnection/failure, recordings where permitted, transcripts, call metadata and provider IDs —
all behind an abstraction. Per amendment 1, no real call is placed without the compliance gate.

## 12. Lead management

A lead may contain name, phone, email, company, source, status, qualification data, interest,
objections, notes, previous interactions, next follow-up, assigned agent, campaign and call
history. Aurevia eventually imports, creates, updates, qualifies and calls leads, records
outcomes, schedules follow-ups and meetings, and hands leads off to humans.

## 13. CRM integration

CRM integrations go through the Tool & Action Framework: LLM → CRM Tool → Authorization →
Validation → CRM Service → CRM API. The LLM never calls a CRM API directly.

## 14. Calendar integration

The AI must verify availability (`get_available_slots`) before `book_meeting`, then confirm.

## 15. Human handoff

Escalate for high-value leads, complex technical questions, explicit requests for a human,
missing approved information, sensitive situations, business rules requiring human approval, or
negotiation beyond the agent's authority — preserving context so the human does not start from
zero.

## 16. Multi-tenancy

Tenant isolation is mandatory. A user from Tenant A must never retrieve, modify, search or infer
Tenant B's leads, data, memory, files, vectors or cached data through APIs or workers. Tenant
identity comes from authenticated server context, never simply from a client-provided
`tenant_id`.

## 17. Authentication and authorization

User, Tenant, Membership, Role, Permissions. Authorization happens server-side. Phase 1 roles
(amendment 2): owner, admin, member.

## 18. Compliance engine

Compliance is a server-side deterministic system. Before a call:

```
CALL REQUEST → Consent → DND / Policy → Calling Window → Tenant Policy
→ Campaign Restrictions → Provider Requirements → ALLOW / BLOCK
```

The LLM cannot override it. Every decision records tenant, lead, campaign, requested action,
policy version, checks, decision, reason and timestamp. Exact regulatory requirements must be
verified against current authoritative sources before production.

## 19. Observability

Visibility into requests, calls, sessions, model/STT/TTS latency, provider and tool failures,
database errors, compliance blocks, token usage, AI costs, call duration, outcomes, handoffs,
bookings, follow-ups and errors — with correlation IDs (`tenant_id`, `call_id`, `session_id`,
`request_id`, `lead_id`, `tool_call_id`, `provider_request_id`).

## 20. Cost and usage tracking

Track STT, TTS, LLM tokens and model, telephony minutes, storage and other provider costs;
calculate cost per call, minute, lead, campaign and tenant for billing and profitability.

## 21–22. SaaS dashboard and AI agent configuration

Dashboard areas: dashboard, agents, leads, campaigns, calls, meetings, follow-ups, knowledge,
analytics, usage, settings, team, integrations. Each tenant configures its agent (name,
personality, voice, company, product knowledge, sales objective, qualification, objection,
tool, escalation, calling and compliance rules). Configuration is validated by the server, never
injected blindly.

## 23–24. Campaigns and analytics

Campaigns (lead lists, schedules, agent assignment, qualification, follow-up sequences, retries,
compliance rules, analytics, conversion tracking) come later. Analytics cover activity,
conversation, sales, AI quality (latency, interruption handling, hallucination rate, tool
failure rate, escalation accuracy) and economics (cost per call, qualified lead, meeting,
conversion).

## 25. Testing strategy

Unit (state machine, qualification, authorization, compliance, tool validation, costs);
integration (PostgreSQL, model providers, STT, TTS, calendar, CRM, telephony); voice (latency,
interruptions, silence, partial speech, long pauses, misrecognition, barge-in, provider
failures); sales simulation (interested, skeptical, angry, price objection, competitor
objection, "send me an email", "call me later", wants human, not interested, highly qualified);
security (tenant isolation, unauthorized tools, prompt injection, data leakage, auth bypass,
privilege escalation); compliance (DND, windows, consent, campaign restrictions, blocked calls,
audit records).

## 26. Development phases

1. **Foundation** — repository, FastAPI, PostgreSQL, SQLAlchemy, Alembic, authentication,
   tenant/user/membership models, thin RBAC, provider interfaces, configuration, health,
   logging, errors, tests, Docker.
2. **Browser voice** — browser mic → VAD/turn detection → streaming STT → Model Gateway →
   streaming TTS → browser audio.
3. **Voice quality** — latency, barge-in, interruption, silence, streaming, backchannel,
   reconnection, evaluation, regression testing.
4. **Memory** — transcript persistence, durable lead facts, retrieval, confidence, provenance,
   tenant-safe memory.
5. **Sales tools** — qualification, lead updates, objection logging, follow-ups, calendar,
   meeting booking, human handoff.
6. **Telephony + compliance gate** — provider, outbound/inbound calls, webhooks,
   recordings/transcripts where allowed, failure recovery, call lifecycle, and the pre-call
   compliance gate (amendment 1).
7. **Compliance hardening** — versioned policies, India policy pack, campaign restrictions,
   audit logs, counsel review.
8. **SaaS platform** — dashboard, agent management, campaigns, analytics, usage/cost, billing
   boundaries, multi-tenant administration, custom roles.
9. **Pilot** — controlled pilots measuring voice quality, sales outcomes, conversion, cost,
   reliability, compliance, handoff and incident rate. Only then broad production deployment.

## 27. Not now

Do not jump ahead into production telephony, large-scale campaigns, billing, advanced memory,
complex CRM integrations, production compliance automation, full analytics, massive agent
orchestration, multiple speculative providers, or autonomous architecture redesign.

## 28. Engineering rules

1. Read the architecture and implementation documentation before architectural changes.
2. Do not redesign silently: stop, explain the problem, propose an alternative, wait for
   approval.
3. The LLM is not the application controller.
4. The LLM cannot directly access PostgreSQL.
5. External side effects go through validated tools/services.
6. Provider SDKs stay behind adapters/interfaces.
7. Tenant isolation is enforced server-side.
8. Provider secrets never reach the browser.
9. Compliance is enforced deterministically on the server.
10. Every meaningful feature has tests.
11. Database changes require migrations.
12. Do not implement future phases prematurely.

## One sentence to remember

Aurevia is a multi-tenant AI sales workforce platform that combines real-time voice AI,
deterministic sales control, tools/actions, memory, CRM/calendar integrations, compliance,
analytics and human handoff to automate the sales-conversation lifecycle — built foundation
first, so those capabilities can be added without rewriting the system.
