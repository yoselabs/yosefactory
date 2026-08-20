## 1. Isolation posture fix

- [ ] 1.1 `executor/claude.py::build_argv` — non-isolated branch adds
      `--permission-mode bypassPermissions` when `policy.workspace_scoped` is true.
- [ ] 1.2 `runtime/loop.py::main()` — branch the resolved `IsolationPolicy` on `unattended`:
      `unattended=True` → `workspace_scoped=True, isolated=False`, stated opt-out reason;
      `unattended=False` → `isolated=True`, unchanged.
- [ ] 1.3 Update/add unit tests for both branches (posture selection in `main`, argv content in
      `build_argv`) without requiring a live `claude` binary.
- [ ] 1.4 `make check` before and after; confirm no `ledger/spend.jsonl` growth from this step
      (line count unchanged).

## 2. Verify against the real binary

- [ ] 2.1 Run (or confirm still passing) `tests/executor/test_integration.py`'s
      `workspace_scoped` receipt locally, and add a scenario (or extend the existing one) that
      exercises a real tool call (not just "reply OK") to confirm `bypassPermissions` actually
      admits it without a prompt.

## 3. Container build and dev-workspace check

- [ ] 3.1 `docker compose build` (or `docker build .`) — confirm the image from
      `run-the-factory-in-a-container` still builds; note any drift, fix only if broken.
- [ ] 3.2 Confirm `.env` exists locally with a real `CLAUDE_CODE_OAUTH_TOKEN` (gitignored; do not
      read or print its value).
- [ ] 3.3 Confirm the yosefactory checkout is clean (`git status`) before any container run —
      `_refuse_if_dirty` will otherwise refuse the loop.

## 4. Boundary demonstration (before the paid receipt)

- [ ] 4.1 From inside a container run against this image, attempt to reach something outside the
      mounted workspace (e.g. list `~/Documents/Knowledge`, another `~/Workspaces/*` repo, or the
      host credential store) and record the literal failure.
- [ ] 4.2 Confirm no volume in the receipt's `docker compose run`/`docker run` invocation mounts
      anything beyond the yosefactory repository.

## 5. The paid receipt: a real turn, in the container, against yosefactory's own backlog

- [ ] 5.1 Read `ledger/spend.jsonl` line count before starting (baseline).
- [ ] 5.2 Identify one real, small backlog item in yosefactory's own queue for the turn to work
      (or confirm the existing queue state) — do not fabricate a fixture item.
- [ ] 5.3 Run the loop inside the container (D4: workspace = `/app` = the yosefactory checkout
      itself, `--max-iterations` small, `--spend-ceiling-usd` per the $5 standing allowance /
      two-turn budget), with `CLAUDE_CODE_OAUTH_TOKEN` supplied via `.env` only.
- [ ] 5.4 After the run: read the produced `ledger/runs/*.json` and `.wake.json` from the host,
      outside the container.
- [ ] 5.5 Read the corresponding `ledger/spend.jsonl` row(s), joined by `run_id`, from the host.
- [ ] 5.6 `grep -c '/Users/' <the run's transcript>` from the host -- expect `0`; quote the command  hostpath-allow
      and its output verbatim in the closing report.
- [ ] 5.7 If the loop reached a state other than clean completion (e.g. `needs_approval` again,
      or a `done` proposal without a commit), record exactly what happened and why, rather than
      omitting or softening it.

## 6. Close

- [ ] 6.1 Commit code changes (task 1) with explicit literal pathspecs (Article V).
- [ ] 6.2 Commit the receipt's ledger records (task 5) separately, with explicit literal
      pathspecs, naming the run id in the message.
- [ ] 6.3 `openspec validate run-the-loop-inside-the-container --strict` passes.
- [ ] 6.4 Archive the change; confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows
      only additions (this change adds capabilities/requirements, it does not modify existing
      requirement text beyond what's declared).
- [ ] 6.5 Report: commits (SHAs), the receipt quoted from disk, the boundary demonstration
      quoted, which boundaries are topology vs policy, actual spend, anything that contradicted
      this dispatch.
