# Aurevia status

Last updated: 17 Oct 2026 (fourth session, after merging #22, #23, #17, #24). **Update this file at the end of every work session.**
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
| 10.1 Restore real audio (Cartesia) | Blocked: keys, Cartesia credits. |
| 10.2 Model bake-off | Not started. On hold until Virat says go. Needs the paid key. |
| 10.3 Cut model time | Merged in PR #18 (17 Oct). Done-when not measured yet. |
| 10.4 Turn-handling benchmark (Deepgram) | Blocked: keys. |
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

None open (17 Oct, after this docs PR). Merged on 17 Oct, each with CI green:

| PR | What |
|---|---|
| [#22](https://github.com/ViratThakran/aurevia/pull/22) | Pricing (c): Claude cache writes priced separately (migration 0011) |
| [#23](https://github.com/ViratThakran/aurevia/pull/23) | Pricing (a): reviewed price file, add-only loader, startup check |
| [#17](https://github.com/ViratThakran/aurevia/pull/17) | Hosting stage 1: `deploy/` packaging, now loading prices after migrations. Nothing deployed: no server exists. |
| [#24](https://github.com/ViratThakran/aurevia/pull/24) | Pricing (b): warn on unpriced usage (usage page, analytics, logs); fixes the #18 limit test |

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
| Cloud environment: `AUREVIA_GEMINI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` not set, and `api.deepgram.com`, `api.cartesia.ai` refused by the network policy, in all three 17 Oct sessions. Settings only reach a **new** session. | Virat |
| Paid Gemini key (expected about 19 Oct). Needed for 10.2 and a fair Gate 10 run. | Virat |
| Cartesia credits for 10.1. | Virat |
| The Gemini key pasted into chat on 17 Oct should be rotated. | Virat |
| Human microphone test (10.5). | Virat |
| Check the Gemini prices on https://ai.google.dev/gemini-api/docs/pricing; if they match, a PR sets `verified = true` in `prices.toml` (and `tests/test_prices_file.py`). Until then Gemini usage is unpriced. | Virat |
| Not Phase 10: hosting server and public IP, Exotel trunk, counsel's review of the India policy. | Virat / counsel |

## 5. Next step

Virat: in the cloud environment settings, set the three variables above, add `api.deepgram.com`
and `api.cartesia.ai` to Allowed domains, save, start a new session, and paste:

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
