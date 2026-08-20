#!/usr/bin/env bash
# One-shot driver for openspec/changes/run-a-turn-against-a2web: the boundary demonstration (a real
# read attempt against a host path outside both of this run's two mounts, expected to fail) followed
# by the actual cross-repo turn. Meant to run inside the container, not on the host.
set -x
echo "=== boundary check: attempt to reach a host path never mounted ==="
cat /Users/iorlas/Documents/Knowledge/CLAUDE.md 2>&1; echo "exit=$?"  # hostpath-allow
ls /Users 2>&1; echo "exit=$?"
echo "=== mounts visible ==="
ls /data 2>&1
echo "=== running the turn ==="
uv run python scripts/run_a2web_turn.py
echo "TURN_EXIT=$?"
