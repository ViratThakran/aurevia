# Aurevia status

Last updated: 17 Oct 2026 (second session). **Update this file at the end of every work session.**
No key values in this file, ever. Name the variable, not its value.

## 1. Where we are

**Phase 10 (speed and voice acceptance), WP-10.3 (cut model time).** Plan: `docs/plan/`.
Gate 10: median end of speech to first audio under 1.0 s, p95 under 1.8 s, the 8 sales
scenarios pass, and Virat signs off the human microphone test.

| WP | State |
|---|---|
| 10.1 Restore real audio (Cartesia) | Not started. Needs keys and Cartesia credits. |
| 10.2 Model bake-off | Not started. On hold until Virat says go. Needs the paid key. |
| 10.3 Cut model time | Built in PR #18. Real numbers not taken yet. |
| 10.4 Turn-handling benchmark (Deepgram) | Not started. Needs keys. |
| 10.5 Human acceptance | Not started. Needs Virat at a microphone. |

**Measured**
- Before Phase 10: text-path first word about 2.6 to 3 s (free Gemini key).
- PR #18 offline counts (no model called):
  - Model requests before the first word: next step "when could we talk?" 2 → 1; "book Tuesday
    at 11" 3 → 2; pitch 2 → 2.
  - Fresh prompt tokens per request with a warm cache (estimated): next step ~1,855 → ~185;
    pitch ~1,860 → ~40.
- PR #18 backend tests: 357 passed (including database tests, local Postgres 16).
- PR #18 pricing fix: 1M input tokens, 800k from the cache, input 300/M, cached 30/M now cost
  84, not 300. A monthly cost limit of 100 no longer blocks the next call (tested).
- Rough paced run, 17 Oct, free Gemini key, 2 scenarios (a sanity check, **not** Gate 10):
  - Before (main): 6 of 6 turns succeeded. First word 1204, 1374, 2008, 2256, 2907, 3475 ms;
    p50 ≈ 2.1 s, p95 ≈ 3.5 s.
  - After (PR #18): 1 turn succeeded (1649 ms), then rate-limited; run stopped. No comparison
    possible.

**Not measured**
- Gate 10 end-of-speech-to-first-audio p50 and p95 on the real stack.
- WP-10.3 done-when: model first token under 600 ms at the median.
- The 8 sales scenarios after PR #18.
- Real audio retry (10.1), turn handling (10.4), human microphone test (10.5).

## 2. Open pull requests

| PR | What | Waiting for |
|---|---|---|
| [#18](https://github.com/ViratThakran/aurevia/pull/18) | WP-10.3: next-step meeting-time lookup, prompt caching | Real before/after numbers (needs the paid Gemini key, about 19 Oct). Codex P1 (cached tokens billed at the full input price) is fixed: separate `llm_cached_input_tokens` price, migration 0010, test. Cache writes are still priced at the normal input rate. Codex P2 on an older commit (replayed slot lookups) looks covered by the 5-minute window, confirm. CI green. Then "merge PR 18". |
| [#17](https://github.com/ViratThakran/aurevia/pull/17) | Hosting stage 1: `deploy/` packaging | CI backend tests failed (run on Friday evening, likely the weekday slots test that #18 fixes; not confirmed). Codex P2: `deploy.sh` only warns when speech keys are missing, should fail. A real server and domain to verify. Not deploying until told. |

## 3. Decisions Virat has made

- Free meeting times are looked up before the turn **at the next-step stage only**, not during the
  pitch. Listed times are at most 5 minutes old; `book_meeting` still re-checks the slot.
- Phase 10 one WP at a time. **Do not start 10.2 or any later phase until Virat replies.**
- Test text only. Never send real prospect data or call recordings through the free tier.
- If a provider hits a quota: stop and report. No retry loops; benchmark runs are paced.
- A free-key paced run is a rough check only, not the Gate 10 measurement.
- One PR per piece of work. Merge only on an explicit "merge PR N". No auto-merge, no deploy.
- Still open: confirm the Gate 10 and WP-10.5 pass marks (plan, decisions table).

### Prices (cost report and spend limit)

- Prices live in the database, entered in **Platform admin → Prices** in the dashboard (or
  `POST /api/v1/platform/prices`). They are append-only and versioned by date. No database is
  hosted yet, so none are entered anywhere.
- **No cached-token price for a model:** the cost report lists those tokens as *unpriced* and
  shows "not fully priced". The spend-limit check counts them as **zero**, so spend is
  understated and the limit can be passed without blocking calls. Same rule as any other
  unpriced usage: no price is guessed.
- The spend limit only adds up prices in the plan's own currency. Enter prices in the same
  currency as the limit (e.g. all USD), or they are left out of the limit.
- Prices to enter, per 1M tokens (USD). Use the exact model name or `*` for the provider:

  | Provider / model | `llm_input_tokens` | `llm_cached_input_tokens` | `llm_output_tokens` | Source |
  |---|---|---|---|---|
  | `gemini` / `gemini-3.5-flash` (default) | 1.50 | 0.15 | 9.00 | Third-party sites only, **check Google's page first** |
  | `anthropic` / `claude-opus-5-5` | 4.00 | 0.20 | 20.00 | Anthropic pricing page, 17 Oct 2026 |

- Known gap: Anthropic cache *writes* cost 1.25x input ($5 per 1M on Opus 5.5) but are priced
  at the normal input rate (slightly understated). Gemini cache storage is not tracked.

## 4. Blocked

| What | On whom |
|---|---|
| Cloud environment: `AUREVIA_GEMINI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` were not set in the last two sessions, and `api.deepgram.com` and `api.cartesia.ai` were refused by the network policy. Still the case in the 17 Oct second session. Settings only reach a **new** session. | Virat |
| Paid Gemini key (expected about 19 Oct). Needed for 10.2 and a fair Gate 10 run. | Virat |
| Cartesia credits for 10.1. | Virat |
| The Gemini key pasted into chat on 17 Oct should be rotated. | Virat |
| Human microphone test (10.5). | Virat |
| Enter model prices (input, cached input, output) in Platform admin → Prices once a database is hosted; check the Gemini figures on Google's pricing page first. | Virat |
| Not Phase 10: hosting server and public IP, Exotel trunk, counsel's review of the India policy. | Virat / counsel |

## 5. Next step

Virat: in the cloud environment settings, set the three variables above, add `api.deepgram.com`
and `api.cartesia.ai` to Allowed domains, save, start a new session, and paste:

```text
Read docs/STATUS.md first. Check that AUREVIA_GEMINI_API_KEY, DEEPGRAM_API_KEY and
CARTESIA_API_KEY are set and that api.deepgram.com and api.cartesia.ai are reachable.
Don't print the keys. If anything is missing, stop and tell me exactly what. If all is there:
1. Run 10.1 (Cartesia audio) and 10.4 (Deepgram turn handling) and report measured numbers.
2. Update docs/STATUS.md.
Test text only. If a provider hits a quota, stop and report. The Gemini before/after waits
for the paid key. Don't start 10.2 until I reply.
```

Once the paid Gemini key is in (about 19 Oct), the next session also runs the WP-10.3
before/after, paced with no retries ("before" = main, "after" = phase-10-wp-3-tool-rounds),
and the 8 sales scenarios, reporting p50, p95, and turns succeeded and failed.
