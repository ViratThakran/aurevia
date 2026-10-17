#!/usr/bin/env bash
# Shared helpers for the deploy scripts. Source it; do not run it.
# shellcheck disable=SC2034  # variables are used by the scripts that source this file
# Secret values are never printed: the checks below report only variable NAMES.

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"
ENV_FILE="${AUREVIA_ENV_FILE:-$DEPLOY_DIR/.env}"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
RELEASES_FILE="$DEPLOY_DIR/.releases"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# env_get NAME: the value from the env file (last assignment wins; empty if absent), without sourcing it.
env_get() {
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n1 | cut -d= -f2- | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# Fails with a plain message if the env file is missing, loose, incomplete or still on dev keys.
check_env() {
  [ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE (copy deploy/production.env.example to deploy/.env and fill it in)"
  local mode
  mode=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%Lp' "$ENV_FILE")
  case "$mode" in
    600|400) ;;
    *) die "$ENV_FILE has permissions $mode; run: chmod 600 $ENV_FILE" ;;
  esac

  local missing=() name
  for name in AUREVIA_DOMAIN ACME_EMAIL AUREVIA_ENVIRONMENT POSTGRES_USER POSTGRES_PASSWORD \
      POSTGRES_DB AUREVIA_APP_DB_PASSWORD AUREVIA_JWT_SECRET LIVEKIT_API_KEY LIVEKIT_API_SECRET; do
    [ -n "$(env_get "$name")" ] || missing+=("$name")
  done
  if [ -z "$(env_get AUREVIA_GEMINI_API_KEY)" ] && [ -z "$(env_get AUREVIA_ANTHROPIC_API_KEY)" ]; then
    missing+=("AUREVIA_GEMINI_API_KEY or AUREVIA_ANTHROPIC_API_KEY")
  fi
  [ ${#missing[@]} -eq 0 ] || die "not set in $ENV_FILE: ${missing[*]}"

  case "$(env_get AUREVIA_ENVIRONMENT)" in
    staging|production) ;;
    *) die "AUREVIA_ENVIRONMENT must be staging or production" ;;
  esac
  case "$(env_get AUREVIA_DOMAIN)" in
    *://*|*/*|app.*|api.*|rtc.*) die "AUREVIA_DOMAIN must be the bare domain (example.com), without https:// or app./api./rtc." ;;
  esac
  case "$(env_get LIVEKIT_API_KEY)" in
    devkey) die "LIVEKIT_API_KEY is the development key; generate a new one" ;;
  esac
  case "$(env_get LIVEKIT_API_SECRET)" in
    secret) die "LIVEKIT_API_SECRET is the development secret; generate a new one" ;;
  esac
  [ "$(env_get AUREVIA_JWT_SECRET | wc -c)" -gt 32 ] || die "AUREVIA_JWT_SECRET must be at least 32 characters (openssl rand -hex 32)"
  [ "$(env_get LIVEKIT_API_SECRET | wc -c)" -gt 32 ] || die "LIVEKIT_API_SECRET must be at least 32 characters"
}
