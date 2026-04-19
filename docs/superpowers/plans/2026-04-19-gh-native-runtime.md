# GH-Native Runtime (Mode 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Mode-2 (GitHub-only) runtime end-to-end today — a target repo installs two workflow files, a shaping skill turns a GH Discussion into a graph of GH Issues linked by tasklists, and the engine drives each issue through SPEC → IMPLEMENT → REVIEW → MERGE with label transitions and PR merges automatically unblocking dependents.

**Architecture:** The engine already owns the per-stage label state machine via `GitHubWorkAdapter` (labels: `agent`, `stage:spec..merge`, `stage:blocked`, `stage:done`). This plan fills the three gaps around it: (1) the `.github/workflows/*.yml` files that invoke `a2sdlc dispatch` on each relevant issue/PR event, (2) an `unblock-next` workflow that reads `## Blocked by` tasklists via `gh api graphql` when an issue closes and applies the `agent` label to newly-unblocked issues, and (3) a shaping skill that creates issues with tasklist-encoded dependencies.

**Tech Stack:** Python 3.12 (existing engine), GitHub Actions reusable workflows, `gh` CLI + `gh api graphql` for tasklist parsing, Typer (existing CLI), pytest (existing tests). No new engine dependencies — everything piggybacks on `GitHubWorkAdapter` and the subscriber bus.

---

## Phase boundaries

- **Phase 0 (OPTIONAL, can defer to Plan B):** uv workspace refactor. Skip if time is tight today; do it first in Plan B (Jira dispatcher) when the second package arrives.
- **Phase 1:** Engine-side tweaks (small) — confirm behaviour, add only what's missing.
- **Phase 2:** Reusable workflow files in the engine repo.
- **Phase 3:** GH-mode shaping skill.
- **Phase 4:** Target-repo onboarding README + smoke test.

Stop between phases, `make check`, commit. Frequent commits.

---

## Task 0: Create feature branch

**Files:**
- No files changed.

- [ ] **Step 1: Cut a branch off main**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-engine
git fetch origin
git checkout -b feat/gh-native-runtime origin/main
```

- [ ] **Step 2: Verify starting state is clean**

```bash
git status
make check
```

Expected: `nothing to commit, working tree clean`; `make check` passes.

---

## Phase 0 (OPTIONAL): uv workspace refactor

Skip this phase if the demo is hours away. Every downstream task works on the current `src/a2sdlc/` layout. If skipped now, do it as the first phase of Plan B when `packages/dispatcher/` lands.

### Task 0.1: Plan the move

**Files:**
- Read only: `pyproject.toml`, `Makefile`.

- [ ] **Step 1: Confirm no other code imports from `src.a2sdlc` textually**

Run: `grep -rE "from src\.a2sdlc|import src\.a2sdlc" src tests Makefile pyproject.toml`
Expected: empty output. (All imports use `a2sdlc.x`, not `src.a2sdlc.x`.)

### Task 0.2: Move the engine into a workspace member

**Files:**
- Create: `packages/engine/pyproject.toml`
- Move: `src/a2sdlc/**` → `packages/engine/src/a2sdlc/**`
- Modify: root `pyproject.toml`

- [ ] **Step 1: Create `packages/engine/` and move sources**

```bash
mkdir -p packages/engine
git mv src packages/engine/src
rmdir src 2>/dev/null || true
```

- [ ] **Step 2: Create `packages/engine/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "a2sdlc-engine"
version = "0.1.0"
description = "a2sdlc engine — per-ticket pipeline (SPEC → IMPLEMENT → REVIEW → MERGE)"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0",
    "claude-agent-sdk>=0.1.50",
    "pydantic>=2.0",
    "rich>=14.0",
    "PyGithub>=2.6",
    "gitpython>=3.1",
    "tenacity>=8.0",
    "python-ulid>=2.0",
    "mlflow>=2.15",
    "typer>=0.24.1",
]

[project.scripts]
a2sdlc = "a2sdlc.cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/a2sdlc"]
```

- [ ] **Step 3: Rewrite root `pyproject.toml` as a workspace root**

Replace the root `pyproject.toml` contents with:

```toml
[project]
name = "a2sdlc-workspace"
version = "0"
requires-python = ">=3.12"

[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["unit", "integration"]
env = ["A2SDLC_TEST=1"]

[tool.importlinter]
root_packages = ["a2sdlc"]

[[tool.importlinter.contracts]]
name = "domain is pure (no imports from other a2sdlc packages)"
type = "forbidden"
source_modules = ["a2sdlc.domain"]
forbidden_modules = [
    "a2sdlc.adapters",
    "a2sdlc.pipeline",
    "a2sdlc.lifecycle",
    "a2sdlc.assembly",
    "a2sdlc.evaluation",
    "a2sdlc.stages",
    "a2sdlc.cli",
    "a2sdlc.config",
]

[[tool.importlinter.contracts]]
name = "adapters do not import application layer"
type = "forbidden"
source_modules = ["a2sdlc.adapters"]
forbidden_modules = [
    "a2sdlc.pipeline",
    "a2sdlc.lifecycle",
    "a2sdlc.assembly",
    "a2sdlc.evaluation",
    "a2sdlc.stages",
    "a2sdlc.cli",
]
ignore_imports = ["a2sdlc.config -> a2sdlc.stages"]

[[tool.importlinter.contracts]]
name = "lifecycle, assembly, evaluation do not import each other or pipeline"
type = "forbidden"
source_modules = ["a2sdlc.lifecycle", "a2sdlc.assembly", "a2sdlc.evaluation"]
forbidden_modules = ["a2sdlc.pipeline", "a2sdlc.cli"]

[[tool.importlinter.contracts]]
name = "lifecycle does not import assembly or evaluation"
type = "forbidden"
source_modules = ["a2sdlc.lifecycle"]
forbidden_modules = ["a2sdlc.assembly", "a2sdlc.evaluation"]

[[tool.importlinter.contracts]]
name = "assembly does not import lifecycle or evaluation"
type = "forbidden"
source_modules = ["a2sdlc.assembly"]
forbidden_modules = ["a2sdlc.lifecycle", "a2sdlc.evaluation"]

[[tool.importlinter.contracts]]
name = "evaluation does not import lifecycle or assembly"
type = "forbidden"
source_modules = ["a2sdlc.evaluation"]
forbidden_modules = ["a2sdlc.lifecycle", "a2sdlc.assembly"]

[dependency-groups]
dev = [
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0",
    "pytest-env>=1.6.0",
    "diff-cover>=9.0",
    "ruff>=0.15.9",
    "ty>=0.0.28",
    "import-linter>=2.0",
]
```

- [ ] **Step 4: Resync, relint, retest**

```bash
uv sync --all-packages
uv run lint-imports
make test
```

Expected: `uv sync` succeeds, `lint-imports` passes (import-linter contracts still hold — they reference `a2sdlc.*` which is unchanged), tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move engine into uv workspace member packages/engine"
```

---

## Phase 1: Engine-side confirmation (small)

### Task 1.1: Verify stage-transition label writes already exist

**Files:**
- Read only: `packages/engine/src/a2sdlc/adapters/work/github.py` (or `src/a2sdlc/adapters/work/github.py` if Phase 0 skipped) and any `end_stage`/`finalize` call sites.

- [ ] **Step 1: Grep for label-set operations in the work adapter**

Run: `grep -nE "set_labels|add_to_labels|stage:implement|stage:review|stage:merge|stage:done|stage:blocked" packages/engine/src/a2sdlc/adapters/work/github.py 2>/dev/null || grep -nE "set_labels|add_to_labels|stage:implement|stage:review|stage:merge|stage:done|stage:blocked" src/a2sdlc/adapters/work/github.py`

Expected: writes of `stage:<next>` / `stage:blocked` / `stage:done` at pipeline/stage boundaries. If present: no engine change needed for Phase 1. If absent: add a Task 1.2 to implement `advance_to(next_stage)` / `mark_blocked(reason)` / `mark_done()` and wire them into `pipeline/dispatch.py`. Since this plan targets the demo, write down what you find here in a comment and proceed.

- [ ] **Step 2: Record findings**

Write a 3-line note in the PR description of what already exists vs what was missing.

### Task 1.2 (CONDITIONAL): add missing stage-advance label writes

Only perform if Task 1.1 found gaps. Skip otherwise.

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/work/github.py` (add `advance_to_next_stage(current)`, `mark_blocked(reason)`, `mark_done()` methods using PyGithub's `issue.add_to_labels` / `remove_from_labels`).
- Test: `tests/adapters/work/test_github_label_transitions.py`

- [ ] **Step 1: Write failing test**

```python
# tests/adapters/work/test_github_label_transitions.py
from unittest.mock import MagicMock
from a2sdlc.adapters.work.github import GitHubWorkAdapter
from a2sdlc.domain.models import StageName


def test_advance_to_next_stage_swaps_labels():
    repo = MagicMock()
    issue = MagicMock()
    repo.get_issue.return_value = issue

    adapter = GitHubWorkAdapter(repo)
    adapter.advance_to_next_stage(issue_number=42, current=StageName.SPEC)

    issue.remove_from_labels.assert_called_with("stage:spec")
    issue.add_to_labels.assert_called_with("stage:implement")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/adapters/work/test_github_label_transitions.py -v`
Expected: FAIL (method does not exist).

- [ ] **Step 3: Implement `advance_to_next_stage`**

Add to `GitHubWorkAdapter`:

```python
_NEXT_STAGE: dict[StageName, StageName | None] = {
    StageName.SPEC: StageName.IMPLEMENT,
    StageName.IMPLEMENT: StageName.REVIEW,
    StageName.REVIEW: StageName.MERGE,
    StageName.MERGE: None,
}

def advance_to_next_stage(self, issue_number: int, current: StageName) -> None:
    issue = self._repo.get_issue(issue_number)
    current_label = STAGE_LABELS[current]
    try:
        issue.remove_from_labels(current_label)
    except Exception:
        pass
    next_stage = self._NEXT_STAGE.get(current)
    if next_stage is not None:
        issue.add_to_labels(STAGE_LABELS[next_stage])
    else:
        issue.add_to_labels(DONE_LABEL)

def mark_blocked(self, issue_number: int, reason: str) -> None:
    issue = self._repo.get_issue(issue_number)
    issue.add_to_labels(BLOCKED_LABEL)
    issue.create_comment(f":warning: blocked: {reason}")
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/adapters/work/test_github_label_transitions.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into `pipeline/dispatch.py`**

Hunt for the current post-stage hook call site. Add invocations of `advance_to_next_stage` on success and `mark_blocked` on failure. Keep within the existing hexagonal rules (dispatch calls adapter, never issue labels directly).

- [ ] **Step 6: `make check` + commit**

```bash
make check
git add -A
git commit -m "feat(adapters): label-based stage transitions for Mode 2"
```

---

## Phase 2: Reusable GH Actions workflows (in engine repo)

These YAMLs live in the engine repo (`.github/workflows/`) and are referenced from the target repo via `uses: yoselabs/a2sdlc-engine/.github/workflows/<name>@v1`. For the demo, the target repo can reference them as `@main` until a tag is cut.

### Task 2.1: Create `run-native.yml`

**Files:**
- Create: `.github/workflows/run-native.yml`

- [ ] **Step 1: Write the reusable workflow**

```yaml
# .github/workflows/run-native.yml
# Reusable workflow: runs `a2sdlc dispatch` on a single GitHub event.
# Consumer workflows pass the event context through and provide secrets.

name: a2sdlc — run (native)

on:
  workflow_call:
    secrets:
      ANTHROPIC_API_KEY:
        required: true
      MLFLOW_TRACKING_URI:
        required: false
      MLFLOW_TRACKING_USERNAME:
        required: false
      MLFLOW_TRACKING_PASSWORD:
        required: false

jobs:
  dispatch:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    permissions:
      contents: write        # push branches
      issues: write          # comment, label, close
      pull-requests: write   # open, review, merge
      statuses: write        # commit-status writes (if the engine posts any)
      checks: write          # check-run annotations (if the engine posts any)
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Install engine
        run: |
          uv tool install --from 'git+https://github.com/yoselabs/a2sdlc-engine@main' a2sdlc-engine
          # TEMP for pre-release: install from source until a tag is cut.

      - name: Dispatch
        env:
          GITHUB_TOKEN: ${{ github.token }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          MLFLOW_TRACKING_URI: ${{ secrets.MLFLOW_TRACKING_URI }}
          MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
          MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
        run: |
          uv tool run a2sdlc dispatch
```

Rationale:
- `workflow_call` makes it reusable from any consumer repo.
- `permissions` scoped to what the engine needs (issues/PRs/contents).
- MLflow secrets optional — MLflow subscriber activates only when `MLFLOW_TRACKING_URI` is set.
- `uv tool install --from '<git-url>' a2sdlc-engine` — the trailing token is the **package name**, not a URL. If Phase 0 was done, the distribution is `a2sdlc-engine`. If Phase 0 was skipped, keep the root-level package name `a2sdlc` (i.e. `uv tool install --from '<git-url>' a2sdlc`). The `--from` URL is the same either way.

- [ ] **Step 2: Manual-verify YAML parses**

Run: `yamllint .github/workflows/run-native.yml || true`
(If yamllint not installed, skim visually — no tab characters, keys aligned.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/run-native.yml
git commit -m "ci: reusable workflow run-native.yml for Mode 2"
```

### Task 2.2: Create `unblock-next.yml`

**Files:**
- Create: `.github/workflows/unblock-next.yml`
- Create: `.github/workflows/scripts/unblock.sh` (small shell script)

- [ ] **Step 1: Write the unblock workflow**

```yaml
# .github/workflows/unblock-next.yml
# Reusable workflow: when an issue closes, use GH's native tasklist
# relationships (`trackedInIssues`) to find dependents and label them
# `agent` when ALL their tracked issues are closed.

name: a2sdlc — unblock next

on:
  workflow_call: {}

jobs:
  unblock:
    runs-on: ubuntu-latest
    permissions:
      issues: write
    steps:
      - name: Apply agent label to newly-unblocked issues
        env:
          GH_TOKEN: ${{ github.token }}
          CLOSED_ISSUE: ${{ github.event.issue.number }}
          OWNER: ${{ github.repository_owner }}
          NAME: ${{ github.event.repository.name }}
        run: |
          set -euo pipefail

          # 1) Find issues that track the just-closed one (native tasklist backref).
          TRACKED_IN=$(gh api graphql -f query='
            query($owner:String!,$name:String!,$num:Int!) {
              repository(owner:$owner, name:$name) {
                issue(number:$num) {
                  trackedInIssues(first:50) { nodes { number state } }
                }
              }
            }' -F owner="$OWNER" -F name="$NAME" -F num="$CLOSED_ISSUE" \
            --jq '.data.repository.issue.trackedInIssues.nodes[] | select(.state=="OPEN") | .number')

          if [ -z "$TRACKED_IN" ]; then
            echo "No open issues track #${CLOSED_ISSUE}."
            exit 0
          fi

          # 2) For each dependent, check ALL its tracked issues are CLOSED.
          for N in $TRACKED_IN; do
            ALL_CLOSED=$(gh api graphql -f query='
              query($owner:String!,$name:String!,$num:Int!) {
                repository(owner:$owner, name:$name) {
                  issue(number:$num) {
                    trackedIssues(first:50) { nodes { state } }
                  }
                }
              }' -F owner="$OWNER" -F name="$NAME" -F num="$N" \
              --jq '[.data.repository.issue.trackedIssues.nodes[].state] | all(.=="CLOSED")')

            if [ "$ALL_CLOSED" = "true" ]; then
              echo "#$N fully unblocked — labelling 'agent'"
              gh issue edit "$N" --repo "$OWNER/$NAME" --add-label "agent"
            else
              echo "#$N still has open blockers, skipping"
            fi
          done
```

Rationale:
- Uses **GH's native tasklist API** (`trackedIssues` / `trackedInIssues` via GraphQL). These are the official relationships behind the `- [ ]` checklist UX on issues — robust against code fences, heading typos, renames.
- Two tiny queries per closed issue; no body parsing anywhere.
- Applies `agent` label (the engine's SPEC trigger) only when every dependency is `CLOSED`.
- Fallback: if the target repo uses `## Blocked by` markdown references instead of GH tasklists, this workflow will find nothing. The shaping skill (Task 3.1) always emits tasklists, so the happy path works. Users adopting this manually must use GH's checklist-reference feature.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/unblock-next.yml
git commit -m "ci: reusable workflow unblock-next.yml for Mode 2 dependency graph"
```

### Task 2.3: Create target-repo onboarding example workflows

**Files:**
- Create: `docs/mode2/example-workflows/a2sdlc-run.yml`
- Create: `docs/mode2/example-workflows/a2sdlc-unblock.yml`

These are the files a target repo copies into its own `.github/workflows/`. We ship them under `docs/mode2/example-workflows/` as copy-paste artifacts.

- [ ] **Step 1: Create `docs/mode2/example-workflows/a2sdlc-run.yml`**

```yaml
# .github/workflows/a2sdlc-run.yml (in the TARGET repo)
# Trigger: any event that GitHubWorkAdapter knows how to dispatch.
# See docs/mode2/README.md for the label state machine.

name: a2sdlc

on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]
  pull_request:
    types: [labeled]
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]

jobs:
  dispatch:
    uses: yoselabs/a2sdlc-engine/.github/workflows/run-native.yml@main
    secrets:
      ANTHROPIC_API_KEY:        ${{ secrets.ANTHROPIC_API_KEY }}
      MLFLOW_TRACKING_URI:      ${{ secrets.MLFLOW_TRACKING_URI }}
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
```

- [ ] **Step 2: Create `docs/mode2/example-workflows/a2sdlc-unblock.yml`**

```yaml
# .github/workflows/a2sdlc-unblock.yml (in the TARGET repo)
name: a2sdlc-unblock

on:
  issues:
    types: [closed]

jobs:
  unblock:
    uses: yoselabs/a2sdlc-engine/.github/workflows/unblock-next.yml@main
```

- [ ] **Step 3: Commit**

```bash
git add docs/mode2/example-workflows/
git commit -m "docs: target-repo example workflows for Mode 2"
```

---

## Phase 3: Shaping skill (GH mode)

The shaping skill is a Claude Code prompt + tiny helper scripts. For Day 1 it lives in `skills/shaping-gh/` inside the engine repo and is invoked interactively via Claude Code Desktop against a target repo.

### Task 3.1: Scaffold the skill

**Files:**
- Create: `skills/shaping-gh/SKILL.md`
- Create: `skills/shaping-gh/templates/pitch.md`
- Create: `skills/shaping-gh/scripts/create-issues.sh`

- [ ] **Step 1: Write `skills/shaping-gh/SKILL.md`**

```markdown
---
name: shaping-gh
description: Shape a feature milestone into a dependency graph of GitHub Issues. Input: a GitHub Discussion thread or a local markdown brief. Output: an epic issue plus story issues linked by "## Blocked by" tasklists, with the first root issue labeled `agent` to kick off the engine.
---

# Shaping (GitHub mode)

## When to use

- The user has a rough feature idea (in a GH Discussion thread, a markdown file,
  or verbally) and wants to break it into a sequence of tickets the a2sdlc
  engine can process.
- The target repo already has `a2sdlc-run.yml` and `a2sdlc-unblock.yml`
  installed (see `docs/mode2/README.md`).

## Flow

1. Read the input source (Discussion thread via `gh api graphql` or local file).
2. Ask the user clarifying questions one at a time — scope, non-goals, success
   criteria. Keep it short; this is not full brainstorming.
3. Draft a pitch list as markdown (see `templates/pitch.md`). Each pitch has
   - a story title
   - a problem statement (2–3 sentences)
   - acceptance criteria (bulleted)
   - a `## Blocked by` tasklist referencing earlier pitches by their eventual
     issue numbers (use placeholders `#?` until issues exist).
4. Present the full draft back to the user. Iterate on feedback.
5. On approval:
   - Create the epic issue (`gh issue create`) with a summary + a tasklist
     pointing at the stories.
   - Run `scripts/create-issues.sh <pitches-dir> <owner/repo>` — creates each
     story, writes `<pitches-dir>/pitches.json` mapping slug → issue_number.
   - Back-patch `#?` placeholders in each created issue:
     ```bash
     # Example for one story body that had "- [ ] #?auth-slug":
     NUM=$(jq -r '."auth-slug"' pitches.json)
     gh issue edit <STORY_NUM> --repo <owner/repo> \
       --body "$(gh issue view <STORY_NUM> --repo <owner/repo> --json body --jq .body \
         | sed "s/#?auth-slug/#${NUM}/g")"
     ```
     (The skill iterates this for every `#?slug` placeholder in every story.)
   - Apply the `agent` label to the root issue(s) (those with no blockers).

## Scripts

`scripts/create-issues.sh` expects a bundle of pitch markdown files and
creates issues in order, writing the mapping back to `pitches.json`.

## Anti-patterns

- Do not create issues before the user approves the draft.
- Do not start engine runs directly — only label the first issue `agent`;
  the GH Actions workflow fires from there.
- Do not rewrite the user's language into agent-speak. Preserve their framing.
```

- [ ] **Step 2: Write `skills/shaping-gh/templates/pitch.md`**

```markdown
# <story title>

## Problem
<2-3 sentences describing the concrete problem this story solves.>

## Acceptance criteria
- [ ] <criterion 1>
- [ ] <criterion 2>

## Blocked by
- [ ] #<blocker issue number>
```

- [ ] **Step 3: Write `skills/shaping-gh/scripts/create-issues.sh`**

```bash
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
```

- [ ] **Step 4: Make script executable and commit**

```bash
chmod +x skills/shaping-gh/scripts/create-issues.sh
git add skills/shaping-gh/
git commit -m "feat(skills): shaping-gh for turning requirements into GH issue graphs"
```

### Task 3.2: Smoke-validate the skill on a throwaway repo

**Files:**
- No new files. This validates the skill end-to-end against a real repo.

- [ ] **Step 1: Pick or create a throwaway repo**

Use or create a throwaway repo (e.g. `iorlas/a2sdlc-demo-day1`) with:
- `main` branch, a README
- `.github/workflows/a2sdlc-run.yml` + `a2sdlc-unblock.yml` copied from `docs/mode2/example-workflows/`
- Secret `ANTHROPIC_API_KEY` set
- (Optional) Secrets `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD` set

- [ ] **Step 2: Invoke the skill against a tiny brief**

Create a local brief file `brief.md` with 2 pitches where pitch 2 blocks on pitch 1. Run the skill from Claude Code Desktop against the throwaway repo. Expect: 3 issues created (1 epic + 2 stories), pitch 2's `## Blocked by` contains `#<pitch1 number>`, pitch 1 has label `agent`.

- [ ] **Step 3: Confirm engine kicks off**

Watch the GH Actions runs page. `a2sdlc-run.yml` should trigger immediately on the `agent` label. Let it run through SPEC → IMPLEMENT → REVIEW → MERGE for pitch 1. If MLflow secrets are set, confirm a run appears in your MLflow tracking server tagged with `ticket_key=<issue number>`.

- [ ] **Step 4: Confirm unblock-next fires after merge**

Merge the PR (human click). The unblock workflow should fire on issue close, label pitch 2 with `agent`, and the engine should pick it up automatically.

- [ ] **Step 5: Record findings in `docs/mode2/smoke-test.md`**

Write what worked, what didn't, and any tweaks needed to the example workflows.

- [ ] **Step 6: Commit**

```bash
git add docs/mode2/smoke-test.md
git commit -m "docs: Mode 2 smoke test findings"
```

---

## Phase 4: Target-repo onboarding README

### Task 4.1: Write the onboarding doc

**Files:**
- Create: `docs/mode2/README.md`

- [ ] **Step 1: Write `docs/mode2/README.md`**

```markdown
# a2sdlc — GitHub-only runtime (Mode 2)

Drop two workflow files into your target repo and the engine will drive
tickets through SPEC → IMPLEMENT → REVIEW → MERGE on GitHub Actions, using
GH Issues as the tracker.

## What you need

- A GitHub repo with Issues enabled.
- Secrets configured in the repo:
  - `ANTHROPIC_API_KEY` (required)
  - `MLFLOW_TRACKING_URI` + `MLFLOW_TRACKING_USERNAME` + `MLFLOW_TRACKING_PASSWORD` (optional; skip if you don't want telemetry)

## Install

1. Copy `example-workflows/a2sdlc-run.yml` → `.github/workflows/a2sdlc-run.yml`.
2. Copy `example-workflows/a2sdlc-unblock.yml` → `.github/workflows/a2sdlc-unblock.yml`.
3. Commit, push.

That's it. No other files, no mappings, no per-repo config.

## Drive it

### Manual (single-ticket mode)

1. Create a GH Issue with a description.
2. Apply the `agent` label.
3. Watch the Actions tab: the engine runs SPEC → IMPLEMENT → REVIEW → MERGE
   across four workflow runs (one per stage), advancing via `stage:*` labels.
4. On completion the engine opens a PR with `Closes #<issue>`. Human merges.
5. Issue auto-closes. If other issues reference this one under `## Blocked by`,
   they'll get the `agent` label automatically and the cycle repeats.

### Batch (shaping mode)

Use the `shaping-gh` skill (see `skills/shaping-gh/SKILL.md`) to turn a GH
Discussion or brief into a pre-ordered graph of issues in one go.

## Label state machine

| Label          | Meaning                                              | Who sets it                                   |
|----------------|------------------------------------------------------|-----------------------------------------------|
| `agent`        | kick off SPEC stage                                  | you (or shaping skill, or unblock workflow)   |
| `stage:spec`   | SPEC in progress                                     | engine                                        |
| `stage:implement` | IMPLEMENT in progress                             | engine                                        |
| `stage:review` | REVIEW in progress                                   | engine                                        |
| `stage:merge`  | MERGE stage opening PR                               | engine                                        |
| `stage:done`   | fully done                                           | engine                                        |
| `stage:blocked`| engine failed — inspect comments                     | engine                                        |
| `needs-input`  | engine asked a question, awaiting human reply        | engine                                        |
| `proceed`      | human answered `needs-input`, resume                 | human                                         |

## Dependency encoding (for multi-ticket features)

In a story's issue body, include a section exactly named `## Blocked by`
containing GitHub task-list items referencing blockers:

```markdown
## Blocked by
- [ ] #12
- [ ] #14
```

When #12 and #14 close, the `unblock-next` workflow applies the `agent` label
to this issue automatically.

## Observability

- **GH Actions**: every engine run is a workflow run URL — logs, steps, re-run.
- **MLflow** (optional): if secrets set, every run is tagged with
  `ticket_key`, `run_id`, `branch`, `variant`, `mode`.
- **Issue comments**: the engine posts throttled status updates via
  `GhCommentSubscriber`.

## Troubleshooting

| Symptom                                     | Likely cause                                        |
|---------------------------------------------|-----------------------------------------------------|
| Nothing runs after labelling `agent`        | Check Actions tab; secret `ANTHROPIC_API_KEY` unset |
| Engine loops on SPEC                        | Stage-transition label writes missing (Task 1.2)    |
| Unblock workflow doesn't trigger dependents | `## Blocked by` header mistyped or mixed casing     |
| MLflow empty                                | Optional secrets unset; engine runs without it      |
```

- [ ] **Step 2: Commit**

```bash
git add docs/mode2/README.md
git commit -m "docs: Mode 2 onboarding README"
```

---

## Phase 5: Wrap-up

### Task 5.1: Final gate

**Files:**
- No new files.

- [ ] **Step 1: Run the full gate**

```bash
make check
```

Expected: all green.

- [ ] **Step 2: Open the PR**

```bash
git push -u origin feat/gh-native-runtime
gh pr create --title "feat: GH-native runtime (Mode 2)" --body "$(cat <<'EOF'
## Summary
- Phase 0 (optional): move engine into uv workspace member (`packages/engine/`)
- Phase 1: confirm/add stage-transition label writes in `GitHubWorkAdapter`
- Phase 2: reusable workflows `run-native.yml`, `unblock-next.yml` + example target-repo workflows
- Phase 3: `shaping-gh` skill (scaffold + create-issues script)
- Phase 4: target-repo onboarding README

## Test plan
- [x] `make check` green
- [ ] Smoke test run against throwaway repo: 2 pitches, 1→2 dependency, full pipeline + unblock
- [ ] MLflow trace visible for each stage (if `MLFLOW_TRACKING_URI` set)

Closes: Mode 2 v1 (day 1 of shaping+dispatcher demo).
EOF
)"
```

---

## Spec coverage

Cross-reference against `docs/superpowers/specs/2026-04-19-shaping-and-dispatcher-design.md` §"Day 1 — GH-Native Runtime (Mode 2)":

| Spec item | Task(s) |
|---|---|
| Trigger on `issues: labeled` with `agent` | Task 2.1, 2.3 |
| Dependency encoding via `## Blocked by` tasklists | Task 2.2, 3.1, 4.1 |
| Label state machine (`agent` → `stage:*` → `stage:done`/`blocked`) | Task 1.1, 1.2, 4.1 (docs) |
| `GHIssueReader` / `GHIssueSubscriber` | Existing `GitHubWorkAdapter` covers both — verified in Task 1.1 |
| Composition root env branches | Already present (see Explore report) — no new code |
| Reusable workflow `run-native.yml` | Task 2.1 |
| Unblock workflow | Task 2.2 |
| Shaping skill GH mode | Task 3.1 |
| MLflow first-class subscriber | Existing; passed through workflow secrets (Task 2.1, 2.3) |
| Local eval preserved | No changes to local mode; verified by `make check` passing in Phase 5 |
| Target-repo install footprint = 2 workflow files | Task 2.3 + Task 4.1 |
| Onboarding docs | Task 4.1 |

Spec items NOT in this plan (deferred to Plan B or post-demo):
- Dispatcher service (Days 2–3 scope)
- `DispatcherEventSubscriber`, `WorkflowInputReader` (Days 2–3 scope)
- `PROJECTS_JSON` (Days 2–3 scope)
- Parallel A/B variant orchestration (deferred)
- GitLab / Azure Boards adapters (deferred)
- `.a2sdlc.yml` per-project preferences file (deferred — engine already has config defaults)
- Marketplace publication (deferred)
