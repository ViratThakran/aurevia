# Cloud setup: developing in the cloud, and hosting Aurevia

Two separate things, both needed eventually:

1. **Working on Aurevia from a cloud Claude session** (code, tests, pull requests).
2. **Hosting Aurevia** somewhere with a public address, so a person can use it with a
   microphone and, later, so phone calls can reach it.

A cloud session works from a clone of the GitHub repository. It cannot see this machine's
files, Docker containers, `.env`, microphone or browser. Everything it needs must be in the
repo or in the cloud environment's settings.

## 1. What a cloud session can and cannot do

| Task | Cloud session |
|---|---|
| Read and change code, open pull requests | Yes |
| Lint, type-check, build the dashboard, run worker tests | Yes (Python 3.12 + uv, Node 22) |
| Backend database tests | Only with a Postgres 16 in the sandbox; otherwise rely on **CI**, which has its own Postgres |
| `docker compose` stack | Check first: a sandbox often has no Docker daemon |
| Real model, speech or call tests | Only if the keys are set as secrets **and** the network allows those hosts |
| Human microphone test | **No.** It needs the app running at an address you can open, with HTTPS |

CI (`.github/workflows/ci.yml`) is the reference check: backend (with Postgres), voice worker,
dashboard. Use it whenever a local check cannot run.

## 2. First thing in a new cloud session

Run these and report the answers before changing anything:

```bash
python3 --version; uv --version; node --version; npm --version
docker info >/dev/null 2>&1 && echo "docker: yes" || echo "docker: no"
pg_isready 2>/dev/null || echo "postgres: not running"
git log --oneline -3; git status --short
```

Then read `CLAUDE.md` and `docs/AGENTS.md`.

## 3. Secrets and configuration

Never commit these. Enter them in the cloud environment's secret/variable settings (or the
host's secret store). Names only; the template is `backend/.env.example`.

| Variable | Used by | Notes |
|---|---|---|
| `AUREVIA_JWT_SECRET` | api | `openssl rand -hex 32`; mandatory in staging/production |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | postgres, migrations | schema owner |
| `AUREVIA_APP_DB_PASSWORD` | api | password of the `aurevia_app` role (no BYPASSRLS) |
| `AUREVIA_GEMINI_API_KEY` | api only | or `AUREVIA_ANTHROPIC_API_KEY` with `AUREVIA_AI_PROVIDER=anthropic` |
| `AUREVIA_LLM_MODEL`, `AUREVIA_LLM_FALLBACK_MODELS` | api | e.g. `gemini-3.5-flash-lite` with `["gemini-3.5-flash"]` |
| `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` | voice worker only | never the API, never the browser |
| `AUREVIA_LIVEKIT_API_KEY`, `AUREVIA_LIVEKIT_API_SECRET` | api, livekit, worker | **replace the dev keys** (`devkey` / `secret`) |
| `AUREVIA_LIVEKIT_URL`, `AUREVIA_LIVEKIT_PUBLIC_URL` | api | internal URL, and the `wss://` URL browsers use |
| `AUREVIA_CORS_ORIGINS` | api | the dashboard's exact `https://` origin |
| `AUREVIA_TELEPHONY_MODE` | api | leave `test`; `live` stays blocked until counsel review |
| `AUREVIA_CAMPAIGN_SCHEDULER_ENABLED` | api | leave `false` |
| `AUREVIA_ENVIRONMENT` | api | `staging` or `production` when hosted (enforces the secret checks) |

**Rotate before moving:** any key that was ever pasted into a chat or a log (the Gemini key
and any Cartesia/Deepgram key shared that way). Create new keys, set them as secrets, and
revoke the old ones at the provider.

## 4. Hosting Aurevia (not done yet)

The chosen approach and the stage-by-stage plan are in `hosting-plan.md`.

The repo has Dockerfiles and a compose file but **no deployment setup**: no staging, no
domain, no TLS, no managed database. The simplest first step is one small virtual machine
running the existing compose file behind HTTPS.

Requirements that are easy to miss:

- **HTTPS is mandatory.** Browsers only allow the microphone on secure pages, and the
  dashboard's session cookie is `Secure` in production. LiveKit must be reached over `wss://`.
- **Open ports for LiveKit:** TCP 7880/7881 and UDP 7882 (media). For phone calls also SIP
  (UDP/TCP 5060) and the RTP range (10000-10100/udp). Bind these to the public interface;
  the local compose file binds them to 127.0.0.1.
- **`NEXT_PUBLIC_API_URL` is baked into the dashboard at build time** (a Docker build
  argument). Build the dashboard image with the public API URL, not `http://localhost:8000`.
  The dashboard server uses `AUREVIA_API_URL` for its own server-side calls.
- **Same-origin check.** The dashboard's session routes compare the request's `Origin` with
  its `Host`; serve the dashboard from one hostname and put the API's CORS origin to match.
- **Reverse proxy:** set `AUREVIA_TRUST_PROXY_HEADERS=true` only behind a proxy you control.
- **Database:** the API container runs `alembic upgrade head` as the schema owner on start,
  then serves as `aurevia_app`. Use `backend/scripts/backup.sh` and `restore_check.sh`; test a
  restore before relying on backups (`docs/05-operations/disaster-recovery.md`).
- **Provider limits:** set spend limits at the model, Cartesia and Deepgram dashboards.

## 5. What is still open (in order)

1. Cartesia credits, a paid model key, and rotated keys.
2. A hosted instance with HTTPS, so the microphone test
   (`docs/06-testing/voice-manual-acceptance.md`) can be run by a person.
3. Repeat one Test Call with working audio to confirm recovery after a voice failure.
4. Real phone audio: Exotel trunk, public IP, SIP ports.
5. Counsel review of the India policy pack
   (`docs/04-compliance-security/counsel-review-pack.md`) before any live call.
6. A real calendar integration, so "booked" means booked.
7. The pilot (`docs/05-operations/pilot-runbook.md`).
