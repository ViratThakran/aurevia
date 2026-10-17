# Phase 12: Learning from the expert recordings

State: **in progress (built early, off by default, not proven on real calls).** Content is from the plan, plus build status. Follows
`docs/07-learning/sales-learning-design.md` (design only today) and adds the audio step it
leaves out.

## Goal

Turn Virat's 50 to 60 recordings of top cold callers into an approved playbook of what to say
(objections, hooks, closes) and a timing profile of how they say it (pauses, backchannels, talk
ratio).

## Gate 12 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| Playbook v1 for the first niche | approved by a person | Review queue decisions (WP-12.6, 12.7) |
| Simulated A/B vs no-playbook baseline | better objection handling and booking, zero honesty or compliance regressions | WP-12.8 simulator runs. Exact metric and margin: **to confirm** |
| Timing profile | feeds Phase 11 | Profile file read by Phase 11 defaults (WP-12.5) |
| Seed playbook | at least 10 seeded entries approved by Virat | Playbook entries with status `approved` |
| Test call | agent follows the goal ladder and tone changes by stage | A test call. Simulated or real: **to confirm** |

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 12.0 | Inventory (Virat): one row per recording: file, caller, caller permission proof, language, industry and product, outcome, length, prospect-consent evidence. Pick the first niche. | Sheet complete and counsel has seen the prospect-consent question. | Not started (Virat) | none |
| 12.1 | Transcribe with timing: batch STT adapter behind the provider layer, speaker separation, word timestamps, English, Hindi, Hinglish. Audio used only to transcribe, then deleted; encrypted Indian-region storage, per-tenant keys and audited access before any audio is stored. | Three calls checked by a human and word error rate recorded. | Not started | none |
| 12.2 | Redact names, phone numbers, emails, addresses, ID numbers (patterns plus a model detector through the Model Gateway); placeholders keep structure; delete the original. | Report shows counts only; a test seeded with fake personal data finds none left. | Built with fakes: patterns plus a detector interface (`GatewayDetector` through the Model Gateway); counts-only report; a seeded test finds none left. Not proven on real transcripts | [#38](https://github.com/ViratThakran/aurevia/pull/38) |
| 12.3 | New migrations for `learning_sources`, `learning_transcripts`, `learning_labels` (tenant_id, forced RLS); permissions `learning.import`, `learning.review`, `learning.publish`; CSV and JSON import. | Tenant-isolation tests pass for every new table. | Built, API off by default (`AUREVIA_LEARNING_ENABLED`); isolation tests pass for all three tables; `source_type` (call or talk) included, talks refuse timings | this PR |
| 12.4 | Label each call: stage markers, objection category, outcome, qualification facts, next step, talk ratio, question count. Model proposes; a person spot-checks about one in five. | Label accuracy against the human check recorded. | Not started | none |
| 12.5 | Timing profile per stage: pause before replying (p10, p50, p90), overlap rate, backchannels per minute and placement, speech rate, turn length. Aggregates only, no voice fingerprints. | A profile file exists and Phase 11 reads it for defaults. | Not started | none |
| 12.6 | Technique extraction and review: candidates with redacted excerpts, frequency in booked vs unbooked calls, conditions; automatic policy check first; dashboard review queue (approve, edit, reject), every decision audited. | **To confirm** (no done-when in the plan). | Not started | none |
| 12.7 | Playbooks and retrieval: immutable versions (draft, active, retired), one active per agent; at most three techniques per turn as guidance below the honesty rules. | Retrieval adds under 50 ms and records which techniques were offered. | Not started | none |
| 12.8 | Evaluate: simulator A/B (baseline vs candidate, scripted prospects plus new ones from the recordings' objections); only an improvement with no regression can become active; then a live A/B on 50% of pilot calls, version stored per call. | **To confirm** (the plan states the rule but no done-when). | Not started | none |
| 12.A | Phase 12 addition: `source_type` (`call` or `talk`); a call needs speaker labels, a talk skips timing and never builds a timing profile. Fixed playbook format (situation, what the agent says, tone, goal, source, status `proposed`/`approved`). Seed 15 to 20 entries from the expert material. | At least 10 seeded entries approved by Virat (Gate 12 addition). | Not started | none |

The plan's seed material (call structure, goal ladder, objection method, booking, qualification,
tone by stage) is in the plan PDF, page 8 to 9. It is input for WP-12.A, not approved content.

## Decisions and open questions

- Virat: the recordings inventory, the first niche (insurance brokers or the recordings'
  industry), voice cloning yes or no (the plan's default is **no**; it needs each speaker's
  written consent and a counsel check).
- Principles that stay: authorized sources only; redact first; correlation is not proof; a
  person approves every technique; techniques never bypass the sales-state engine, tools,
  compliance gate or AI disclosure; no fine-tuning of any model.
- Prospect consent for the existing recordings: counsel question (WP-12.0).
- Which STT provider does batch transcription: **to confirm**.

## Parts of the system it touches

- Backend: a batch STT adapter in `providers/`, redaction through the Model Gateway, new
  learning tables and migrations, permissions, import, labeling, playbook versions and
  retrieval in the turn prompt, the evaluation harness and simulator.
- Dashboard: review queue for techniques.
- Voice worker: none stated in the plan (**to confirm**).
- Docs: `docs/07-learning/`.

## Risks and dependencies

- Depends on Virat's inventory and counsel's view on prospect consent before audio is used.
- Feeds Phase 11 (timing profile) and Phase 17 (niche choice).
- Risk: recordings too few or too narrow. Fallback: add objections from simulation, grow the
  library from opt-in pilot calls, start with one niche.
- Personal data in recordings: audio deleted after transcription; storage rules from design
  section 6 apply first.

## Measured results

None yet.

## Done checklist

- [ ] WP-12.0 inventory complete; counsel has seen the consent question
- [ ] WP-12.1 to 12.8 and 12.A done-when met (12.6 and 12.8 done-when to confirm)
- [ ] Gate 12 met, including at least 10 approved seed entries and the goal-ladder test call
- [ ] Definition of done for each WP; tenant-isolation tests for every new table; `CLAUDE.md` status and this file updated
