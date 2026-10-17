#!/usr/bin/env bash
# Shared server-side operations. Never source production environment files.
set -Eeuo pipefail
umask 077
LIB_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

fail() { printf '%s\n' "$*" >&2; exit 1; }
helper() { python3 "$LIB_DIR/lib.py" "$@"; }

init() {
    [[ "$1" = /* && -d "$1" ]] || fail 'Project root must be an existing absolute directory.'
    ROOT=$(cd -- "$1" && pwd -P)
    for tool in python3 docker flock curl; do
        command -v "$tool" >/dev/null || fail "Required tool missing: $tool"
    done
    helper config "$ROOT" >/dev/null || fail 'Invalid production environment.'
    [[ ! -L "$ROOT/.deploy.lock" ]] || fail 'Unsafe deployment lock.'
    exec 9>"$ROOT/.deploy.lock"
    flock -x 9
    docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is required.'
    docker info >/dev/null 2>&1 || fail 'Docker daemon is unavailable.'
    for name in backups logs; do
        [[ ! -L "$ROOT/$name" ]] || fail 'Unsafe project directory.'
        mkdir -p -- "$ROOT/$name"
    done
}

validate_release() {
    helper validate "$ROOT" "$1" || fail 'Release bundle validation failed.'
    helper compose-check "$ROOT" "$1" || fail 'Unsafe production Compose configuration.'
}

compose() { helper compose "$ROOT" "$1" "$2" "${@:3}"; }

pull_images() {
    local release=$1 ref platform
    compose "$release" runtime pull app migrate || fail 'Image pull failed.'
    while IFS= read -r ref; do
        platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$ref" 2>/dev/null) || fail 'Cannot inspect image.'
        [[ "$platform" == linux/amd64 ]] || fail 'Images must target linux/amd64.'
    done < <(helper images "$ROOT" "$release")
}

start_app() {
    compose "$1" runtime up -d --no-build --pull never --force-recreate --wait --wait-timeout "${HEALTH_TIMEOUT:-120}" app
}

load_timeout() {
    local key value
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [[ "$key" == HEALTH_TIMEOUT ]]; then HEALTH_TIMEOUT=$value; fi
    done < <(helper config "$ROOT")
}

restore_app() {
    if [[ -n "$OLD" ]]; then
        printf '%s\n' 'Restoring the previously active app.' >&2
        if start_app "$OLD" && helper health "$ROOT"; then
            printf '%s\n' 'Previous app restored; database changes remain in place.' >&2
        else
            printf '%s\n' 'Previous app recovery failed; manual intervention is required.' >&2
        fi
    else
        compose "$TARGET" runtime stop app || true
    fi
}
