# Sales-learning system: technical design (future milestone, not implemented)

**Goal:** improve how the agent sells by learning from **authorized** sales conversations. Every technique must be backed by evidence, approved by a person, versioned and scoped to one tenant.

**Non-goals:**
- no fine-tuning or training of any foundation model
- no automatic learning from raw customer calls
- no unreviewed technique ever reaches a live call
- no audio pipeline in the first stages

## 1. Principles

1. **Authorization first.** Only transcripts the tenant is entitled to use, imported deliberately, with a recorded legal basis. Aurevia's own call transcripts are included only if the tenant opts in.
2. **Privacy by design.** Personal data is redacted **before** anything else touches the text. Raw imports are kept for the shortest time possible.
3. **Evidence, not causation.** A technique that appears in more booked calls is a *candidate*. Correlation is reported as correlation; only controlled simulation and A/B testing count as evidence of effect.
4. **Humans approve.** Candidates stay inert until a permitted person approves them. Every approval is audited.
5. **Same controls as today.** Techniques shape *what the agent says*. They never bypass the sales-state engine, tool validation, the compliance gate or AI disclosure. A technique that conflicts with a policy is rejected automatically.

## 2. Pipeline

```text
Import (authorized transcripts) → Redact PII → Segment + label → Extract candidate techniques
   → Review queue (human) → Approved playbook version (tenant-scoped) → Retrieval at turn time
   → Simulated A/B (baseline vs candidate playbook) → Pilot A/B → Metrics
```

| Stage | What it does | Storage (new tables, tenant-scoped, forced RLS) |
|---|---|---|
| 1. Import | Upload transcripts (CSV/JSON: speaker, text, timestamps, outcome if known) with a declared source and legal basis (`consent`, `own business record`, …). **Recordings:** a separate, later approval (§6) | `learning_sources` (source, legal basis, uploaded by, retention date), `learning_transcripts` (redacted only) |
| 2. Redact | Remove names, phone numbers, emails, addresses, policy and ID numbers, using deterministic patterns plus a model-based detector through the Model Gateway. Placeholders keep structure ("[NAME]"). The un-redacted upload is deleted once redaction succeeds | Redaction report per transcript (counts, not values) |
| 3. Label | Call outcome (booked / attended / qualified / not interested / no answer), qualification facts captured, objections and their categories, next step agreed, talk-time ratio, question count. Labels come from tools when the call was ours; otherwise from the model plus spot checks by a person | `learning_labels` (label, value, source: tool / model / human, confidence) |
| 4. Extract | Candidate techniques: a short pattern ("acknowledge price concern, then ask about current claim experience"), with the conversation excerpts that show it (redacted), how often it occurs in good vs poor outcomes, the confidence, and the conditions (stage, objection type, language) | `technique_candidates` (text, conditions, evidence ids, outcome stats, extractor version) |
| 5. Review | A person with a new `learning.review` permission approves, edits or rejects each candidate. An automatic policy check (honesty, no invented facts, no pressure tactics, compliance rules) runs first and can block it | `technique_reviews` (decision, reviewer, reason); audit events |
| 6. Playbook | Approved techniques are grouped into an **immutable, versioned playbook per tenant**, like policy versions: draft → active → retired. One active version per agent | `playbooks`, `playbook_techniques` |
| 7. Retrieval | Each turn, the conversation engine picks ≤ 3 techniques whose conditions match the current sales state, objection category and language. They go into the prompt as a "Techniques that work for this team" section, framed as guidance, below the honesty rules and never replacing them | No new storage; the turn records which playbook version and techniques were offered (`turn_techniques`) |
| 8. Evaluate | The simulator and evaluation runner compare the **baseline** playbook (none) with the **candidate** version on the same scripted prospects (plus new ones from objections seen in imports), several runs each. Only an improvement with no regression in honesty or compliance can become active. Then a pilot A/B: 50 % of calls per tenant, with the playbook version recorded per call | Evaluation reports per playbook version |

## 3. Metrics

Per playbook version, per tenant:
- qualification rate (connected calls with a qualified lead)
- **meetings booked** and **meetings attended**, the latter confirmed by a person or a calendar integration
- conversation quality: reviewer score 1–5, and the evaluation style metrics (`evaluation/style.py`)
- compliance: gate blocks, do-not-call requests honoured, AI disclosure on request (evaluation scenarios), and zero false claims (judge)
- latency: retrieval must add < 50 ms, and the prompt stays within budget
- **cost per qualified meeting:** (model + STT + TTS + telephony) / qualified meetings, from the usage and cost engine

## 4. Security and tenant isolation

- Every learning table has `tenant_id`, forced RLS and app-role grants without DELETE, except for retention purges via SECURITY DEFINER, as with transcripts.
- Techniques never cross tenants. A cross-tenant "global playbook" would need separate legal review and anonymised, aggregated evidence. It is out of scope.
- Imported text is treated as untrusted data: it may contain prompt-injection attempts. Extraction prompts frame it as data, and candidate text is length-limited and policy-checked before review.
- Permissions: `learning.import`, `learning.review`, `learning.publish`, granted separately.

## 5. Retention and DPDP

- Redacted transcripts: kept for a configurable period (default 180 days), then purged.
- Techniques keep only short redacted excerpts as evidence. They are deleted with their source unless the tenant explicitly keeps them as aggregated statistics.
- Erasure: the existing `erase_lead` path extends to any learning data that came from that person's calls, linked by call id at import.
- Export: learning data about a person is included in the existing DPDP export.

## 6. Recording support: requirements before any audio is stored

Audio is **not** stored today; the platform keeps transcripts only. Before recordings could be ingested, all of the following must hold:
1. **Consent:** a recording notice at the start of every recorded call, consent captured and stored, and no recording when consent is refused. Counsel confirms the wording and the IRDAI / DPDP basis.
2. **Retention:** a fixed period per tenant, automatic deletion, and deletion included in erasure.
3. **Security:** encrypted object storage in an Indian region, per-tenant prefixes and keys, signed short-lived URLs, access audited, never public.
4. **Minimisation:** audio is used only to produce a better transcript (diarisation, accuracy), then deleted. No voice cloning, no biometric use.
5. **Separate approval:** it ships behind its own permission and a tenant-level switch, with counsel's sign-off recorded like policy reviews.

## 7. Delivery stages

1. Import + redaction + labels for authorized transcripts, with a manual review UI. **No live effect.**
2. Candidate extraction with evidence and confidence; the review queue.
3. Versioned playbooks; simulation A/B against the baseline.
4. Retrieval into live calls for one pilot tenant behind a switch, with call-level A/B.
5. Recording ingestion, only after §6 is approved.
