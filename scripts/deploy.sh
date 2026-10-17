#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib.sh"
[[ $# == 2 ]] || fail 'Usage: deploy.sh PROJECT_ROOT RELEASE_DIR'
# Validate the bundle before contacting Docker or performing any operation.
ROOT=$1
helper config "$ROOT" >/dev/null || fail 'Invalid production environment.'
helper validate "$ROOT" "$2" || fail 'Release bundle validation failed.'
init "$ROOT"
TARGET=$(cd -- "$2" && pwd -P)
OLD=$(helper link "$ROOT" current) || fail 'Invalid current release link.'
load_timeout
validate_release "$TARGET"
if [[ -n "$OLD" ]]; then validate_release "$OLD"; fi
pull_images "$TARGET"
for tool in pg_dump pg_restore; do command -v "$tool" >/dev/null || fail "Required tool missing: $tool"; done
BACKUP=$(mktemp "$ROOT/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
if ! helper backup "$ROOT" "$BACKUP"; then
    rm -f -- "$BACKUP"
    fail 'Backup or archive validation failed; app was not changed.'
fi
printf '%s\n' 'Backup verified. Running migration.'
compose "$TARGET" tooling run --rm --no-deps migrate /app/bin/migrate || fail 'Migration failed; app was not changed.'
# Once app replacement begins, every failure (including termination) recovers the
# previous app. No database restore or reverse migration is attempted.
trap 'trap - EXIT INT TERM; restore_app' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! start_app "$TARGET" || ! helper health "$ROOT"; then
    fail 'Candidate app did not become healthy.'
fi
helper activate "$ROOT" "$TARGET" "${OLD:--}"
trap - EXIT INT TERM
printf '%s\n' 'Deployment healthy; release activated.'
