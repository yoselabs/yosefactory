# Adapters — Kind-First Layout Restructure

**Status:** Draft · 2026-04-19
**Author:** Claude (with Denis)
**Scope:** Reorganize `src/a2sdlc/adapters/` from a flat 14-file folder into kind-first subfolders; consolidate protocol definitions (currently in three places); mirror the new layout in `tests/adapters/`; move `PipelineEvent` to `domain/`. Zero behavior change.

---

## Motivation

Two friction points Denis hit while reading the code:

1. **Growth anxiety.** `adapters/` is flat. We have 4 subscribers already and 1 more in the pipeline (`TranscriptLogSubscriber`). New git/work/review variants are plausible too. The folder keeps bloating alongside hard-to-categorize helpers (`factory.py`, `retry.py`).
2. **Discoverability.** "Show me all available adapters for kind X" requires eyeballing filenames. No single place collects "here's the contract, here are the impls."

A concrete inconsistency surfaced during exploration, but it's a **consequence** of the flat layout, not the driver: three protocols (`GitAdapter`, `StageRunner`, `Subscriber`) live in `protocols.py`, two (`WorkAdapter`, `ReviewAdapter`) have their own dedicated files (`work.py`, `review.py`). The restructure resolves that naturally.

## Non-goals

- **Not** changing architectural rules. Domain purity, `adapters → evaluation` subscriber direction, and the `pipeline/` composition-root role all stay intact.
- **Not** redesigning the Protocols themselves. Only moving them.
- **Not** touching the `stages/` or `pipeline/` packages. The `Stage` Protocol lives in `stages/base.py` and stays there.
- **Not** splitting tests by kind beyond a one-level mirror. No nested test groupings like `subscriber/console/test_*`.

## Target structure

### `src/a2sdlc/adapters/`

```
adapters/
  __init__.py             # slim re-exports; keeps backwards-compat single-line imports
  factory.py              # unchanged — cross-kind composition helper
  retry.py                # unchanged — cross-kind utility
  _github.py              # NEW — PyGithub connect() + shared helpers for work/github + review/github
  git/
    __init__.py           # GitAdapter Protocol + re-exports of impls
    local.py              # was git.py                → LocalGitAdapter
    local_branch.py       # was local_branch_git.py   → LocalBranchGitAdapter
  work/
    __init__.py           # WorkAdapter Protocol + re-exports
    github.py             # NEW — GitHubWorkAdapter carved from current github.py
    local_file.py         # was local_file_work.py    → LocalFileWorkAdapter
  review/
    __init__.py           # ReviewAdapter Protocol + Approval + ReviewComment + re-exports
    github.py             # NEW — GitHubReviewAdapter carved from current github.py
    local_noop.py         # was local_noop_review.py  → LocalNoopReviewAdapter
  subscriber/
    __init__.py           # Subscriber Protocol + re-exports
    console.py            # was console_subscriber.py
    gh_actions.py         # was gh_actions_subscriber.py
    gh_comment.py         # was gh_comment_subscriber.py
    mlflow_trace.py       # was mlflow_trace_subscriber.py
  runner/
    __init__.py           # StageRunner Protocol (no impls — SdkStageRunner stays in pipeline/)
```

Each subfolder's `__init__.py` re-exports both the Protocol and its impls so external callers keep a one-line import:
```python
from a2sdlc.adapters.work import WorkAdapter, LocalFileWorkAdapter, GitHubWorkAdapter
from a2sdlc.adapters.subscriber import Subscriber, ConsoleSubscriber
```

**Top-level `adapters/__init__.py` facade policy.** The current top-level module re-exports 7 names (`GitAdapter`, `StageRunner`, `WorkAdapter`, `ReviewAdapter`, `PipelineEvent`, `Approval`, `ReviewComment`). After the migration it still re-exports every Protocol + the two review data types, just sourced from their new subpackages. `PipelineEvent` drops out of the top-level re-exports because it leaves `adapters/` entirely (Commit 3). Net: callers that already do `from a2sdlc.adapters import WorkAdapter` keep working; only `PipelineEvent` imports must migrate to `a2sdlc.domain.pipeline_event`.

**Why `runner/` with no impls.** `StageRunner` is the only Protocol with no in-tree impls (`SdkStageRunner` lives in `pipeline/runner.py` intentionally — it composes the SDK and belongs to the pipeline layer, not adapters). The `runner/` subfolder exists solely to hold its Protocol and give the layout kind-first uniformity. Future runner variants (fake, retrying, recording) would land here.

### `src/a2sdlc/domain/`

```
domain/
  models.py
  run_result.py
  exceptions.py
  directives.py
  handover.py
  pipeline_event.py       # NEW — moved from adapters/work.py
```

`PipelineEvent` is a pure dataclass with no I/O — crosses the pipeline↔adapter boundary and is consumed by both. Belongs in `domain/`. `WorkAdapter.parse_event()` returns it; `pipeline/dispatch.py` consumes it; `tests/fakes.py` constructs it.

### `tests/adapters/`

```
tests/adapters/
  test_factory.py              # unchanged — exercises factory.py
  test_retry.py                # unchanged — exercises retry.py
  git/
    test_local.py              # was test_git.py (renamed — maps to git/local.py)
    test_local_branch.py       # was test_local_branch_git.py
  work/
    test_github.py             # was test_github_work.py
    test_github_parse_event.py # unchanged filename, new location
    test_local_file.py         # was test_local_file_work.py
  review/
    test_github.py             # was test_github_review.py
    test_local_noop.py         # was test_local_noop_review.py
  subscriber/
    test_console.py            # was test_console_subscriber.py
    test_gh_actions.py         # was test_gh_actions_subscriber.py
    test_gh_comment.py         # was test_gh_comment_subscriber.py
    test_mlflow_trace.py       # was test_mlflow_trace_subscriber.py
    test_protocol.py           # was test_subscriber_protocol.py (name was overclaiming)
```

`test_pipeline_event.py` moves out of `tests/adapters/` entirely. It now lives at `tests/domain/test_pipeline_event.py` mirroring the new home of `PipelineEvent`.

## Migration plan

Done as one branch with sequential commits; each commit should leave `make check` green.

### Commit 1 — Create kind folders and move files (no splits yet)

- `git mv` preserving history on each single-file move. For files that need rename, use `git mv src/a2sdlc/adapters/git.py src/a2sdlc/adapters/git/local.py` (git tracks as rename; `git log --follow` traces blame).
- Create `__init__.py` for each subfolder with a re-export block. Copy Protocol code into the right `__init__.py` from the old file.
- **Ordering hazard — read carefully.** `adapters/github.py` currently has `from a2sdlc.adapters.review import Approval, ReviewComment` and `from a2sdlc.adapters.work import PipelineEvent`. Those imports are preserved intentionally — they must keep resolving after Commit 1. This works if and only if the flat `adapters/review.py` and `adapters/work.py` modules are deleted **after** the new `review/` and `work/` packages exist with `__init__.py` files re-exporting `Approval`, `ReviewComment`, `WorkAdapter`, and `PipelineEvent`. Python resolves `from a2sdlc.adapters.review import Approval` against the package's `__init__.py` once the flat module is gone. Do not rewrite these imports in Commit 1 — they survive the migration unchanged.
- Delete `adapters/protocols.py`, `adapters/work.py`, `adapters/review.py` last, once their content has been redistributed.
- `adapters/github.py` NOT yet split — keep it for now; imports below handle both old and new paths.
- `adapters/__init__.py` re-exports everything from the new locations so external callers see no change.
- **Source-side hardcoded loggers.** `adapters/local_noop_review.py` contains `logging.getLogger("a2sdlc.adapters.local_noop_review")`. After the file moves to `adapters/review/local_noop.py`, update this literal to `"a2sdlc.adapters.review.local_noop"` to match `__name__` (or replace with `__name__`). Matching test side: `tests/adapters/test_local_file_work.py` has three `caplog.at_level(..., logger="a2sdlc.adapters.local_file_work")` calls that must become `"a2sdlc.adapters.work.local_file"`. (`adapters/retry.py` stays top-level, its logger string doesn't change.)

Import linter `ignore_imports` entries update to the new dotted paths. Note: the `a2sdlc.adapters.protocols -> a2sdlc.evaluation.progress` entry appears in **two** contracts in `pyproject.toml` — the "adapters do not import application layer" contract (~line 90) **and** the "lifecycle does not import assembly or evaluation" contract (~line 124). Both must be updated.

- `a2sdlc.adapters.console_subscriber -> a2sdlc.evaluation.progress` → `a2sdlc.adapters.subscriber.console -> a2sdlc.evaluation.progress`
- Same rename for `gh_actions_subscriber`, `gh_comment_subscriber`, `mlflow_trace_subscriber`
- `a2sdlc.adapters.protocols -> a2sdlc.evaluation.progress` → `a2sdlc.adapters.subscriber -> a2sdlc.evaluation.progress` (applied in both contracts)

### Commit 2 — Split `adapters/github.py`

- `work/github.py` gets `GitHubWorkAdapter`
- `review/github.py` gets `GitHubReviewAdapter`
- `_github.py` gets the `connect()` helper and any constants/utilities used by both
- Update the hardcoded logger string `"a2sdlc.adapters.github"` in each split file to its new path (or switch to `__name__`).
- Update callers (`cli.py` imports both; factory.py if relevant) to the new paths.
- **Update string-form test references.** `patch()` targets don't fail at import time — they explode at test-run time with an unhelpful `AttributeError` or `ModuleNotFoundError`. Sweep explicitly. Concrete targets (verified 2026-04-19; re-grep before editing in case unrelated work lands):
  - `tests/test_cli.py` — 4 patches:
    - `patch("a2sdlc.adapters.github.connect")` → `patch("a2sdlc.adapters._github.connect")`
    - `patch("a2sdlc.adapters.github.GitHubWorkAdapter")` → `patch("a2sdlc.adapters.work.github.GitHubWorkAdapter")`
    - `patch("a2sdlc.adapters.github.GitHubReviewAdapter")` → `patch("a2sdlc.adapters.review.github.GitHubReviewAdapter")`
    - `patch("a2sdlc.adapters.git.LocalGitAdapter")` → `patch("a2sdlc.adapters.git.local.LocalGitAdapter")` (handled in Commit 1 by convention, verify here)
  - `tests/adapters/test_git.py` — 11 identical `patch("a2sdlc.adapters.git.Repo")` strings → `patch("a2sdlc.adapters.git.local.Repo")` (this is technically a Commit 1 follow-up, but re-verify in Commit 2 since the git.py rename happens in Commit 1)
  - `tests/adapters/test_mlflow_trace_subscriber.py` — 1 patch: `"a2sdlc.adapters.mlflow_trace_subscriber.mlflow.start_span_no_context"` → `"a2sdlc.adapters.subscriber.mlflow_trace.mlflow.start_span_no_context"` (Commit 1 concern — include in that commit's sweep)
- Delete `adapters/github.py`.

This is the one commit that loses blame continuity across the split. Acceptable — the file is recent.

### Commit 3 — Move `PipelineEvent` to `domain/`

- Create `src/a2sdlc/domain/pipeline_event.py` with the dataclass
- Update all import sites — found by grep now so we know the exact set:
  - `src/a2sdlc/adapters/work/github.py` (currently `adapters/github.py`)
  - `src/a2sdlc/adapters/work/local_file.py`
  - `src/a2sdlc/adapters/work/__init__.py` (re-export drops `PipelineEvent`)
  - `src/a2sdlc/pipeline/dispatch.py`
  - `src/a2sdlc/adapters/__init__.py` (drop `PipelineEvent` re-export)
  - `tests/fakes.py`
  - `tests/adapters/test_pipeline_event.py` → moves to `tests/domain/test_pipeline_event.py` (Commit 3 runs before Commit 4's test-mirror reshuffle, so the source path is still flat at this point)
  - `tests/pipeline/test_dispatch_e2e.py`
  - `tests/adapters/test_gh_comment_subscriber.py` → update to new path
  - `tests/lifecycle/test_comment.py` → update to new path
- Import-linter: no new rule needed; `domain/` is already allowed as an import target for everyone. Verify the existing "domain is pure" contract still passes (no `domain.pipeline_event` imports anything from `adapters/`, `pipeline/`, etc.).

### Commit 4 — Mirror test layout

- `git mv` test files into their new subfolders with renames.
- Add empty `__init__.py` to each new test subfolder (matches existing `tests/adapters/__init__.py` convention).
- Rename `test_subscriber_protocol.py` → `test_protocol.py` inside the new `subscriber/` test folder. Name was overclaiming before.
- Final grep pass: `rg -n 'patch\(["\047]a2sdlc\.adapters\.' tests/` and `rg -n 'logger=["\047]a2sdlc\.adapters\.' tests/` to ensure no lingering string references to dead module paths. Commits 1–3 should have caught them all; this is belt-and-suspenders.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Stale imports break runtime | `make check` runs ty + tests; ty catches structural errors; tests catch runtime ones. Green gate is the merge criterion. |
| **String-form module references** (`patch("a2sdlc.adapters.X")`, `caplog.at_level(logger="a2sdlc.adapters.X")`, hardcoded `logging.getLogger("a2sdlc.adapters.X")`) are **not** caught by ty and fail only at test-run time with confusing errors. Commits 1 and 2 explicitly sweep them; the final grep in Commit 4 is the backstop. |
| Import-linter contract drift | Review `pyproject.toml` `ignore_imports` line-by-line. The `adapters.protocols -> evaluation.progress` entry appears in **two** contracts — rename both. Run `uv run lint-imports` at each commit boundary. |
| Git blame discontinuity on `github.py` split | Accepted. File is recent, Denis knows the history, `git log --follow` still works on single-file renames. |
| Downstream live specs/plans referencing old module paths | **Live specs must update** (the `2026-04-18-transcript-log-subscriber-design.md` references `adapters.mlflow_trace_subscriber` — update to `adapters.subscriber.mlflow_trace`). **Already-executed plans stay as-is** — they're history, not living docs; editing them would mislead future readers about what actually shipped. Scope the grep to `src/`, `tests/`, and the live specs. |
| Circular imports during migration | Subfolder `__init__.py`s should import from their own submodules only. Cross-kind imports (e.g. factory importing from all kinds) stay at the top-level `adapters/`. |
| `coverage-diff` false positives on moved lines | `make check` runs `diff-cover` against moved lines. Pure `git mv` should register as renames and not trigger "new uncovered lines." If it does flag something, investigate the specific file before suppressing — a real miss vs. a rename-detection quirk matters. |

## Testing

No new tests. Success criterion is **all existing 527 tests still pass** after each commit. If one fails, it's an import miss — fix the import, don't rewrite the test.

## Acceptance

- **All tests pass** after each of the four commits (use current test count as baseline — record it before Commit 1 and assert equality after Commit 4 to catch accidental deletions during moves).
- `make check` green at each commit boundary.
- `find src/a2sdlc/adapters -name '*.py' | xargs grep -l 'class.*Protocol' | sort` returns exactly 5 files (git, work, review, subscriber, runner `__init__.py`s). `protocols.py` is gone.
- **No references to fully-renamed flat modules remain anywhere (src, tests, live specs):**
  ```
  rg -n 'a2sdlc\.adapters\.(protocols|console_subscriber|gh_actions_subscriber|gh_comment_subscriber|mlflow_trace_subscriber|local_branch_git|local_file_work|local_noop_review)\b' src tests docs/superpowers/specs
  ```
  Must return **zero** lines. These former modules have no new-path collision — any match is stale.
- **No direct references to `a2sdlc.adapters.github` module (the old flat file):**
  ```
  rg -n 'a2sdlc\.adapters\.github\b' src tests docs/superpowers/specs
  ```
  Must return **zero** lines. New paths are `adapters.work.github`, `adapters.review.github`, `adapters._github` — grep uses `\b` word boundary so it won't match those.
- `PipelineEvent` lives under `a2sdlc.domain.pipeline_event`; `rg "from a2sdlc.adapters.*PipelineEvent" src tests` returns nothing.
- No lingering string-form module references: `rg 'patch\(["\047]a2sdlc\.adapters\.(protocols|console_subscriber|gh_actions_subscriber|gh_comment_subscriber|mlflow_trace_subscriber|local_branch_git|local_file_work|local_noop_review|github)\b' tests` and `rg 'logger=["\047]a2sdlc\.adapters\.(local_file_work|github|local_noop_review)\b' tests src` both return zero lines.

## Out of scope / follow-ups

- Tests for the `StageRunner` Protocol: currently exercised only indirectly. No new tests added by this cleanup.
- Splitting `tests/adapters/test_factory.py` by kind: stays top-level; factory composes across kinds so it doesn't fit one subfolder.
- Moving `factory.py` or `retry.py` into subfolders: they're cross-kind; top-level is the right home.
- A future decision about whether `Approval` and `ReviewComment` should live in `domain/` alongside `PipelineEvent`: plausible, but they're less cross-cutting (only consumed by review code paths). Leave in `review/__init__.py` for now.
