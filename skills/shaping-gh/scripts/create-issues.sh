#!/usr/bin/env bash
# Usage: create-issues.sh <pitches-dir> <repo>
#   pitches-dir: directory containing <slug>.md files per pitch, sorted
#                alphabetically by intended creation order.
#   repo: owner/name target repo.
# Writes pitches.json mapping slug -> issue_number.
set -euo pipefail

DIR="${1:?pitches dir required}"
REPO="${2:?repo required}"
MAP="$DIR/pitches.json"
: > "$MAP.tmp"
echo "{" > "$MAP.tmp"

FIRST=1
for f in "$DIR"/*.md; do
  slug=$(basename "$f" .md)
  title=$(head -n1 "$f" | sed 's/^# //')
  body=$(tail -n +2 "$f")
  num=$(gh issue create --repo "$REPO" --title "$title" --body "$body" --json number --jq .number)
  echo "Created #$num for $slug"
  if [ $FIRST -eq 0 ]; then echo "," >> "$MAP.tmp"; fi
  printf '  "%s": %s' "$slug" "$num" >> "$MAP.tmp"
  FIRST=0
done
echo "" >> "$MAP.tmp"
echo "}" >> "$MAP.tmp"
mv "$MAP.tmp" "$MAP"
echo "Wrote $MAP"
