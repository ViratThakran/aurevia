# Cost and Usage Engine

Track:
- Telephony minutes
- STT usage
- TTS usage
- LLM input/output tokens
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
