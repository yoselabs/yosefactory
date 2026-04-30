#!/usr/bin/env bash
# Spec §Testing strategy → End-to-end smoke. AC #15.
set -euo pipefail

REQUIRED=(ANTHROPIC_API_KEY)
for v in "${REQUIRED[@]}"; do
  if [ -z "${!v:-}" ]; then
    echo "smoke-local skipped: $v not set"
    exit 0
  fi
done

ROOT="$(git rev-parse --show-toplevel)"
TMP="$ROOT/tmp/smoke-local"
WORK="$TMP/repo"
ORIGIN="$TMP/origin.git"

# Cleanup older failed-run preservation directories — keep only the most recent.
shopt -s nullglob
for d in "$ROOT/tmp/smoke-local-failed-"*; do
  rm -rf "$d"
done

rm -rf "$TMP"
mkdir -p "$WORK" "$ORIGIN"

git init -q --bare "$ORIGIN"
git init -q "$WORK"
cd "$WORK"
git config user.email "smoke@a2sdlc.local"
git config user.name "smoke"
git remote add origin "$ORIGIN"

mkdir -p .a2sdlc
cat > .a2sdlc/config.yaml <<'YAML'
mode: local
adapters: {work: local-file, review: local}
subscribers: [console, mlflow]
required_env: [ANTHROPIC_API_KEY]
pipeline: {max_review_cycles: 2, protected_bases: [main]}
YAML

cat > INPUT.md <<'MD'
# Smoke task

Add a top-level Python module `greet.py` that exposes a function
`greet(name: str) -> str` returning `"hello, {name}!"`. Add a unit
test in `tests/test_greet.py` covering the happy path.
MD

echo "scratch repo init" > README.md
git add .
git commit -q -m "init"
git checkout -q -b req/smoke-feature
git add INPUT.md
git commit -q --amend --no-edit
git push -q -u origin req/smoke-feature

# Run the engine.
TRANSCRIPT="$TMP/transcript.txt"
if a2sdlc run > "$TRANSCRIPT" 2>&1; then
  STATUS=0
else
  STATUS=$?
fi

# On failure, preserve the entire tree.
if [ "$STATUS" -ne 0 ]; then
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  mv "$TMP" "$ROOT/tmp/smoke-local-failed-$TS"
  echo "smoke-local FAILED — preserved at tmp/smoke-local-failed-$TS"
  exit 1
fi

# Assertions.
fail() { echo "smoke-local ASSERT FAILED: $*"; exit 1; }

# Run-branch on origin.
RUN_BRANCH=$(git -C "$WORK" branch --show-current)
echo "$RUN_BRANCH" | grep -q "^a2sdlc/auto/" || fail "branch shape: $RUN_BRANCH"
git -C "$WORK" ls-remote origin "$RUN_BRANCH" | grep -q . || fail "branch missing on origin"

# Artifacts present.
STATE_DIR="$WORK/.a2sdlc/state/$(echo "$RUN_BRANCH" | tr / __)"
[ -f "$STATE_DIR/spec.md" ] || fail "spec.md missing under $STATE_DIR"
ls "$STATE_DIR/"implement-cycle-*.md > /dev/null 2>&1 || fail "implement-cycle-*.md missing"
ls "$STATE_DIR/reviews/"*.md > /dev/null 2>&1 || fail "review file missing"

# Stdout assertions.
grep -q "===== a2sdlc:stage-output BEGIN =====" "$TRANSCRIPT" || fail "missing output BEGIN fence"
grep -q "===== a2sdlc:stage-output END =====" "$TRANSCRIPT" || fail "missing output END fence"
grep -qE "^totals: " "$TRANSCRIPT" || fail "missing totals: line"

# Cleanup on success.
rm -rf "$TMP"

echo "smoke-local PASSED"
