# Cost and Usage Engine

Track:
- Telephony minutes
- STT usage
- TTS usage
- LLM input/output tokens. Input is priced in three parts: plain input (`llm_input_tokens`), input read from the prompt cache (`llm_cached_input_tokens`) and input written to it (`llm_cache_write_input_tokens`). A part with no price of its own is reported as unpriced, never charged at another rate.
- Storage
- Infrastructure allocation

Every usage event should record tenant, call/session, provider, resource type, quantity, unit, provider cost where available, estimated platform cost and timestamp.

## Unpriced usage

- Usage with no price is left out of the cost and counts as **zero toward the monthly spend
  limit**. For now it does not block calls; it is shown instead:
  - `GET /api/v1/usage`: `unpriced_usage` (resource and amount) and `spend_limit_understated`;
  - `GET /api/v1/analytics/summary`: `economics.unpriced_usage`;
  - the dashboard's usage page, home page and campaign page;
  - logs: the warning "Spend limit checked with unpriced usage counted as zero" each time a
    call is checked against a spend limit while usage is unpriced.
- Plan limits, including the spend limit, are checked before **outbound phone calls**
  (`telephony/outbound.py`). Browser test calls are not checked against them.
- Before the first pilot or paying tenant this must change to blocking (see
  `docs/phases/phase-14.md`).

Do not hard-code provider prices throughout application code. Keep pricing versioned/configurable.

Phase 1: instrument usage. Billing enforcement comes later.

## Price file and missing-price check

- Model prices are kept in the reviewed file `backend/src/aurevia/platform/prices.toml` and changed only by pull request. Each entry says whether it was `verified` on the provider's own pricing page, and where the figure came from.
- `python -m aurevia.platform.prices load` (schema owner's connection, after migrations) adds the file's entries not yet in `prices`. It never updates or deletes a row, so running it again changes nothing. To change a price, add a new entry with a later `effective_from`. Unverified entries are skipped unless `--include-unverified` is passed.
- `python -m aurevia.platform.prices check` lists model prices missing for the configured models (exit code 1 if any). The API runs the same check at startup and logs one warning per missing price; it never stops startup.
- A model price that is missing makes that usage unpriced: it shows in reports and counts as zero toward the spend limit.
