# Aurevia: notes for Claude (read this first)

**Every session: read `docs/STATUS.md` first, and update it at the end of the session.**

Aurevia is a multi-tenant AI voice sales agent platform: FastAPI backend, a LiveKit voice worker,
and a Next.js dashboard. These notes carry the project's context and working agreement into any
session, local or cloud. The engineering rules are in `docs/AGENTS.md`; the source of truth is
`docs/00-foundation/master-brief.md`. Navigate with `docs/INDEX.md`.

## How to work with this user

- **Explain, then act.** Say briefly what you found and what you will do. Do not redesign the
  architecture silently: stop, explain, propose, wait for approval (AGENTS.md rule 2).
- **One PR per piece of work, never merged without being told.** Open the PR, report it, and
  wait for an explicit "merge PR N". Never enable auto-merge. Never deploy.
- **Report honestly.** Say which checks ran and their real results. Separate mocked tests from
  tests against a real provider, and a human microphone test from a synthetic one. Do not claim
  a real call, booking or recovery that was only mocked. If a check is blocked (credentials,
  quota, a person needed), say it is blocked.
- **Fix a failing test properly.** Never weaken a safety requirement to make CI green.
- **Keep scope tight.** Build only what Aurevia needs; do not copy decorative extras from
  reference designs or add features nobody asked for. Do not build future phases early.
- **Plain language.** The user is not a developer by background: lead with the outcome, put
  commands in code blocks, and say exactly what they need to do.

## Hard rules (security and safety)

- **Never ask the user to paste an API key into chat.** Never print key values in terminal
  output, logs, errors, tests or docs. Secrets are read through the backend configuration
  (`aurevia/config.py`), never exposed to the browser, never committed (`.env` is git-ignored).
  If a secret appears in output, redact it and tell the user to rotate it.
- **The LLM is not the application controller.** Side effects only through validated tools
  (`backend/src/aurevia/tools/`), which are tenant-scoped and audited. A reply is never allowed
  to claim a tool succeeded when it did not.
- **Tenant isolation is enforced twice:** services filter by the principal's tenant, and
  Postgres row-level security backs it up. Every new tenant-owned table needs `tenant_id`, an
  index starting with it, and a forced RLS policy. Never edit an applied migration.
- **No real outbound call without the compliance gate.** Telephony is in `test` mode by
  default (own registered numbers only). Live mode stays blocked until counsel has reviewed the
  India policy pack. The campaign auto-dialer is off unless switched on in both the server
  setting and the campaign. Do not change these safeguards.
- **Voice rules:** the agent never claims to be human, answers honestly when asked if it is an
  AI, never invents product facts, and handles interruptions.
- **Provider SDKs stay behind adapters** in `backend/src/aurevia/providers/` (enforced by
  `backend/tests/test_architecture.py`; the voice worker has its own adapter module).

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI API, Alembic migrations, Model Gateway, tools, compliance, campaigns, usage |
| `voice-worker/` | LiveKit agent: speech in/out, language switching, failure reporting, simulator |
| `web/dashboard/` | Next.js 15 dashboard (white/light, forest-green accent), types generated from OpenAPI |
| `docs/` | Architecture, rules, runbooks, audits, acceptance tests |
| `.github/workflows/ci.yml` | CI: backend, voice-worker, dashboard |

## Checks (run before every commit; CI runs the same)

```bash
# backend (Python 3.12, uv)
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run python scripts/export_openapi.py ../web/dashboard/openapi.json   # then git diff must be empty

# voice worker
cd voice-worker
AUREVIA_BACKEND_URL=http://backend.invalid uv run ruff check . && uv run ruff format --check . \
  && uv run mypy && uv run pytest

# dashboard (Node 22)
cd web/dashboard
npm ci && npm run gen:api && npm run typecheck && npm run lint && npm test && npm run build
```

- Database tests need a Postgres 16 whose user can create databases and roles:
  `AUREVIA_TEST_DATABASE_URL=postgresql://USER:PW@HOST:5432/postgres` and
  `AUREVIA_REQUIRE_DB_TESTS=1`. Without them DB tests are skipped locally; CI sets them and
  has its own Postgres, so **CI is the reliable check when no database is available**.
- After changing an API response, regenerate `web/dashboard/openapi.json` and
  `src/lib/api-schema.d.ts`; CI fails on drift.
- A sales-conversation evaluation exists: `python -m aurevia.evaluation.run` (real model, needs
  a key and database; uses a throwaway tenant). A latency benchmark: `backend/scripts/voice_benchmark.py`.

## Status (see `docs/` for detail)

- All nine planned phases are built and merged. Voice quality work: spoken-style prompt,
  Meera (female, default) and Dev (male) voices, speak-first with a background bookkeeping
  pass, Hindi/Hinglish TTS switching, visible voice-failure notices with safe audio retry.
- **The voice is chosen but not accepted.** Acceptance needs the human microphone test in
  `docs/06-testing/voice-manual-acceptance.md`. Real audio recovery after a Cartesia failure is
  unverified (credits were exhausted).
- **Not built / blocked:** a real calendar integration (bookings are internal records),
  hosting and a public IP, the Exotel phone trunk (untested), counsel's review of the India
  policy, the sales-learning pipeline (design only: `docs/07-learning/`), a paid model key.
- Latency target (p50 < 1 s end of speech to first audio) is **not met**; measured text-path
  first word is about 2.6 to 3 s on a free key. Re-baseline before treating it as a target.
- The master plan the user is following: reliable voice, natural conversation, accurate
  memory, expert-call learning, model experiments, compliant pilot. Work one phase at a time.

## Environment notes

- Secrets live only in `backend/.env` locally, or in the cloud environment's secret settings.
  Variable names are in `backend/.env.example`. See `docs/05-operations/cloud-setup.md`.
- Locally the stack runs with `docker compose --profile voice up -d` from `backend/`
  (API 8000, dashboard 3002, LiveKit 7880). The user's Docker Desktop stops often; restart it.
- A cloud sandbox may not have Docker or a microphone. Check what is available at the start of
  a session and say so; do not pretend a real-audio test ran.
