## 1. Preflight — verify before acting (Article XII)

- [x] 1.1 Confirmed clean on both repos before starting; a2web on `main`. yosefactory carried
      pre-existing unpushed history (unaffected — no push in this change).
- [x] 1.2 `yosefactory-factory:latest` present; `.env` carries `CLAUDE_CODE_OAUTH_TOKEN` (presence
      checked, value never read).
- [x] 1.3 Confirmed `hepsiburada.com` still absent from `_JS_HEAVY_HOSTS_SEED` and task 7.5
      (`a2web-cid`) still unclaimed.

## 2. The driver script

- [x] 2.1-2.6 `scripts/run_a2web_turn.py` written: seeds one `ready` item, constructs cross-repo
      `Places(queue=/app, workspace=/data/a2web, publish_workspace=False, publish_queue=False)`,
      `IsolationPolicy(isolated=False, workspace_scoped=True)`, calls `take_turn` once with
      `test_command=("make", "check")`, prints the `TurnRecord`.
      **Finding, not fixed:** the script never passes `isolated=` to `take_turn` (default `True`),
      so every `TurnRecord.isolated` field from this change reads `true` even though the actual
      invocation used `workspace_scoped`/`bypassPermissions` — the same wiring gap
      `add-cross-repo-workspace`'s own review comment on `runtime.loop.main` names and fixes for
      the single-repo CLI path (`isolated=policy.isolated`). Not fixed here — this script is a
      one-off, not the CLI surface that comment was written against; recorded so the record's own
      field is not misread as evidence about which posture ran (the `opt_out_reason` string in the
      transcript is the accurate source).

## 3. Container invocation — two mounts, deliberately

- [x] 3.1-3.2 Ran via explicit `docker run` (not `docker compose run`) against
      `yosefactory-factory:latest`, mounting exactly `~/Workspaces/yosefactory:/app` and
      `~/Workspaces/a2web:/data/a2web` — the shipped compose file's default third mount
      (`./.dev-workspace:/data/workspace`) was deliberately avoided by not using `docker compose
      run`, since that default is itself a live git repo on this host and mounting it would have
      been a third, undeclared reach.

## 4. The boundary demonstration

- [x] 4.1-4.2 Inside the same container invocation as the turn: `cat /Users/iorlas/Documents/Knowledge/CLAUDE.md` fails with `No such file or directory`; `ls /Users` fails with  hostpath-allow
      `cannot access '/Users': No such file or directory`; `ls /data` → `a2web` only. Full output
      quoted in the closing report.

## 5. The receipt

- [x] 5.1-5.6 Two real turns ran, quoted in full in the closing report:
  - **Turn 1** (`turn-20260820T072444Z-1092bcd7`, $0.7187): the agent did real work and committed
    it (a2web `25d2ccb`, branch `add-hepsiburada-js-heavy-host`) — then the platform's own
    `verify.may_write_done` crashed (`'make' is not on PATH`) before it could write a terminal
    record. **Root-caused and fixed**: `Dockerfile` never installed `make`, because no prior
    receipt ever ran a foreign repository's own `test_command`. Fixed narrowly (added `make` to
    the existing `apt-get install` line), image rebuilt.
  - **Turn 2** (`turn-20260820T073255Z-f65e695c`, $0.6042), after the fix: the agent again did real
    work correctly, committed it (a2web `fd24220`, branch `fix-hepsiburada-js-heavy-host`), and
    **proposed `done` correctly this time** — `may_write_done` ran for real and reported `failed`:
    5 of a2web's own tests failed. **Root-caused, not fixed**: those 5 failures are pre-existing
    and unrelated to the change — confirmed by running `make check` against the identical commit
    on the host (0 failures, 92.14% coverage) and a second time inside the same container as a
    diagnostic (same 5 failures, byte-identical test names). The container image installs none of
    a2web's own optional browser-backend test extras (`patchright`/`zendriver`); 5 of a2web's tests
    require them regardless of what change is made. Installing a foreign repository's full browser
    stack into this image is out of this change's scope (proposal.md Non-goals) — reported here
    instead.
  - Neither turn reached `Outcome.ADVANCED`. **D014's clock did not start on this run.**
  - Both items closed cleanly (`failed`, retryable) rather than left dangling in `doing` — turn 1's
    crash left no `_dispose` path to close the item automatically (a real gap, see design.md
    addendum); turn 2's clean `failed` outcome likewise leaves the item non-terminal by the
    platform's own design (`_dispose`'s `failed()` path commits the ledger record but does not
    append an event to the item) — both closed by hand, same as the platform's own `note`/`failed`
    vocabulary would, with the reason stated in full.

## 6. Spend and close

- [x] 6.1 `ledger/spend.jsonl`: 12 rows before this change, 14 after (+2, matching the two turns
      above: $0.7187 + $0.6042 = $1.3229). `make check` itself added zero rows.
- [x] 6.2 `git diff --cached` confirmed empty after every commit in this change.
- [ ] 6.3 `openspec validate run-a-turn-against-a2web --strict` — run before archiving.
- [ ] 6.4 `make check` in yosefactory — confirm still green, $0.
- [ ] 6.5 Commit this change's own files with explicit literal pathspecs.
- [ ] 6.6 Archive.
