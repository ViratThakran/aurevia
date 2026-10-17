# Cost and Usage Engine

Track:
- Telephony minutes
- STT usage
- TTS usage
- LLM input/output tokens. Input is priced in three parts: plain input (`llm_input_tokens`), input read from the prompt cache (`llm_cached_input_tokens`) and input written to it (`llm_cache_write_input_tokens`). A part with no price of its own is reported as unpriced, never charged at another rate.
- Storage
- Infrastructure allocation

Every usage event should record tenant, call/session, provider, resource type, quantity, unit, provider cost where available, estimated platform cost and timestamp.

Do not hard-code provider prices throughout application code. Keep pricing versioned/configurable.

Phase 1: instrument usage. Billing enforcement comes later.
