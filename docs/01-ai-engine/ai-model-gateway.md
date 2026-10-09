# AI Model Gateway

## Purpose
Prevent business logic and voice orchestration from coupling to one LLM provider.

```text
Conversation Layer
       |
AureviaModelGateway
       |
 +-----+------+------+
 |            |      |
Claude      OpenAI  Future
Provider    Provider Provider
```

## Responsibilities
- Provider abstraction
- Model selection
- Request configuration
- Streaming
- Timeouts and retries
- Explicit fallback policy
- Provider health
- Token and cost tracking
- Prompt/model version tracking
- Request correlation
- Per-tenant model configuration where authorized

## Interface
```python
class ModelGateway:
    async def generate(...)
    async def stream(...)
    async def health(...)
```

## Fallback
Fallback must be explicit and policy-controlled. Do not silently change model, cost or behavior.

## Observability
Capture request ID, session/call ID, tenant ID, provider, model, prompt version, latency, usage and errors.

## Security
Provider credentials are server-side secrets only.

## Phase 1
Implement the gateway with one provider first. Add more providers only after the abstraction is tested.

## Implemented (2026-10-08)
- Adapters: Gemini (`providers/gemini_model.py`, current development provider) and Anthropic
  (`providers/anthropic_model.py`). Selected by `AUREVIA_AI_PROVIDER`; built only in
  `providers/registry.py`.
- One normalized error type (`ModelProviderError`: auth_failed, rate_limited,
  invalid_request, unavailable, timeout) for every adapter.
- Fallback: Anthropic's server-side fallback when `llm_fallback_policy=server_default`;
  refused at startup for providers without one.
