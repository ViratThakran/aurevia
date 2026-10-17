# Phase 10: Speed and voice acceptance

State: **in progress.** WP-10.3 merged; 10.1 and 10.4 blocked on keys. Last updated 17 Oct 2026.

## Goal

Reply about as fast as a person on a call. At the start of the phase the median reply was
about 2.6 to 2.8 s, mostly model time (first token about 1.7 to 2.0 s). The human-feel work in
Phase 11 depends on fixing this first.

## Gate 10 and how to measure it

| Check | Target | How it is measured |
|---|---|---|
| End of speech to first audio, median | under 1.0 s | On the real stack (real speech and voice providers). Tool: **to confirm** (`scripts/voice_benchmark.py` measures the text path only). |
| End of speech to first audio, p95 | under 1.8 s | Same run as above. |
| Sales scenarios | 8 of 8 pass | `python -m aurevia.evaluation.run` (real model, throwaway tenant). |
| Human microphone test | Virat signs off | `docs/06-testing/voice-manual-acceptance.md` (WP-10.5). |

The plan calls these pass marks for speed "to confirm" by Virat (decisions table).

## Work packages

| WP | What | Done when | Status | PR |
|---|---|---|---|---|
| 10.1 | Restore real audio (Cartesia): re-run the Test Call, prove a real audio retry and the "audio played" state, remove the limitation from `docs/02-voice/voice-runtime.md`. | A real retry speaks and the transcript shows played, not just generated. | Blocked (keys, Cartesia credits) | none |
| 10.2 | Model bake-off with a paid key: Flash-Lite class, current Flash, Claude Haiku class (pinned names). Time to first token, end to end, cost per scenario, style. | A default and a fallback model are chosen from numbers saved in `docs/02-voice/benchmarks/`. | Not started. On hold until Virat says go. | none |
| 10.3 | Cut model time: smaller prompt, prompt caching, pre-fetch free slots at the next-step stage. | Model first token under 600 ms at the median, tool rounds per booking drop, `tests/test_conversation.py` and honesty rules unchanged. | Merged 17 Oct; done-when not measured yet (needs the paid key) | [#18](https://github.com/ViratThakran/aurevia/pull/18) |
| 10.4 | Turn-handling benchmark in the simulator: fixed vs dynamic endpointing vs turn-detector model, preemptive TTS on/off, Deepgram key terms. Five runs per setting, then ten human calls for the top two. | The chosen settings and their numbers are in the voice audit doc. | Partial: settings A to D measured (canned model); D's last runs, key terms (E) and preemptive TTS (F) waiting on Cartesia credits; turn-detector model not testable here; ten human calls need Virat | this PR |
| 10.5 | Human acceptance: five browser calls (English and Hinglish), scored with the pilot runbook's call-review rubric. | Virat records the decision in the doc. | Not started (needs Virat) | none |

## Decisions and open questions

Decisions (Virat):
- Free meeting times are looked up before the turn **at the next-step stage only**. Listed
  times are at most 5 minutes old; `book_meeting` still re-checks the slot.
- Cache-read model input is priced separately (`llm_cached_input_tokens`). With no cached price
  set, those tokens are unpriced, not charged at the full rate (PR #18).
- One WP at a time. Do not start 10.2 until Virat replies.
- Test text only. No real prospect data or call recordings through the free tier.
- On a provider quota: stop and report, no retry loops. Benchmark runs are paced.
- A free-key run is a rough check only, not the Gate 10 measurement.

Open questions:
- Confirm the Gate 10 pass marks and the WP-10.5 pass mark (proposed: average 4 of 5 on
  naturalness and timing, no call with a safety failure).
- How end-of-speech-to-first-audio is measured on the real stack: **to confirm**.
- Pricing follow-ups chosen 17 Oct and built in PRs #22 (cache writes), #23 (price file,
  loader, startup check) and #24 (warn on unpriced usage; block before the first pilot).

## Parts of the system it touches

- Backend: `aurevia/conversation` prompt and turn flow, `providers/` (Gemini, Anthropic
  adapters, prompt caching), `tools/` (slot lookup through the audited `ToolExecutor`),
  `usage/costs.py` and `usage_events` (cached tokens), migrations 0009 and 0010,
  `scripts/voice_benchmark.py`, `aurevia.evaluation`.
- Voice worker: Cartesia and Deepgram adapters, endpointing and turn settings, the simulator.
- Dashboard: usage page and price form (one new price type).
- Docs: `docs/02-voice/voice-runtime.md`, `docs/02-voice/benchmarks/`, the voice audit doc,
  `docs/06-testing/voice-manual-acceptance.md`.

## Risks and dependencies

- Needs: the three key variables in the cloud environment (`AUREVIA_GEMINI_API_KEY`,
  `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`), `api.deepgram.com` and `api.cartesia.ai`
  allowed, the paid Gemini key (about 19 Oct), Cartesia credits, Virat for the microphone test.
- The free Gemini key rate-limits after a few turns, so before/after comparisons on it are
  not reliable.
- Plan fallback if replies stay slower than 1.5 s: faster paid model, preemptive speech,
  audio cache, closer region or managed LiveKit media, shorter replies.
- Network distance (India-region hosting) is measured again in Phase 14.

## Measured results

| Date | What | Kind | Result |
|---|---|---|---|
| Before Phase 10 | Text-path first word | Real model, free Gemini key | about 2.6 to 3 s |
| 16 to 17 Oct | PR #18 model requests before the first word | Offline count, no model called | Next step "when could we talk?" 2 → 1; "book Tuesday at 11" 3 → 2; pitch 2 → 2 |
| 16 to 17 Oct | PR #18 fresh prompt tokens per request, warm cache | Offline estimate (about 4 characters per token) | Next step ~1,855 → ~185; pitch ~1,860 → ~40 |
| 17 Oct | Rough paced run, 2 scenarios, before (main) | Real model, free Gemini key | 6 of 6 turns succeeded; first word 1204, 1374, 2008, 2256, 2907, 3475 ms; p50 ≈ 2.1 s, p95 ≈ 3.5 s |
| 17 Oct | Same run, after (PR #18) | Real model, free Gemini key | 1 turn succeeded (1649 ms), then rate-limited; stopped. No comparison possible. |
| 17 Oct | PR #18 pricing fix | Mocked usage rows, real Postgres | 1M input tokens with 800k cached cost 84, not 300 (input 300/M, cached 30/M). Spend-limit effect proven only in PR #24 (limit 100 allows, 80 blocks, outbound path) |
| 17 Oct | PR #18 backend tests | Local Postgres 16 | 357 passed; CI green on backend, dashboard, voice worker |
| 17 Oct | WP-10.4 turn settings (partial; full table in `docs/02-voice/benchmarks/2026-10-17-wp-10-4-turns.md`) | Canned model, real Deepgram and Cartesia, simulator; ranks settings, **not Gate 10** | Reply p50/p95: default 1656/1720 ms; preemptive off 1992/2815 ms; dynamic 1668/1868 ms; 0.8 s wait (6 calls) 1668/1768 ms |
| 17 Oct | WP-10.4 names test, no key terms | Same | "Aurevia" and "Meera" never heard correctly in 5 calls ("Mira from Arabia") |

WP-10.3 real before/after, when the paid key arrives: "before" = commit `fb8afdc`, "after" =
commit `5b17634`.

Not measured yet: Gate 10 timings, WP-10.3's 600 ms target, the 8 scenarios after PR #18,
WP-10.1, the rest of WP-10.4 (key terms, preemptive TTS, D's last runs), WP-10.5.

## Done checklist

- [ ] WP-10.1 real audio retry shows "played"
- [ ] WP-10.2 default and fallback model chosen from saved numbers
- [ ] WP-10.3 model first token under 600 ms at the median, fewer tool rounds per booking
- [ ] WP-10.4 settings and numbers in the voice audit doc
- [ ] WP-10.5 Virat's decision recorded
- [ ] Gate 10: median under 1.0 s, p95 under 1.8 s, 8 of 8 scenarios, microphone sign-off
- [ ] Definition of done for each WP (ruff, mypy, pytest, worker and dashboard checks, OpenAPI regenerated, docs updated, no secrets in logs)
- [ ] `CLAUDE.md` status and this file updated
