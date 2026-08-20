#!/usr/bin/env bash
# docker-entrypoint.sh -- checks CLAUDE_CODE_OAUTH_TOKEN is set and non-empty before running a
# loop entrypoint, then execs the given command. Presence-only check: never prints, logs, or
# echoes the value itself, on failure or otherwise -- see
# openspec/changes/run-the-factory-in-a-container/design.md, D2.
#
# Scoped to the two loop entrypoints, not every command: `claude --version`, `python -c "import
# yosefactory"`, and similar diagnostics (task 3.6/5.1) need to work inside the built image without
# a token -- they never call claude. yosefactory-loop / yosefactory-loop-scheduled are the ones
# that would fail three layers down, inside the executor, on a missing token if this did not check.
set -euo pipefail

# HOME is not set by `USER factory` alone (Dockerfile, run-the-loop-inside-the-container) -- derive
# it from whatever user is actually running this process rather than hardcoding the image's build-
# time uid, so a future uid change has one place to edit (the Dockerfile's `useradd`), not two.
export HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"

case "${1:-}" in
    yosefactory-loop | yosefactory-loop-scheduled)
        if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
            echo "docker-entrypoint.sh: CLAUDE_CODE_OAUTH_TOKEN is not set -- claude cannot authenticate." >&2
            echo "docker-entrypoint.sh: supply it via a local, gitignored .env (see .env.example)." >&2
            echo "docker-entrypoint.sh: generate one with 'claude setup-token' (requires a Claude subscription)." >&2
            exit 1
        fi
        ;;
esac

exec "$@"
