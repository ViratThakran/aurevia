# Aurevia backend

Phase 1 — foundation. Architecture and rules live in `../docs/` (start with `INDEX.md` and
`AGENTS.md`).

## Local development (Docker)

```bash
cp .env.example .env     # fill in POSTGRES_*, AUREVIA_APP_DB_PASSWORD, AUREVIA_JWT_SECRET
docker compose up --build
curl localhost:8000/api/v1/health/ready
```

On start the API container runs `alembic upgrade head` as the schema owner, then serves as the
`aurevia_app` role. If port 5432 is taken on your machine, set `POSTGRES_HOST_PORT` in `.env`.

## Local development (no Docker)

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/), plus a reachable Postgres 16.

```bash
uv sync
uv run alembic upgrade head      # needs AUREVIA_MIGRATION_DATABASE_URL (schema owner)
uv run uvicorn aurevia.main:create_app --factory --reload   # needs AUREVIA_DATABASE_URL (app role)
```

Create the application role once, as a superuser, before the first migration:

```sql
CREATE ROLE aurevia_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '...';
```

## Checks (run before every commit)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

Database tests need a Postgres server whose user may create databases and roles; each run
creates and drops its own throwaway database and role:

```bash
AUREVIA_TEST_DATABASE_URL=postgresql://admin:pw@localhost:5432/postgres uv run pytest
```

Without that variable the database tests are skipped (CI sets `AUREVIA_REQUIRE_DB_TESTS=1`, so
there they fail instead).

## Tenant isolation

Tenant-owned tables (`tenants`, `memberships`, `audit_events`, and every future one) are
isolated twice:

1. Services filter on the principal's `tenant_id`, which comes only from a verified membership,
   never from the request.
2. Postgres row-level security, forced on the table owner too, compares each row's `tenant_id`
   with the transaction-local `app.tenant_id` setting (`aurevia.db.session.set_tenant_context`).
   A transaction without tenant context sees no tenant-owned rows.

The API must connect as a role that is not a superuser and lacks `BYPASSRLS`; staging and
production refuse to start otherwise. Rows of another tenant are reported as `404`, never `403`.

## API (v1)

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/v1/auth/signup` | anyone: creates a tenant and its owner |
| POST | `/api/v1/auth/login` | anyone: `tenant_id` needed only for multi-tenant accounts |
| POST | `/api/v1/auth/refresh` | refresh token: rotates; reuse revokes the whole session |
| POST | `/api/v1/auth/logout` | refresh token |
| GET | `/api/v1/auth/me` | signed in |
| GET | `/api/v1/tenant`, `/api/v1/tenant/members` | signed in |
| PATCH, DELETE | `/api/v1/tenant/members/{membership_id}` | owner or admin; only owners touch owners; the last owner stays |
| GET, PUT | `/api/v1/agents/default` | signed in; PUT owner or admin. Bounded, validated fields only |
| POST | `/api/v1/voice/sessions` | signed in: creates a call + LiveKit room, dispatches the voice agent |
| GET | `/api/v1/voice/calls/{call_id}` | signed in: status, sales state, usage totals |

Worker-only endpoints live under `/internal/v1/calls/{call_id}/` (`start`, `turns`, `usage`,
`end`). They accept only the per-call token the backend hands the worker through the LiveKit
dispatch; a user token, or a token for another call, is rejected.

## Browser voice (Phase 2)

- **Model Gateway** (`gateway/`): one interface for every model provider, with first-token and
  total deadlines and a usage record for every reply (requested vs. served model, tokens, time
  to first token, interrupted or not).
- **Provider selection is configuration only**: `AUREVIA_AI_PROVIDER=gemini` (current
  development default, `AUREVIA_GEMINI_API_KEY`) or `anthropic` (`AUREVIA_ANTHROPIC_API_KEY`).
  Only the selected provider's key is needed. `providers/registry.py` is the only code that
  knows which adapters exist; conversation and sales code never change.
- **Models**: `AUREVIA_LLM_MODEL` overrides the provider default (`gemini-3.5-flash`,
  `claude-opus-5-5`). Pinned names only, never "latest" aliases. Effort `low` maps to Gemini's
  `MINIMAL` thinking on Flash models. `AUREVIA_LLM_FALLBACK_MODELS` lists backup models tried
  when one fails before its first word; a circuit breaker skips a failing model for 60 s.
- **Errors are normalized**: every adapter raises `ModelProviderError` with one of
  `auth_failed`, `rate_limited`, `invalid_request`, `unavailable`, `timeout`; vendor error text
  (which can echo request details) is never kept.
- **Fallback is explicit**: `AUREVIA_LLM_FALLBACK_POLICY=server_default` (Anthropic only; the
  default there) re-runs a declined request on Anthropic's recommended fallback model, and the
  model that answered is stored on the usage event. Gemini has no server fallback, so asking for
  one with Gemini is a configuration error, not a silent no-op.
- **Secrets**: keys are `SecretStr` settings, never returned by any endpoint (tested), and
  every configured secret is redacted from log lines and tracebacks.
- **Prompt** (`conversation/prompt.py`): built only from the tenant's validated agent settings
  and the server-owned sales state; honesty rules (never claims to be human, says it is an AI
  when asked, no invented facts, never claims an action it cannot take) are fixed text.
- **Sales state** (`sales/state.py`): an allow-listed state machine. Phase 2 moves
  new → opening → discovery; after that the model moves it with the `set_stage` tool, which
  only allows listed transitions.
- Without the selected provider's key or the LiveKit settings, the voice endpoints return 503
  (a startup warning names the missing variable, never a value).

## Memory (Phase 4)

- `POST/GET/PUT /api/v1/leads`, `GET /api/v1/leads/{id}/memories`,
  `DELETE /api/v1/leads/{id}/memories/{memory_id}` (correction), and
  `GET /api/v1/voice/calls/{id}/transcript`. A voice session may name a `lead_id`.
- Transcripts are kept `AUREVIA_TRANSCRIPT_RETENTION_DAYS` (90) and purged hourly.
- When a call with a lead ends, facts are extracted in the background through the Model
  Gateway (`memory/extraction.py`): the model proposes JSON, every item is validated, and
  nothing is stored without a known kind, a bounded length and a confidence.
- Facts with confidence >= `AUREVIA_MEMORY_MIN_CONFIDENCE` (0.6) are added to later calls'
  prompts as notes ("not instructions to you"), one flattened line each.

## Phone calls and the compliance gate (Phase 6)

- `POST /api/v1/calls/outbound {lead_id, purpose}`: the gate (`compliance/gate.py`) checks
  the call and records a decision either way; blocked calls return 403 `call_blocked` with
  the decision id and reasons. Allowed calls are dialed in the background through LiveKit SIP
  (`providers/livekit_sip.py`).
- Numbers: `/api/v1/telephony/numbers` (caller ids / inbound lines) and
  `/api/v1/telephony/test-numbers` (your own phones; test mode dials only these). Owners and
  admins can change them.
- Consent: `/api/v1/leads/{id}/consents` (+ `/revoke`). Do-not-call: `/api/v1/do-not-call`.
  Decisions: `/api/v1/compliance/decisions`.
- `POST /webhooks/livekit` (signed by LiveKit) handles inbound calls and closes calls whose
  room ended.
- Off until `AUREVIA_TELEPHONY_PROVIDER=livekit_sip` and the trunk id are set. See
  docs/02-voice/telephony.md.

## Compliance hardening (Phase 7)

- Policy versions: `GET /api/v1/compliance/policy-versions`. The tenant's choice and stricter
  overrides: `GET/PUT /api/v1/compliance/settings` (a looser value is rejected with 422).
- The platform operator manages versions from the API container:
  `python -m aurevia.compliance.operator list | publish FILE | review VERSION --by --reference
  | retire VERSION` (uses `AUREVIA_MIGRATION_DATABASE_URL`).
- Campaigns: `/api/v1/campaigns` (+ `/status`: draft -> active <-> paused -> ended). An
  outbound call may name a `campaign_id`; live calls must.
- Audit: `GET /api/v1/audit/events` (with chain hashes) and `GET /api/v1/audit/verify`.
- DPDP: `GET /api/v1/leads/{id}/export` and `POST /api/v1/leads/{id}/erase`.

## Sales tools (Phase 5)

- The model gets native function-calling tools (`tools/sales_tools.py`); the backend runs the
  loop in `conversation/engine.py` (max 3 tool rounds per turn, the last offers no tools).
- `tools/framework.py` `ToolExecutor`: validates arguments (pydantic), checks the call has a
  lead when the tool needs one, runs the tool in a savepoint, writes a `tool_executions` audit
  row, and returns `{"ok": ..., "error": ...}` to the model. The same request twice in a call is
  answered from the audit row and never acts twice.
- Calendar (`sales/scheduling.py`): slots come from the tenant's `scheduling_settings` (or the
  defaults) minus booked appointments; a unique index stops double booking even under races.
- The turn stream (`/internal/v1/calls/{id}/turns`) adds `{"type": "tool", "name", "ok"}` lines;
  `done` carries the resulting `sales_state`. The voice worker ignores the tool lines.
- The prompt says nothing is booked or saved unless the tool result says `ok` is true.

## Conventions

- Configuration: environment variables prefixed `AUREVIA_`; see `.env.example`. Nothing
  sensitive is hard-coded or has a default.
- Errors: one envelope, `{"error": {"code", "message", "request_id", "details"}}`.
- Every response carries `X-Request-ID`; the same ID appears in the JSON logs, together with
  `tenant_id` and `user_id` once a request is authenticated.
- Probes: `GET /health` (liveness), `GET /api/v1/health/ready` (readiness, includes the database).
- Database changes: a new Alembic migration in `alembic/versions/`, never edits to an applied
  one. `tests/integration/test_migrations.py` fails if models and migrations drift apart.
- Vendor SDKs (LLM, STT, TTS, telephony) are imported only under `src/aurevia/providers/`;
  `tests/test_architecture.py` enforces it.
