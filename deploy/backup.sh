#!/usr/bin/env bash
# Back up the hosted database and copy the dump to S3-compatible object storage.
#   deploy/backup.sh
# Uses the existing backend/scripts/backup.sh for the dump. The upload runs the pinned AWS CLI
# image (works with any S3-compatible service via BACKUP_S3_ENDPOINT); the keys are passed to it
# by name, never on a command line. Exit status is non-zero if the dump or the upload fails,
# and local copies are pruned only after a successful upload.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
check_env

AWS_CLI_IMAGE="amazon/aws-cli:2.37.13"
dir="${BACKUP_DIR:-$DEPLOY_DIR/backups}"
mkdir -p "$dir"

out=$(AUREVIA_COMPOSE_FILE="$COMPOSE_FILE" AUREVIA_ENV_FILE="$ENV_FILE" BACKUP_DIR="$dir" \
  bash "$REPO_ROOT/backend/scripts/backup.sh")
echo "$out"
file="$dir/$(basename "$(echo "$out" | sed -n 's/^backup written: \([^ ]*\) .*/\1/p')")"
[ -s "$file" ] || die "backup file is empty: $file"

# A dump that cannot be listed is not a backup.
compose exec -T postgres pg_restore --list < "$file" > /dev/null || die "backup is not a valid dump: $file"
log "backup verified readable: $(basename "$file")"

bucket="$(env_get BACKUP_S3_BUCKET)"
if [ -z "$bucket" ]; then
  log "WARNING: BACKUP_S3_BUCKET is not set; the backup stays on this server only"
else
  endpoint="$(env_get BACKUP_S3_ENDPOINT)"
  region="$(env_get BACKUP_S3_REGION)"
  key="aurevia/$(env_get AUREVIA_ENVIRONMENT)/$(basename "$file")"
  args=(s3 cp "/backups/$(basename "$file")" "s3://$bucket/$key" --only-show-errors)
  [ -z "$endpoint" ] || args+=(--endpoint-url "$endpoint")
  AWS_ACCESS_KEY_ID="$(env_get BACKUP_S3_ACCESS_KEY_ID)" \
  AWS_SECRET_ACCESS_KEY="$(env_get BACKUP_S3_SECRET_ACCESS_KEY)" \
  AWS_DEFAULT_REGION="${region:-us-east-1}" \
    docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION \
      -v "$dir:/backups:ro" "$AWS_CLI_IMAGE" "${args[@]}" \
    || die "upload to object storage failed; local copy kept: $file"
  log "uploaded to s3://$bucket/$key"
fi

keep="$(env_get BACKUP_LOCAL_KEEP_DAYS)"
find "$dir" -name 'aurevia-*.dump' -mtime "+${keep:-7}" -delete
