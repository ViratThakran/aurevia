# Aurevia status

Last updated: 17 Oct 2026 (fifth session: #29 merged; Phase 11 in progress). **Update this file at the end of every work session.**
No key values in this file, ever. Name the variable, not its value.

**Read next: the current phase file, [`docs/phases/phase-10.md`](phases/phase-10.md).** It
has the gate, every work package, decisions and all measured numbers. Index of phases 10 to
18: [`docs/phases/README.md`](phases/README.md).

## 1. Where we are

**Phase 10 (speed and voice acceptance).** WP-10.3 is merged (PR #18); its real-model numbers
are not taken yet. Gate 10: median end of speech to first audio under 1.0 s, p95 under 1.8 s,
the 8 sales scenarios pass, and Virat signs off the human microphone test.

| WP | State |
|---|---|
| 10.1 Restore real audio (Cartesia) | Blocked: **Cartesia out of credits** (HTTP 402, 17 Oct 10:51 UTC). Resumes when Virat says Cartesia is topped up. |
| 10.2 Model bake-off | Not started. On hold until Virat says go. Needs the paid key. |
| 10.3 Cut model time | Merged in PR #18 (17 Oct). Done-when not measured yet. |
| 10.4 Turn-handling benchmark (Deepgram) | Partial (17 Oct): settings A to D measured with a canned model; key terms (E), preemptive TTS (F) and D's last runs **waiting on Cartesia credits**. No default changed. |
| 10.5 Human acceptance | Not started. Needs Virat at a microphone. |

**Measured** (details and dates in the phase file)
- Before Phase 10: text-path first word about 2.6 to 3 s (free Gemini key).
- PR #18 offline: model requests before the first word 2 → 1 (offer a time) and 3 → 2 (book a
  time); fresh prompt tokens ~1,855 → ~185 (next step) and ~1,860 → ~40 (pitch), estimated.
- Rough paced run on the free key, before PR #18: 6 of 6 turns, p50 ≈ 2.1 s, p95 ≈ 3.5 s. After:
  1 turn (1649 ms), then rate-limited. Not comparable, not Gate 10.
- Pricing fix: 1M input tokens with 800k cached now costs 84, not 300 (input 300/M, cached 30/M).
  Correction: the earlier claim that a cost limit of 100 "no longer blocks the next call" was
  not tested (the test used a browser session; limits are checked on outbound calls). Fixed
  and proven in PR #24: limit 100 allows, 80 blocks.
- Backend tests on main after the pricing PRs: 371 passed locally (with database tests); CI green.

**Not measured:** Gate 10 timings, WP-10.3's 600 ms target, the 8 scenarios after PR #18,
WP-10.1, 10.4, 10.5.

## 2. Open pull requests

Open: [#30](https://github.com/ViratThakran/aurevia/pull/30) WP-11.1 backchannel design, **waiting for Virat's approval** (WP-11.2 starts only after it).

Merged on 17 Oct, each with CI green:

| PR | What |
|---|---|
| [#22](https://github.com/ViratThakran/aurevia/pull/22) | Pricing (c): Claude cache writes priced separately (migration 0011) |
| [#23](https://github.com/ViratThakran/aurevia/pull/23) | Pricing (a): reviewed price file, add-only loader, startup check |
| [#17](https://github.com/ViratThakran/aurevia/pull/17) | Hosting stage 1: `deploy/` packaging, now loading prices after migrations. Nothing deployed: no server exists. |
| [#24](https://github.com/ViratThakran/aurevia/pull/24) | Pricing (b): warn on unpriced usage (usage page, analytics, logs); fixes the #18 limit test |
| [#26](https://github.com/ViratThakran/aurevia/pull/26) | Docs: the buildable-now table (section 6), approved by Virat |
| [#27](https://github.com/ViratThakran/aurevia/pull/27) | Fix: the price loader command crashed when run on its own (as `deploy.sh` runs it). Found while setting up WP-10.4; nothing had been deployed. |
| [#28](https://github.com/ViratThakran/aurevia/pull/28) | Docs: the build-early approval and its conditions |
| [#29](https://github.com/ViratThakran/aurevia/pull/29) | WP-10.4, partial: turn benchmark settings A to D (canned model; ranks settings, not Gate 10). Key terms, preemptive TTS and the rest of D wait on Cartesia credits. |
| [#31](https://github.com/ViratThakran/aurevia/pull/31) | Docs: STATUS after #29 (backend CI stalled once; cancelled and re-run, then green) |
| [#32](https://github.com/ViratThakran/aurevia/pull/32) | WP-11.3: agent-side reactions, off by default (`AUREVIA_AGENT_REACTIONS`) |
| [#34](https://github.com/ViratThakran/aurevia/pull/34) | WP-11.4: prospect mood and voice style, off by default (migration 0012) |
| [#35](https://github.com/ViratThakran/aurevia/pull/35) | WP-11.5: natural speech for amounts, phone numbers and dates, off by default |
| [#36](https://github.com/ViratThakran/aurevia/pull/36) | WP-11.6: turn-taking polish, off by default |
| [#37](https://github.com/ViratThakran/aurevia/pull/37) | WP-11.7: human-feel scorecard metrics and listening-test template |
| [#38](https://github.com/ViratThakran/aurevia/pull/38) | WP-12.2: redaction of personal data (library). Backend CI stalled once; cancelled and re-run, then green. |
| [#39](https://github.com/ViratThakran/aurevia/pull/39) | WP-12.3: learning tables (migration 0013, forced RLS), permissions, JSON and CSV import through redaction; off by default (`AUREVIA_LEARNING_ENABLED`) |

Follow-ups, not started:
- Codex P2 from #17: `deploy.sh` only warns when speech keys are missing; it should fail.
- PR #17's "not verified" list (real DNS and certificates, media ports, real audio, SIP, a real
  bucket, cron) waits for a server (WP-14.1).
- CI stalled twice on backend `pytest` (PRs #18 and #24), and a re-run passed both times. The
  cause is unknown; a per-test time limit would make a stall fail fast instead of hanging.

## 3. Decisions Virat has made

- Free meeting times are looked up before the turn **at the next-step stage only**. Listed
  times are at most 5 minutes old; `book_meeting` still re-checks the slot.
- Cache-read input has its own price (`llm_cached_input_tokens`); without one it is unpriced,
  never charged at the full input rate.
- Phase 10 one WP at a time. **Do not start 10.2 or any later phase until Virat replies.**
- Test text only. Never send real prospect data or call recordings through the free tier.
- If a provider hits a quota: stop and report. No retry loops; benchmark runs are paced.
- A free-key paced run is a rough check only, not the Gate 10 measurement.
- One PR per piece of work. Merge only on an explicit "merge PR N". No auto-merge, no deploy.
- Pricing (17 Oct): (a) reviewed price file + add-only loader run by `deploy.sh` + startup
  check; (b) warn on unpriced usage now, **switch to blocking before the first pilot or paying
  tenant** (`docs/phases/phase-14.md`); (c) Claude cache writes priced separately. In PRs #22
  to #24.
- **17 Oct: build the "yes" items of section 6 early**, as an explicit exception to plan rule
  10 and the CLAUDE.md line against building later phases early. Conditions:
  1. One PR per work package, small enough to review.
  2. Every new feature off by default, tested with fake providers, and marked "built, not
     proven on real calls" here.
  3. Order: Phase 10 work needing only Deepgram and Cartesia (10.4, then 10.1; stop if
     Cartesia credits run out), then Phase 11, then Phase 12. Stop after Phase 12 and report
     before Phase 13 or later.
  4. Real model calls (WP-10.3 before/after, 10.2, the 8 scenarios) wait for the paid Gemini
     key. If the free quota is hit, stop that item; no retry loops.
  5. Merge each PR only after CI is green. If backend CI stalls: cancel, re-run once, report.
  6. Update this file after each merged PR.
- **17 Oct, order changed:** do not wait for Cartesia. Phase 11 next (then 12), as above.
  10.1 and the rest of 10.4 resume only when Virat says Cartesia is topped up. No Cartesia or
  other paid provider in the meantime.
- Open, waiting for Virat: Gate 10 and WP-10.5 pass marks.

### Prices (cost report and spend limit)

- Model prices live in the reviewed file `backend/src/aurevia/platform/prices.toml` (changed by
  PR only). `deploy.sh` loads them after migrations; loading only adds rows, and entries marked
  `verified = false` are skipped. Other prices are entered in **Platform admin → Prices**. No
  database is hosted yet, so no prices are loaded anywhere.
- In the file (USD per 1M tokens):

  | Model | Input | Cached input | Cache write | Output | Verified |
  |---|---|---|---|---|---|
  | `gemini-3.5-flash` (default) | 1.50 | 0.15 | none (no charge) | 9.00 | **No**, third-party sites; not loaded |
  | `claude-opus-5-5` | 4.00 | 0.20 | 5.00 | 20.00 | Yes, Anthropic's page, 17 Oct |

- The API logs a warning at startup for each price missing for the configured models.
- **Unpriced usage** (no price for that model and resource) is left out of the cost and counts
  as **zero toward the spend limit**. It is shown with its amount on the usage, home and campaign
  pages and in analytics, and logged when a call is checked against a spend limit. Calls are
  not blocked by it; this must switch to blocking before the first pilot or paying tenant
  (`docs/phases/phase-14.md`).
- The spend limit only adds prices in the plan's own currency (the file uses USD).
- Plan limits, including the spend limit, apply to outbound phone calls, not browser test calls.

## 4. Blocked

| What | On whom |
|---|---|
| ~~Keys and allowed domains~~ **Done in the fifth session (17 Oct):** `AUREVIA_GEMINI_API_KEY`, `DEEPGRAM_API_KEY` and `CARTESIA_API_KEY` are set; Gemini, Deepgram and Cartesia each accepted a free read-only call (HTTP 200). Not yet known: whether the Gemini key is the paid one, and whether Cartesia has credits. No Phase 10 run was started. | Virat |
| Paid Gemini key (expected about 19 Oct). Needed for 10.2 and a fair Gate 10 run. | Virat |
| **Cartesia credits ran out** during WP-10.4 (17 Oct, 10:51 UTC). Needed for 10.1 and the rest of 10.4. Until Virat says it is topped up, no Cartesia or other paid provider is used. | Virat |
| The Gemini key pasted into chat on 17 Oct should be rotated. | Virat |
| Human microphone test (10.5). | Virat |
| Check the Gemini prices on https://ai.google.dev/gemini-api/docs/pricing; if they match, a PR sets `verified = true` in `prices.toml` (and `tests/test_prices_file.py`). Until then Gemini usage is unpriced. | Virat |
| Not Phase 10: hosting server and public IP, Exotel trunk, counsel's review of the India policy. | Virat / counsel |

## 5. Next step

Keys and allowed domains are in place (checked 17 Oct, fifth session). Virat: review the table
in section 6, then either start Phase 10 measurements with the message below, or approve the
table. In a new session, paste:

```text
Read docs/STATUS.md first, then docs/phases/phase-10.md. Check that AUREVIA_GEMINI_API_KEY,
DEEPGRAM_API_KEY and CARTESIA_API_KEY are set and that api.deepgram.com and api.cartesia.ai
are reachable. Don't print the keys. If anything is missing, stop and tell me exactly what.
If all is there:
1. Run 10.1 (Cartesia audio) and 10.4 (Deepgram turn handling) and report measured numbers.
2. Update docs/STATUS.md and docs/phases/phase-10.md.
Test text only. If a provider hits a quota, stop and report. The Gemini before/after waits
for the paid key. Don't start 10.2 until I reply.
```

Once the paid Gemini key is in (about 19 Oct), the next session also runs the WP-10.3
before/after, paced with no retries ("before" = commit `fb8afdc`, main just before PR #18;
"after" = commit `5b17634`, main with PR #18), and the 8 sales scenarios, reporting p50, p95,
and turns succeeded and failed.

## 6. Approved (17 Oct): what in Phases 11 to 18 can be built now

**Yes** means it can be built and tested with fake providers: no paid key, no real call, no
outside account. Each "yes" item would go behind a switch that is **off by default**. Anything
that needs a real measurement (speed, model choice, real audio, real calls, listeners) stays
**waiting on keys** (or on the person named). Nothing here is built yet.

| Phase | Work package | Buildable now | What it needs from Virat |
|---|---|---|---|
| 11 | 11.1 Backchannel spike (design doc, simulator proof) | Yes | Approve the design before 11.2 (the plan says stop for approval). Real-audio check waits on keys and a microphone. |
| 11 | 11.2 Backchannel engine (rules, rate limit, clip lookup) | Yes, after 11.1 is approved | Real clips need Cartesia credits (tests use silent placeholder clips). How often it says "hmm": your choice by ear later. |
| 11 | 11.3 Agent reactions (prompt version, style scoring) | Partly: code and style scoring yes | "8 of 8 scenarios pass" needs the real model: waiting on keys. |
| 11 | 11.4 Mood and emotion (mood field, mood-to-voice mapping) | Yes (mocked voice provider) | Confirm the mapping defaults (the plan's tone-by-stage table). Hearing it waits on keys. |
| 11 | 11.5 Natural speech (rupees, dates, phone numbers, pronunciation dictionary) | Partly: text rules and dictionary yes | A list of company and product names. Hinglish switching benchmark on mixed audio: waiting on keys. |
| 11 | 11.6 Turn-taking polish ("hold on", "repeat that", "I'm driving", silences, goodbye) | Yes (simulator) | Nothing now; how it feels waits on the microphone test. |
| 11 | 11.7 Human-feel scorecard | Partly: metric calculation from transcripts yes | Ten listeners and the blind test; expert numbers from Phase 12. |
| 12 | 12.0 Recordings inventory | No | Your spreadsheet; counsel sees the prospect-consent question. |
| 12 | 12.1 Batch transcription | Partly: adapter interface, fake provider, delete-audio-after rule yes | Real transcription needs your recordings, counsel's view, and storage rules: waiting. |
| 12 | 12.2 Redaction (patterns plus model detector interface) | Yes (fake detector, fake personal data) | Nothing. |
| 12 | 12.3 Learning tables, permissions, CSV and JSON import | Yes (new tables with forced RLS, isolation tests) | Nothing. |
| 12 | 12.4 Labeling (model proposes, person spot-checks) | Partly: label schema, review screen yes | Label accuracy needs the real model and real calls: waiting. |
| 12 | 12.5 Timing profile (pauses, overlaps, backchannels from word timings) | Partly: the calculation on synthetic data yes | The real profile needs your recordings. |
| 12 | 12.6 Technique extraction and review queue | Partly: review queue, audit, automatic policy check yes | Extraction needs real transcripts and the model: waiting. |
| 12 | 12.7 Playbooks and retrieval (versions, max 3 per turn) | Yes | You approve every entry before it can be used. |
| 12 | 12.8 Evaluate (simulator A/B) | Partly: A/B harness with fakes yes | A real result needs the paid model key: waiting on keys. |
| 12 | 12.A Source type (call or talk) and seed playbook format | Yes; seed entries entered as "proposed" | You approve at least 10 entries (Gate 12). |
| 13 | 13.1 Cost metering (reports, budget alert, per-tenant kill switch) | Partly: all of it with fakes yes | "Real cost per minute from 20 test calls": waiting on keys and real calls. |
| 13 | 13.2 Voice bake-off | No | Real audio, listeners, provider accounts. |
| 13 | 13.3 Audio cache (pre-rendered phrases, hit rate) | Yes (fake voice provider) | Real clips need Cartesia credits. |
| 13 | 13.4 Model routing, context trimming, summaries | Partly: routing rules and trimming yes | "Cost per scenario drops" needs the paid key (and 10.2's model choice): waiting. |
| 13 | 13.5 Do not pay for silence | Partly: start speech after answer, call-length cap, skip short non-answers yes | Voicemail detection needs real phone audio: waiting. |
| 13 | 13.6 Phone rates | No | Written quotes from carriers. |
| 13 | 13.7 Pricing plans and ROI calculator | Yes (placeholder numbers, assumptions stated) | Your real prices and pay assumptions before use. |
| 14 | 14.1 Staging server | No | Provider, domain, budget. |
| 14 | 14.2 Region and media measurement | No | A server. |
| 14 | 14.3 Phone trunk | No | Carrier choice and account. |
| 14 | 14.4 Phone-audio quality | No | Real phone calls. |
| 14 | 14.5 Do-not-disturb registry | Partly: caching rules and the four required tests with a fake registry yes | A registry or scrubbing-service account; counsel's caching rules. Unknown stays blocked. |
| 14 | 14.6 Registrations (DLT, caller ID) | No | You and counsel. |
| 14 | 14.7 Counsel review | No | Counsel. |
| 14 | 14.8 Call safety (pacing, abandoned-call limit, daily caps, campaign kill switch, retries) | Yes (some caps exist; tests prove each) | Nothing; real voicemail handling waits on real calls. |
| 14 | 14.9 Operations (alerts for failures, outages, cost spikes) | Partly: alert rules with a fake notifier yes | An alert channel (email or Slack) and a server for the restore drill. |
| 14 | Spend limit blocks on unpriced usage (B1) | Yes, built switched off | Your go-ahead to switch it on before the first pilot. |
| 15 | 15.1 Calendar | Partly: interface, slots, time zones, encrypted tokens, failure tests with a fake calendar yes | A Google Cloud project for sign-in (and later Microsoft). |
| 15 | 15.2 CRM | Partly: interface, field mapping, duplicates, safe retries, signed webhook, CSV export yes | HubSpot and Zoho developer accounts. |
| 15 | 15.3 Messaging follow-ups | Partly: consent-per-channel check, templates only, opt-outs, delivery status with fakes yes | WhatsApp, SMS and email accounts; DLT templates. |
| 15 | 15.4 After the call (sequences, no-show recovery, lead score) | Yes with fakes | Summary quality needs the real model: waiting on keys. |
| 15 | 15.5 Handoff alerts and scheduled callbacks | Yes (fake notifier) | Real email or Slack account later. |
| 15 | 15.6 Public API keys and signed webhooks | Yes | Nothing. |
| 16 | 16.1 Onboarding wizard | Yes | Nothing. |
| 16 | 16.2 Knowledge base | Partly: upload, per-tenant chunks, retrieval with fake embeddings, sources shown yes | Real retrieval quality and the 100 ms budget need a model key: waiting. |
| 16 | 16.3 Vertical templates (insurance first) | Yes | You review the template wording. |
| 16 | 16.4 Practice against simulated prospects | Yes with the fake model | Real practice runs need a model key. |
| 16 | 16.5 Call review screen (no audio) | Yes | Nothing. |
| 16 | 16.6 Analytics funnel | Yes | Nothing. |
| 16 | 16.7 Billing | Partly: invoices, usage charges, trial credits, suspend and resume yes | Razorpay account, legal entity and GST number. |
| 16 | 16.8 Two-factor sign-in, session controls | Yes (authenticator-app codes need no outside account) | Nothing. |
| 16 | 16.9 Owner view (cost, revenue, margin, health) | Yes | Nothing. |
| 16 | 16.10 Customer help | Partly: in-app help pages yes | Terms, privacy policy and DPA from counsel; status page and support email accounts. |
| 17 | 17.1, 17.2, 17.3, 17.6 Niche, pilot design, legal pack, decision | No | You and counsel. |
| 17 | 17.4 Sales material | Partly: demo-call request form with consent capture through the gate yes | Landing page hosting, demo video. |
| 17 | 17.5 Run the pilot | Partly: weekly report generator, pilot tenants with caps, results page yes | Pilot companies. |
| 18 | All items | No | The plan says start none of them before Gate 17; each waits for its trigger. |

Both decisions were made on 17 Oct: build early as an exception to rule 10 (see section 3),
and one PR per work package.

### Built, not proven on real calls

Features built under this approval are listed here. Each is off by default and tested only
with fake providers.

| Work package | PR | Switch (off by default) | Not proven yet |
|---|---|---|---|
| 10.4 tooling: canned model (`AUREVIA_AI_PROVIDER=canned`) | [#29](https://github.com/ViratThakran/aurevia/pull/29) | Only when chosen; refused in staging and production | Benchmark tool only, never a sales model |
| 10.4: Deepgram key terms | [#29](https://github.com/ViratThakran/aurevia/pull/29) | `AUREVIA_STT_KEYTERMS` (empty) | Whether they fix "Aurevia" and "Meera" (run E, waiting on Cartesia credits) |
| 10.4: preemptive text to speech | [#29](https://github.com/ViratThakran/aurevia/pull/29) | `AUREVIA_PREEMPTIVE_TTS` (false) | Any measurement (run F, waiting on Cartesia credits) |
| 11.3 agent-side reactions (prompt variant `voice-2026-10-17.reactions1`, style metrics `reaction_rate`, `repeated_reaction_rate`) | [#32](https://github.com/ViratThakran/aurevia/pull/32) | `AUREVIA_AGENT_REACTIONS` (false) | The 8 sales scenarios and word counts with a real model (paid Gemini key); how it sounds |
| 11.4 prospect mood and voice style (`record_prospect_mood` tool, `calls.prospect_mood`, `turn_metrics.voice_style`, migration 0012) | [#34](https://github.com/ViratThakran/aurevia/pull/34) | Backend `AUREVIA_PROSPECT_MOOD` (false) and worker `AUREVIA_MOOD_VOICE` (false) | How it sounds; whether Cartesia's speed and emotion controls take effect on the current voice model (waiting on Cartesia credits, listening test) |
| 11.5 natural speech (rupee amounts in lakh and crore, mobile numbers digit by digit, numeric dates, a pronunciation list); voice text only, the transcript keeps the original | [#35](https://github.com/ViratThakran/aurevia/pull/35) | `AUREVIA_NATURAL_SPEECH` (false), `AUREVIA_PRONUNCIATIONS` (empty) | How it sounds; per-turn Hinglish switching benchmark on mixed-language audio (waiting on Cartesia and Deepgram) |
| 11.6 turn-taking polish: fixed instant replies for "hold on", "repeat that", "sorry, go ahead" after being cut off, a goodbye and "I'm driving" (the last two end the call); do-not-call and anything about calls or numbers always go to the model | [#36](https://github.com/ViratThakran/aurevia/pull/36) | `AUREVIA_TURN_TAKING` (false) | How it feels on a call (microphone test); the plan has no done-when (to confirm) |
| 11.7 human-feel scorecard: read-only metric calculation (pause before replying p10/p50/p90, talk ratio, words and questions per turn, reactions per minute) and the listening-test template | [#37](https://github.com/ViratThakran/aurevia/pull/37) | None needed (read-only command) | Gate 11 itself: the listening test needs Virat and ten listeners; recordings wait on Cartesia credits; expert numbers wait on Phase 12 |
| 12.2 redaction (`aurevia.learning.redaction`): patterns for email, phone, PAN, Aadhaar, GSTIN, labelled PIN codes; a detector interface for names and addresses (model through the Model Gateway); consistent placeholders; counts-only report; refuses to pass text on if the detector fails | [#38](https://github.com/ViratThakran/aurevia/pull/38) | Library only; used by the learning import (WP-12.3, off by default) | The model detector against real transcripts (needs a model key and real recordings) |
| 12.3 learning tables (`learning_sources` with source type call or talk, `learning_transcripts`, `learning_labels`; migration 0013, forced RLS, no deletes), permissions `learning.import`, `learning.review`, `learning.publish`, JSON and CSV import through redaction | [#39](https://github.com/ViratThakran/aurevia/pull/39) | `AUREVIA_LEARNING_ENABLED` (false; the API answers 404) | Importing real recordings (needs Virat's inventory, caller permissions and counsel's view on prospect consent); the model detector on real transcripts |
| 12.5 timing profile (`aurevia.learning.timing`): per stage and overall, pause before replying p10/p50/p90, overlap rate, backchannels per minute and where they fall, speech rate, turn length; call sources only, numbers only, no text; a CLI writes the profile file | this PR | Nothing runs it automatically; run by hand with the CLI | A profile from real recordings (needs the WP-12.0 inventory and WP-12.1 transcription); WP-11.2 reading it for defaults (waits on PR 30) |
