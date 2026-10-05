# Cost and Usage Engine

Track:
- Telephony minutes
- STT usage
- TTS usage
- LLM input/output tokens
- Storage
- Infrastructure allocation

Every usage event should record tenant, call/session, provider, resource type, quantity, unit, provider cost where available, estimated platform cost and timestamp.

Do not hard-code provider prices throughout application code. Keep pricing versioned/configurable.

Phase 1: instrument usage. Billing enforcement comes later.
