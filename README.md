# Aurevia

A multi-tenant AI voice sales agent. A business sets up an agent (company, goal, voice),
adds leads, and the agent talks to prospects: qualifies them, handles objections, books
meetings, hands over to a person, and stops when asked. Every action goes through validated,
audited tools behind a compliance gate.

| Part | Folder | Stack |
|---|---|---|
| API and sales engine | `backend/` | FastAPI, Postgres 16 with row-level security, Alembic |
| Voice agent | `voice-worker/` | LiveKit agents, Deepgram (speech to text), Cartesia (text to speech) |
| Dashboard | `web/dashboard/` | Next.js 15, TypeScript, Tailwind |
| Documentation | `docs/` | Start at `docs/INDEX.md` |

Models: Gemini by default (Anthropic selectable) behind a Model Gateway with fallback.
Telephony: LiveKit SIP with Exotel as the carrier (not yet connected).

## Run it locally

```bash
cd backend
cp .env.example .env        # fill in the values (never commit .env)
docker compose --profile voice up -d --build
```

- Dashboard: http://localhost:3002
- API health: http://localhost:8000/api/v1/health/ready

The voice features need `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` and a model key
(`AUREVIA_GEMINI_API_KEY`). Details: `backend/README.md`, `voice-worker/README.md`,
`web/dashboard/README.md`.

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd voice-worker && uv run ruff check . && uv run mypy && uv run pytest
cd web/dashboard && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all three on every pull request.

## Where to read next

- `CLAUDE.md`: working agreement and current status, for AI assistants and new contributors
- `docs/AGENTS.md`: engineering rules
- `docs/00-foundation/master-brief.md`: source of truth
- `docs/02-voice/voice-runtime.md`: how a call works, and what happens when a provider fails
- `docs/05-operations/cloud-setup.md`: moving development and hosting to the cloud
- `docs/05-operations/pilot-runbook.md`: what must be true before a real pilot
- `docs/06-testing/voice-manual-acceptance.md`: the human microphone test

## Safety

Live outbound calling is blocked until a compliance reviewer approves the policy pack for the
target country. Test mode only dials numbers you have registered yourself.
