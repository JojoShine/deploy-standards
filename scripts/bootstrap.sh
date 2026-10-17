#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/lib.sh"
[[ $# == 1 ]] || fail 'Usage: bootstrap.sh PROJECT_ROOT'
init "$1"
TARGET=$(helper link "$ROOT" current) || fail 'Invalid current release link.'
[[ -n "$TARGET" ]] || fail 'Deploy a healthy release before bootstrap.'
validate_release "$TARGET"
pull_images "$TARGET"
helper bootstrap "$ROOT" "$TARGET" tooling run --rm --no-deps migrate /app/bin/bootstrap || fail 'Bootstrap failed.'
printf '%s\n' 'Bootstrap completed. The application command owns idempotence.'
