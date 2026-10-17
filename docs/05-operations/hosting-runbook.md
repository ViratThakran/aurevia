# Hosting runbook (Stage 1 packaging; used from Stage 2)

Plain-language steps for putting Aurevia on one server. The design is in `hosting-plan.md`
(Option A: one server, Docker Compose, Caddy, India region). Everything here is in `deploy/`.

**Status:** the packaging is written and checked on a development machine only. It has **not**
been run on a real server, with real DNS, real certificates or real audio (see section 9).

## 1. What is in `deploy/`

| File | What it does |
|---|---|
| `docker-compose.prod.yml` | The hosted stack: Caddy, dashboard, API, voice worker, LiveKit, Redis, Postgres (+ optional SIP, off by default) |
| `production.env.example` | The list of settings, **names only**. Copy to `deploy/.env` on the server |
| `deploy.sh` | `deploy`, `rollback`, `status` |
| `smoke-test.sh` | Checks health, login and the proxy after a deploy |
| `backup.sh` | Database backup, verified, uploaded to S3-compatible storage |
| `cron/` | Nightly backup schedule and log rotation, to copy onto the server |

What is published to the internet: ports 80/443 (Caddy), 7881/tcp and 7882/udp (call media).
Postgres and Redis have no published ports. The telephony mode (`test`) and the campaign dialer
(`off`) are fixed in the compose file and are not read from the env file.

## 2. What you need first (Stage 0 decisions)

A cloud account and server (about 4 vCPU, 8 GB RAM, 40+ GB disk, Ubuntu LTS, an India region),
a domain, a bucket on an S3-compatible service for backups, and **new** keys (the model key,
Deepgram, Cartesia). Keys that were ever pasted into chat must be rotated first.
**Never paste a key into a chat: put it only in `deploy/.env` on the server.**

## 3. One-time server setup (Stage 2)

1. **DNS.** Create three `A` records pointing to the server's public IP:
   `app.<domain>`, `api.<domain>`, `rtc.<domain>`. Wait until they resolve (`nslookup app.<domain>`).
2. **Firewall** (the provider's firewall, not only the server's): allow 22 from **your IP only**,
   80/tcp, 443/tcp, 443/udp, 7881/tcp, 7882/udp. Allow nothing else. (SIP ports come in Stage 5.)
3. **Install Docker** (Docker's own instructions for Ubuntu, including the compose plugin), then:
   ```bash
   sudo git clone https://github.com/ViratThakran/aurevia /opt/aurevia
   cd /opt/aurevia
   cp deploy/production.env.example deploy/.env
   chmod 600 deploy/.env
   ```
4. **Fill in `deploy/.env`** with an editor (`nano deploy/.env`). Make secrets with
   `openssl rand -hex 32` (database passwords: `openssl rand -hex 24`). Use a **new LiveKit key
   pair** (never `devkey`/`secret`). Set `BACKUP_S3_*` for backups. `deploy.sh` refuses to run if
   something required is missing or still a development key; it prints names, never values.
5. **Install backups and log rotation:**
   ```bash
   sudo cp deploy/cron/aurevia-backup.cron /etc/cron.d/aurevia-backup
   sudo cp deploy/cron/aurevia-logrotate.conf /etc/logrotate.d/aurevia
   ```
6. In the bucket, add a lifecycle rule that expires old backups (for example after 30 days)
   and keep the bucket private. Backups contain personal data.

## 4. Deploy

```bash
cd /opt/aurevia
deploy/deploy.sh deploy --smoke
```

It checks the settings, backs up the database (skipped on the first deploy), pulls the code,
builds, runs the database migrations **once**, starts everything, and waits until the health
checks pass. The first run takes several minutes (images are large) and Caddy needs a minute to
obtain certificates. `--smoke` then runs the smoke test.

Useful options: `--no-pull` (deploy what is already checked out), `--skip-backup`.

## 5. Check it works

```bash
deploy/smoke-test.sh      # signs up a throwaway account, logs in, checks the proxy and CORS
deploy/deploy.sh status
```

Then open `https://app.<domain>` and sign in. The smoke test leaves one "Smoke Test" tenant per
run in the database (staging only; harmless).

## 6. Update

Same command as a deploy: `deploy/deploy.sh deploy --smoke`. Every deploy takes a backup first
and records the release (the git commit) in `deploy/.releases`.

## 7. Roll back

```bash
deploy/deploy.sh rollback          # to the previous release, no rebuild
deploy/deploy.sh rollback <tag>    # to a specific recorded release
```

This switches the containers back to the images of that release. **It does not undo database
migrations.** Most migrations are additive and old code keeps working. If the old code cannot
work with the new schema, restore the backup taken at the start of that deploy:
stop the stack, restore the dump (`disaster-recovery.md`), then roll back. Images are kept on the
server until you run `docker image prune`; do not prune right after a deploy.

## 8. Backups and restore check

- `deploy/backup.sh` writes `deploy/backups/aurevia-*.dump`, confirms the dump is readable,
  uploads it to `s3://<bucket>/aurevia/<environment>/`, and removes local copies older than
  `BACKUP_LOCAL_KEEP_DAYS`. The nightly schedule is in `deploy/cron/aurevia-backup.cron`; output is
  in `/var/log/aurevia-backup.log`. A failed upload makes the job fail loudly and keeps the file.
- Prove a restore (Stage 4), without touching live data:
  ```bash
  cd /opt/aurevia
  AUREVIA_COMPOSE_FILE=$PWD/deploy/docker-compose.prod.yml AUREVIA_ENV_FILE=$PWD/deploy/.env \
    BACKUP_DIR=$PWD/deploy/backups bash backend/scripts/restore_check.sh
  ```
- Container logs rotate by themselves (10 MB x 5 per container). `docker compose logs` never
  contains keys by design; if you see a secret in a log, rotate it.

## 9. Platform operator commands

The API container does not hold the database owner password. Run operator tools through the
migration job, which does:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.prod.yml run --rm migrate \
  python -m aurevia.platform.operator --help
```

## 10. What was verified, and what was not

Verified on a development machine (Docker, no cloud, 2026-10-13):
- The compose file validates; the Caddyfile validates with Caddy itself; the scripts pass `shellcheck`.
- A **production-style run** with the domain `localhost` (Caddy's own test certificates): all three
  images built, Postgres/Redis/API/dashboard/LiveKit/Caddy started and reported healthy, migrations
  ran once, and `smoke-test.sh` passed every step (health, dashboard, LiveKit endpoint, CORS, blocked
  private paths, signup, login, `/auth/me`, logout). Postgres has no published port.
- A second deploy took a backup first, a rollback switched back to the earlier images, and
  `restore_check.sh` restored the dump into a scratch database with identical row counts.
- The backup upload ran against a local S3-compatible stand-in (not a real bucket).

**Not verified until Stage 2/3:** DNS; real certificate issuance; the media ports reachable from the
internet; LiveKit with `use_external_ip: true` (it needs to reach a public STUN server at start; the
sandbox could not, so that one line was switched off for the local run only); real audio; the voice
worker with real Deepgram/Cartesia keys (without keys it refuses to start, by design); the SIP
service (config written, never started); the upload to a real bucket; the nightly cron job; Next.js
session cookies behind Caddy over real HTTPS.

## 11. Known limits and follow-ups

- Images are built on the server (no registry). The backend image still contains development
  dependencies; a slimmer production image is a possible later change.
- TURN is deferred. If a caller's network blocks UDP/TCP 7881-7882 the call may fail.
- One server is a single point of failure (accepted for staging and a small pilot).
- Live calling stays blocked by the compliance gate whatever the hosting state.
