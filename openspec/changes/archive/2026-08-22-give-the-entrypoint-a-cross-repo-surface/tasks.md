## 1. CLI surface

- [x] 1.1 Add `--queue` and `--workspace` (optional `Path`, default `None`) to `main`'s argparse
      surface in `src/yosefactory/runtime/loop.py`.
- [x] 1.2 Add `--test-command` (optional `str`, `shlex.split` when given, default
      `verify.DEFAULT_TEST_COMMAND` unchanged) and thread it through to `run_loop`'s
      `test_command` kwarg.
- [x] 1.3 Add `--cost-ceiling-usd` (optional `float`, default `None`) and wire it into the
      `Guardrails(...)` construction as `cost_ceiling_usd=args.cost_ceiling_usd`. Do not touch
      `--spend-ceiling-usd` or `LoopBound`.

## 2. Places construction

- [x] 2.1 Replace `places = Places.local(repo)` with resolution: `queue = (args.queue or
      args.repo).resolve()`, `workspace = (args.workspace or args.repo).resolve()`.
- [x] 2.2 When `queue == workspace`, build `Places` exactly as `Places.local` does today (same
      lock file for both roles) — confirm via a test asserting field-for-field equality with
      `Places.local(repo)` for the omitted-flags case.
- [x] 2.3 When `queue != workspace`, build `Places` with `ledger=queue/RUNS`,
      `queue_lock=queue/LOCK`, `workspace_lock=workspace/".git"/"yosefactory-turn.lock"`.
- [x] 2.4 Keep the existing `unattended` publish-boolean wiring (`--publish` sets both
      `publish_queue`/`publish_workspace`) unchanged and applying to whichever `Places` was built.

## 3. Spec delta

- [x] 3.1 `specs/containerized-loop/cross-repo-invocation/spec.md` — already drafted; confirm it
      matches the shipped behavior once 1-2 land (adjust wording only, not requirements, unless
      implementation forces a real behavior change — if it does, that is Article VII and gets
      reported, not silently absorbed).

## 4. Tests

- [x] 4.1 Unit: omitting `--queue`/`--workspace` produces a `Places` identical to
      `Places.local(repo)` (mirrors the existing `test_a_supplied_ceiling_is_identical_via_either_
      entrypoint` pattern of capturing `run_loop`'s kwargs via `monkeypatch`).
- [x] 4.2 Unit: `--cost-ceiling-usd` reaches `Guardrails.cost_ceiling_usd`; `--spend-ceiling-usd`
      still reaches `LoopBound.spend_ceiling_usd`; giving both on one invocation leaves each where
      it belongs (capture `limits` from the faked `run_loop`/`take_turn` call).
- [x] 4.3 Unit: `--test-command "make check"` reaches `run_loop`'s `test_command` kwarg as
      `("make", "check")`; omitted, it is `DEFAULT_TEST_COMMAND`.
- [x] 4.4 **The end-to-end receipt this change exists for**: two temporary git repositories (queue,
      workspace), an item seeded in the queue, `main(["--queue", str(queue), "--workspace",
      str(workspace), "--max-iterations", "1", ...])` invoked with a fake executor that makes one
      real commit in the workspace, asserting: the turn record lands under
      `queue/RUNS/`, the workspace commit lands in the workspace repo (not the queue repo), and
      neither repo's git history contains the other's commits. Follows
      `tests/runtime/test_turn_integration.py`'s existing cross-repo fixture pattern if one already
      covers `take_turn` directly — reuse it rather than inventing a second one for the CLI layer.
- [x] 4.5 Regression: every existing `test_loop.py` invocation that omits the new flags still
      passes unmodified — the collapsed single-repo case is untouched.

## 5. Verify by construction against the driver's inventory

- [x] 5.1 Walk `design.md`'s driver-inventory table line by line against the shipped flags; for
      any row that cannot actually be expressed, stop and report it in the closing report rather
      than declaring the surface complete.
- [x] 5.2 `make check` green.

## 6. ADR

- [x] 6.1 Write `decisions/00NN-*.md` (next available number) recording: the two-flag collapse
      (5 seams + 2 booleans -> `--queue`/`--workspace`) versus exposing every `Places` field
      individually; the two-ceiling naming decision; and the `Revisit trigger:` — e.g. "a second
      cross-repo caller needs a workspace_lock convention other than `.git/yosefactory-turn.lock`,
      or needs `publish_queue`/`publish_workspace` independently."

## 7. Archive

- [x] 7.1 `openspec validate give-the-entrypoint-a-cross-repo-surface --strict` passes.
- [x] 7.2 Archive the change; confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows
      only additions (this change adds a capability, modifies none).
