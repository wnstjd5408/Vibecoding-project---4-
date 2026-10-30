#!/usr/bin/env bash
# Supabase CLI 2.121.0 + config.toml major_version=17 image.
# Keep this pin in sync when upgrading the CLI. Never print dump logs or URLs.
set -euo pipefail
umask 077
python3 backend/scripts/diagnose_backup.py
out="${RUNNER_TEMP:?}/backup/db"
mkdir -p "$out"
image="public.ecr.aws/supabase/postgres:17.11.0.004"
ready=0
for source in "$image" "ghcr.io/supabase/postgres:17.11.0.004"; do
  if docker pull "$source" > "${RUNNER_TEMP}/backup-image.log" 2>&1; then
    if [ "$source" != "$image" ]; then
      docker tag "$source" "$image"
    fi
    ready=1
    break
  fi
  python3 backend/scripts/diagnose_backup.py --log "${RUNNER_TEMP}/backup-image.log"
done
if [ "$ready" != 1 ]; then
  echo '::error::Backup image unavailable from both official registries'
  exit 1
fi
# Ensure the CLI uses the exact image prepared above, without stale local pins.
mkdir -p supabase/.temp
printf '%s\n' '17.11.0.004' > supabase/.temp/postgres-version
export SUPABASE_INTERNAL_IMAGE_REGISTRY=public.ecr.aws
export SUPABASE_USE_SLIM_IMAGES=false
for name in roles schema data; do
  args=()
  case "$name" in
    roles) args=(--role-only) ;;
    data) args=(--use-copy --data-only) ;;
  esac
  if ! npx --no-install supabase db dump --db-url "$SUPABASE_DB_URL" \
    -f "$out/$name.sql" "${args[@]}" > "${RUNNER_TEMP}/dump-${name}.log" 2>&1; then
    python3 backend/scripts/diagnose_backup.py --log "${RUNNER_TEMP}/dump-${name}.log"
    echo "::error::${name} dump failed; private log withheld"
    exit 1
  fi
done
if ! grep -q '^COPY ' "$out/data.sql"; then
  echo '::error::Data dump contains no COPY statement'
  exit 1
fi
