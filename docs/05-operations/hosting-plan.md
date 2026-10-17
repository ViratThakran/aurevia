# Hosting plan (Option A: one server, Docker Compose, HTTPS)

**Status: decided (2026-10-13). Stage 1 (packaging) is written, see `hosting-runbook.md` and `../../deploy/`; it has not run on a real server. Stages 2 onward wait for the user's decisions.** The user chose Option A. Provider,
domain and budget are still open (section 7). This plan covers staging first and then the
pilot; it does not cover scale. Related: `cloud-setup.md`, `deployment-and-environments.md`,
`disaster-recovery.md`, `pilot-runbook.md`, `../02-voice/telephony.md`.

## 1. What has to be hosted

| Piece | Today (local development) | Needs on a real host |
|---|---|---|
| API (FastAPI) | `--reload`, source mounted from disk | Plain server, restart policy, health check |
| Postgres 16 | Docker volume, port exposed on localhost | Private network only, backups, restore tested |
| Redis | Used by LiveKit and the SIP service | Private network only |
| LiveKit media server | Dev mode, keys `devkey`/`secret`, advertises 127.0.0.1 | Real keys, public IP, open media ports, `wss://` |
| Voice worker | Shares LiveKit's network, keys in env | Same, with the real LiveKit keys |
| Dashboard (Next.js) | API URL baked in as `http://localhost:8000` | Built with the public API URL (build-time argument) |
| SIP bridge (Exotel) | Starts, but is not reachable | Public IP, ports 5060 and 10000-10100/udp (stage 5) |
| HTTPS front door | None | Required: microphone access and the `Secure` session cookie both need HTTPS |

The current `backend/docker-compose.yml` is a **development** file and must not be exposed as is.

## 2. Options considered

| Option | What it is | Good | Bad |
|---|---|---|---|
| **A. One VM + Docker Compose + Caddy (chosen)** | Everything on one server in an India region, HTTPS by Caddy | Cheapest, matches what exists, easiest to debug | Single point of failure; manual updates |
| B. Split | VM for LiveKit/worker, managed Postgres, PaaS for API and dashboard | Better durability | More parts and cost |
| C. LiveKit Cloud for media | Own API/worker, managed LiveKit and SIP | Removes UDP, public IP and NAT operations | Per-minute cost; a dependency. Check regions and pricing first |
| D. Kubernetes | | Scales | Overkill for a pilot |

Revisit C if UDP/NAT problems or the operating burden of Option A become painful. The code
uses the standard LiveKit protocol, so it is a configuration change plus pricing, not a rewrite.

## 3. Design

- **Region:** India (Mumbai or Bengaluru): closest to users and Exotel, and simplest for
  data-residency questions (not legal advice; counsel decides).
  - **To measure, not assume:** Deepgram, Cartesia and Gemini are probably served from
    outside India, which may add 0.2 to 0.5 s per turn. Benchmark the same test from this
    region and from one nearer the providers (`backend/scripts/voice_benchmark.py`,
    `python -m aurevia_voice.simulate`) before committing.
- **Size to start:** about 4 vCPU, 8 GB RAM and 40+ GB disk (the worker image is about 2 GB,
  the API about 1.1 GB). This is an estimate; measure during a test call and adjust.
- **Hostnames:** `app.<domain>` (dashboard), `api.<domain>`, `rtc.<domain>` (LiveKit `wss://`).
  Certificates by Caddy.
- **Firewall:** 22 (your IP only), 80, 443, 7881/tcp and 7882/udp (media). Postgres and Redis
  are never public. SIP ports (5060, 10000-10100/udp) only when telephony starts, ideally
  restricted to the carrier's addresses.
- **Secrets:** a root-only env file on the server or the provider's secret manager.
  Separate keys for staging and production. New LiveKit keys; never `devkey`/`secret`.
- **Deploys:** scripted and manual at first. Pin image versions (not `latest`). Every deploy
  has a rollback step. Migrations run once per deploy.
- **Cost:** a server of this size is roughly $25 to $80 per month depending on the provider;
  provider usage (Cartesia, Deepgram, Gemini, Exotel) will dominate. Verify on each provider's
  pricing page and set spend caps before testing.

## 4. Stages

### Stage 0: decisions (user)
Provider and account, region, domain, monthly budget. See section 7.

### Stage 1: production packaging (code, one PR; no cloud account needed) — written, awaiting review
- `docker-compose.prod.yml`: no `--reload`, no bind mounts, `restart: unless-stopped`, health
  checks, no published Postgres/Redis ports, pinned image tags.
- LiveKit production config: real keys, `use_external_ip`, TCP 7881 and UDP 7882, webhook key
  matching the API, same keys for the worker. TURN deferred.
- Caddy: `app.`, `api.` and `rtc.` hostnames with TLS; WebSocket proxying for LiveKit.
- Dashboard built with `NEXT_PUBLIC_API_URL=https://api.<domain>`;
  `AUREVIA_API_URL=http://api:8000` for its server-side calls.
- API settings for a deployed environment: `AUREVIA_ENVIRONMENT=staging`, JWT secret, CORS
  origin, `AUREVIA_TRUST_PROXY_HEADERS=true` behind Caddy, public LiveKit URL.
- `deploy.sh` (pull, migrate, restart, rollback), a smoke-test script, a backup job to object
  storage, log rotation, and a runbook.
- **Done when:** CI passes and the smoke test passes against a production-style run on a
  development machine.

### Stage 2: provision (user, guided)
Create the server, firewall and DNS; install Docker; add secrets; run the first deploy.
**Done when:** the health endpoint and the dashboard login work over HTTPS.

### Stage 3: prove it works (user and developer)
- Sign up, configure the agent, and make a Test Call with a microphone using
  `docs/06-testing/voice-manual-acceptance.md`.
- Repeat the voice-failure and retry check with working Cartesia credits.
- Record a latency baseline from this host.
**Done when:** the acceptance sheet has a recorded result.

### Stage 4: harden
Restore from a backup and check the data, uptime and disk alerts, provider spend caps,
SSH keys only, review logs for secrets (`disaster-recovery.md`, `observability-and-operations.md`).

### Stage 5: telephony in test mode
Exotel trunk, SIP ports and carrier allow-list, then calls only to the user's own registered
numbers, to hear real phone audio. Live calling stays blocked until counsel signs off.

### Stage 6: pilot gate
Everything in `pilot-runbook.md`.

## 5. Risks

- UDP and NAT: some networks block media; TURN may be needed later.
- Single server: an outage stops all calls. Acceptable for staging and a small pilot.
- Provider concurrency limits: Cartesia and Deepgram cap parallel connections by plan.
- Cost runaway: spend caps at every provider before any testing.
- Secrets: keys previously pasted into chat must be rotated; nothing is entered in chat.
- Compliance: hosting does not unblock live calling; counsel's review of the India policy
  pack is separate and required.

## 6. Out of scope for this plan

High availability, autoscaling, multi-region, Kubernetes, a managed database, and a
provider migration without a controlled comparison.

## 7. Open decisions

| # | Decision | Needed by | Note |
|---|---|---|---|
| 1 | Cloud provider and account owner | Stage 2 | Suggested: DigitalOcean or AWS Lightsail in Mumbai or Bengaluru for simplicity |
| 2 | Domain name | Stage 2 | Needed for HTTPS |
| 3 | Monthly budget (server and provider usage) | Stage 2 | |
| 4 | Cartesia credits and a paid model key | Stage 3 | Without them there is no real voice |
| 5 | Who rotates the exposed keys | Before Stage 2 | |
