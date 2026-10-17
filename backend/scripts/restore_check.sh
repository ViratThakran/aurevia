#!/usr/bin/env bash
# Prove a backup restores: load it into a scratch database next to the live one, compare the
# row count of every table, then drop the scratch database. The live database is never written.
#   scripts/restore_check.sh [backups/file.dump]   (default: the newest backup)
# For the hosted stack set AUREVIA_COMPOSE_FILE, AUREVIA_ENV_FILE and BACKUP_DIR (see backup.sh).
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
file="${1:-$(ls -t "$dir"/*.dump | head -1)}"
scratch="aurevia_restore_check"
psql() { "${compose[@]}" exec -T postgres psql -U "$user" -v ON_ERROR_STOP=1 -qAt "$@"; }

psql -d postgres -c "DROP DATABASE IF EXISTS $scratch" -c "CREATE DATABASE $scratch"
trap 'psql -d postgres -c "DROP DATABASE IF EXISTS $scratch" >/dev/null' EXIT
"${compose[@]}" exec -T postgres pg_restore -U "$user" -d "$scratch" --no-owner < "$file"

counts() {
  # Exact counts, one count(*) per table. The inner psql must not read the loop's stdin.
  psql -d "$1" -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1" |
    while read -r table; do
      echo "$table=$(psql -d "$1" -c "SELECT count(*) FROM \"$table\"" < /dev/null)"
    done
}
live=$(counts "$db")
restored=$(counts "$scratch")
if [ "$live" = "$restored" ]; then
  echo "restore OK: $(echo "$live" | wc -l) tables, identical row counts ($file)"
else
  echo "RESTORE MISMATCH ($file):"
  diff <(echo "$live") <(echo "$restored") || true
  exit 1
fi
