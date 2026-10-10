#!/usr/bin/env bash
# Back up the Aurevia database (custom-format pg_dump) into backend/backups/.
#   scripts/backup.sh            -> backups/aurevia-YYYYmmdd-HHMMSS.dump
# Reads only POSTGRES_USER and POSTGRES_DB from .env; no secret is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
user=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)
db=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)
mkdir -p backups
file="backups/aurevia-$(date -u +%Y%m%d-%H%M%S).dump"
docker compose exec -T postgres pg_dump -U "$user" -d "$db" --format=custom --no-owner > "$file"
echo "backup written: $file ($(wc -c < "$file") bytes)"
