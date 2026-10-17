#!/usr/bin/env bash
# Back up the Aurevia database (custom-format pg_dump) into backend/backups/.
#   scripts/backup.sh            -> backups/aurevia-YYYYmmdd-HHMMSS.dump
# Reads only POSTGRES_USER and POSTGRES_DB from .env; no secret is printed.
#
# Defaults suit the development stack. For the hosted stack deploy/backup.sh sets:
#   AUREVIA_COMPOSE_FILE / AUREVIA_ENV_FILE  which compose file and env file to use
#   BACKUP_DIR                               where to write the dump
set -euo pipefail
cd "$(dirname "$0")/.."
envfile="${AUREVIA_ENV_FILE:-.env}"
compose=(docker compose)
if [ -n "${AUREVIA_COMPOSE_FILE:-}" ]; then
  compose=(docker compose --env-file "$envfile" -f "$AUREVIA_COMPOSE_FILE")
fi
user=$(grep -E '^POSTGRES_USER=' "$envfile" | cut -d= -f2-)
db=$(grep -E '^POSTGRES_DB=' "$envfile" | cut -d= -f2-)
dir="${BACKUP_DIR:-backups}"
mkdir -p "$dir"
file="$dir/aurevia-$(date -u +%Y%m%d-%H%M%S).dump"
"${compose[@]}" exec -T postgres pg_dump -U "$user" -d "$db" --format=custom --no-owner > "$file"
echo "backup written: $file ($(wc -c < "$file") bytes)"
