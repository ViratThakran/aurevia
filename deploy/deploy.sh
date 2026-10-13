#!/usr/bin/env bash
# Deploy, roll back or inspect the hosted stack. Run on the server, from anywhere.
#   deploy/deploy.sh deploy [--no-pull] [--skip-backup] [--smoke]
#   deploy/deploy.sh rollback [TAG]      (default: the release before the current one)
#   deploy/deploy.sh status
# deploy: check env -> back up the database -> git pull -> pull pinned images -> build ->
# start Postgres/Redis -> run migrations ONCE -> start everything and wait until healthy.
# Rollback switches the running containers back to images of an earlier release. It does not
# undo database migrations: see docs/05-operations/hosting-runbook.md.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVICES=(api dashboard voice-worker)

usage() { sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

current_tag() { tail -n1 "$RELEASES_FILE" 2>/dev/null | cut -d' ' -f1; }
previous_tag() { tail -n2 "$RELEASES_FILE" 2>/dev/null | head -n1 | cut -d' ' -f1; }
record_release() { echo "$1 $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$RELEASES_FILE"; }

cmd_deploy() {
  local pull=1 backup=1 smoke=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --no-pull) pull=0 ;;
      --skip-backup) backup=0 ;;
      --smoke) smoke=1 ;;
      *) usage 1 ;;
    esac
    shift
  done

  check_env
  compose config -q || die "docker-compose.prod.yml does not validate with this env file"
  for name in DEEPGRAM_API_KEY CARTESIA_API_KEY; do
    [ -n "$(env_get "$name")" ] || log "WARNING: $name is empty; the voice worker will not start until it is set (everything else works)"
  done

  if [ "$backup" -eq 1 ] && [ -n "$(compose ps -q postgres)" ]; then
    log "backing up the database before changing anything"
    "$DEPLOY_DIR/backup.sh" || die "backup failed; nothing was changed (use --skip-backup only if you accept that)"
  else
    log "no running database (first deploy) or --skip-backup: skipping the backup"
  fi

  if [ "$pull" -eq 1 ]; then
    git -C "$REPO_ROOT" diff --quiet HEAD || die "the server's checkout has local changes; commit or discard them first"
    log "updating the code (fast-forward only)"
    git -C "$REPO_ROOT" pull --ff-only
  fi

  AUREVIA_TAG="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
  export AUREVIA_TAG
  log "release $AUREVIA_TAG (previous: $(current_tag || true))"

  log "fetching pinned third-party images not yet on this server"
  compose pull --ignore-buildable --policy missing
  log "building api, dashboard, voice-worker"
  compose build

  log "starting Postgres and Redis"
  compose up -d --wait --wait-timeout 120 postgres redis
  log "running database migrations (once)"
  compose run --rm migrate

  log "starting the stack"
  if ! compose up -d --remove-orphans --wait --wait-timeout 240; then
    compose ps || true
    die "the stack did not become healthy. Inspect: deploy/deploy.sh status ; docker compose logs. To go back: deploy/deploy.sh rollback"
  fi

  record_release "$AUREVIA_TAG"
  log "deployed $AUREVIA_TAG"
  if [ "$smoke" -eq 1 ]; then
    "$DEPLOY_DIR/smoke-test.sh"
  else
    log "next: deploy/smoke-test.sh"
  fi
}

cmd_rollback() {
  check_env
  local target="${1:-$(previous_tag)}" svc
  [ -n "$target" ] || die "no earlier release recorded in $RELEASES_FILE; pass a tag explicitly"
  [ "$target" != "$(current_tag)" ] || die "release $target is already the current one"
  for svc in "${SERVICES[@]}"; do
    docker image inspect "aurevia/$svc:$target" > /dev/null 2>&1 \
      || die "image aurevia/$svc:$target is not on this server (pruned?); redeploy that commit instead"
  done
  AUREVIA_TAG="$target"
  export AUREVIA_TAG
  log "rolling back to release $target (no rebuild)"
  compose up -d --remove-orphans --wait --wait-timeout 240 || die "rollback did not become healthy; see: deploy/deploy.sh status"
  record_release "$target"
  log "now running $target. Database migrations were NOT undone; if the old code cannot use the new schema, restore a backup (runbook)."
}

cmd_status() {
  log "current release: $(current_tag || echo none)"
  AUREVIA_TAG="$(current_tag || true)"
  export AUREVIA_TAG="${AUREVIA_TAG:-dev}"  # only used to resolve image names in the compose file
  compose ps
}

[ $# -ge 1 ] || usage 1
action="$1"; shift
case "$action" in
  deploy) cmd_deploy "$@" ;;
  rollback) cmd_rollback "$@" ;;
  status) cmd_status ;;
  -h|--help|help) usage 0 ;;
  *) usage 1 ;;
esac
