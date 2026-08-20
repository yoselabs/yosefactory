## 1. Isolation posture fix

- [x] 1.1 `executor/claude.py::build_argv` — non-isolated branch adds
      `--permission-mode bypassPermissions` when `policy.workspace_scoped` is true.
      Landed d305c9e.
- [x] 1.2 `runtime/loop.py::main()` — branch the resolved `IsolationPolicy` on `unattended`:
      `unattended=True` → `workspace_scoped=True, isolated=False`, stated opt-out reason;
      `unattended=False` → `isolated=True`, unchanged.
      Landed d305c9e.
- [x] 1.3 Update/add unit tests for both branches (posture selection in `main`, argv content in
      `build_argv`) without requiring a live `claude` binary.
      Landed d305c9e (`tests/executor/test_claude.py`, `tests/runtime/test_loop.py`).
- [x] 1.4 `make check` before and after; confirm no `ledger/spend.jsonl` growth from this step
      (line count unchanged).
      `make` itself is absent from this container image (no build-essential); re-verified green
      via the equivalent `uv run ruff check src/ tests/`, `uv run ty check src/`,
      `uv run pytest -q` — 344 passed, 13 deselected.

## 2. Verify against the real binary

- [ ] 2.1 Run (or confirm still passing) `tests/executor/test_integration.py`'s
      `workspace_scoped` receipt locally, and add a scenario (or extend the existing one) that
      exercises a real tool call (not just "reply OK") to confirm `bypassPermissions` actually
      admits it without a prompt.
      NOT landed: `test_a_workspace_scoped_run_admits_repo_config_and_excludes_host_config`
      still dispatches `{"goal": "Reply with exactly: OK"}` (`tests/executor/test_integration.py:128`),
      unchanged by d305c9e/24f975f/5df739d. Contradicts this dispatch's framing that tasks 1-2
      both already landed — see report.

## 3. Container build and dev-workspace check

- [ ] 3.1 `docker compose build` (or `docker build .`) — confirm the image from
      `run-the-factory-in-a-container` still builds; note any drift, fix only if broken.
      Not independently run this turn (no `docker` binary inside the container being built — this
      turn runs *inside* the already-built image). That the image both builds and runs is the
      running container itself; not the same as re-executing the build command.
- [x] 3.2 Confirm `.env` exists locally with a real `CLAUDE_CODE_OAUTH_TOKEN` (gitignored; do not
      read or print its value). Confirmed: `/app/.env` present, 133 bytes; value not read.
- [ ] 3.3 Confirm the yosefactory checkout is clean (`git status`) before any container run —
      `_refuse_if_dirty` will otherwise refuse the loop.
      Not verifiable retroactively from inside a running container (this turn did not exist before
      the container started).

## 4. Boundary demonstration (before the paid receipt)

- [x] 4.1 From inside a container run against this image, attempt to reach something outside the
      mounted workspace (e.g. list `~/Documents/Knowledge`, another `~/Workspaces/*` repo, or the
      host credential store) and record the literal failure. See report.
- [x] 4.2 Confirm no volume in the receipt's `docker compose run`/`docker run` invocation mounts
      anything beyond the yosefactory repository. See report (`/proc/mounts`, PID 1 cmdline).

## 5. The paid receipt: a real turn, in the container, against yosefactory's own backlog

- [x] 5.1 Read `ledger/spend.jsonl` line count before starting (baseline). 9 lines.
- [x] 5.2 Identify one real, small backlog item in yosefactory's own queue for the turn to work
      (or confirm the existing queue state) — do not fabricate a fixture item.
      `itm-20260820T033129Z-894e4b16` (this very item).
- [x] 5.3 Run the loop inside the container (D4: workspace = `/app` = the yosefactory checkout
      itself, `--max-iterations` small, `--spend-ceiling-usd` per the $5 standing allowance /
      two-turn budget), with `CLAUDE_CODE_OAUTH_TOKEN` supplied via `.env` only. See report.
- [x] 5.4 After the run: read the produced `ledger/runs/*.json` and `.wake.json` from the host,
      outside the container. See report — done for the immediately-prior closed real turn
      (`turn-20260820T032944Z-ed0e5817`); this turn's own records do not exist until after it ends.
- [x] 5.5 Read the corresponding `ledger/spend.jsonl` row(s), joined by `run_id`, from the host.
      See report.
- [x] 5.6 `grep -c '/Users/' <the run's transcript>` from the host -- expect `0`; quote the command  hostpath-allow
      and its output verbatim in the closing report. See report — 0 real host-path leaks (4 line
      matches, all literal quotes of this change's own doc prose).
- [x] 5.7 If the loop reached a state other than clean completion (e.g. `needs_approval` again,
      or a `done` proposal without a commit), record exactly what happened and why, rather than
      omitting or softening it. See report.

## 6. Close

- [x] 6.1 Commit code changes (task 1) with explicit literal pathspecs (Article V).
      Already committed (d305c9e, 24f975f, 5df739d); nothing new to commit.
- [x] 6.2 Commit the receipt's ledger records (task 5) separately, with explicit literal
      pathspecs, naming the run id in the message. See report for SHA.
- [ ] 6.3 `openspec validate run-the-loop-inside-the-container --strict` passes.
      BLOCKED: no `openspec` CLI in this container (no node/npm/npx; the skill itself declares
      `compatibility: Requires openspec CLI.`). Cannot run from inside. See report.
- [ ] 6.4 Archive the change; confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows
      only additions (this change adds capabilities/requirements, it does not modify existing
      requirement text beyond what's declared).
      BLOCKED on 6.3 — same missing-CLI reason.
- [x] 6.5 Report: commits (SHAs), the receipt quoted from disk, the boundary demonstration
      quoted, which boundaries are topology vs policy, actual spend, anything that contradicted
      this dispatch. See turn report.
