#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib.sh"
[[ $# == 1 ]] || fail 'Usage: rollback.sh PROJECT_ROOT'
init "$1"
OLD=$(helper link "$ROOT" current) || fail 'Invalid current release link.'
TARGET=$(helper link "$ROOT" previous) || fail 'Invalid previous release link.'
[[ -n "$OLD" && -n "$TARGET" && "$OLD" != "$TARGET" ]] || fail 'Rollback requires distinct current and previous releases.'
load_timeout
validate_release "$OLD"
validate_release "$TARGET"
pull_images "$TARGET"
trap 'trap - EXIT INT TERM; restore_app' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! start_app "$TARGET" || ! helper health "$ROOT"; then
    fail 'Rollback target failed health checks.'
fi
helper activate "$ROOT" "$TARGET" "$OLD"
trap - EXIT INT TERM
printf '%s\n' 'Previous app activated; database unchanged.'
