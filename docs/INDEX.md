# Aurevia AI Sales Agent — Documentation Index

## Start here
- `STATUS.md` — current state, open PRs, blockers, next step (read first every session)
- `RUN-LOCAL.md` — run Aurevia on your own Windows PC and test by voice with a microphone
- `phases/README.md` — phases 10 to 18, one file each, from the master plan in `plan/`

## 00 Foundation
- `00-foundation/master-brief.md` — source of truth, with approved amendments
- `00-foundation/README.md`
- `00-foundation/product-spec.md`
- `00-foundation/architecture.md`
- `00-foundation/implementation-plan.md`

The detailed architecture and build plan, with diagrams, is kept as a shared doc:
"Aurevia — Architecture & Build Plan".

## 01 AI Engine
- `01-ai-engine/agent-spec.md`
- `01-ai-engine/ai-model-gateway.md`
- `01-ai-engine/sales-control-engine.md`
- `01-ai-engine/tool-and-action-framework.md`
- `01-ai-engine/conversation-memory.md`

## 02 Voice
- `02-voice/voice-runtime.md`
- `02-voice/voice-provider-abstraction.md`
- `02-voice/voice-quality-evaluation.md`

## 03 Platform
- `03-platform/api-spec.md`
- `03-platform/database-schema.md`
- `03-platform/backend-prompt.md`
- `03-platform/frontend-prompt.md`
- `03-platform/multi-tenancy.md`
- `03-platform/cost-and-usage-engine.md`

## 04 Compliance & Security
- `04-compliance-security/compliance.md`
- `04-compliance-security/compliance-engine.md`
- `04-compliance-security/security.md`
- `04-compliance-security/security-threat-model.md`

## 05 Operations
- `05-operations/observability-and-operations.md`
- `05-operations/cloud-setup.md` — cloud development, secrets, hosting requirements
- `05-operations/hosting-plan.md` — hosting plan (Option A: one server, Compose, HTTPS)
- `05-operations/hosting-runbook.md` — deploy, update, roll back, back up the hosted stack (`deploy/`)
- `05-operations/deployment-and-environments.md`
- `05-operations/disaster-recovery.md`

## 06 Testing
- `06-testing/pilot-acceptance-tests.md`
- `06-testing/voice-evaluation.md`
- `06-testing/security-tests.md`
- `06-testing/compliance-tests.md`

## Source of truth
`master-brief.md` wins over every other document. Keep `architecture.md`,
`implementation-plan.md`, `AGENTS.md`, and this index synchronized with it when architecture
changes.
