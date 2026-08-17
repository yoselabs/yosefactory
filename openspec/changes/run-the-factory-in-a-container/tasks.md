## 1. Read and re-acquire, and retire the superseded change

- [x] 1.1 `orchestration.md`, the coordinator's container dispatch (supersedes the launchd one),
      `runtime/loop.py`, `executor/claude.py`, `executor/outcome.py`, `executor/stream.py`
- [x] 1.2 Retired `add-scheduled-loop`: deleted its change directory (never archived, nothing
      promoted — clean retirement, not a MODIFIED block) and `ops/launchd/` entirely
- [x] 1.3 Credentials investigated FIRST, before building anything: found the keychain-vs-container
      gap, messaged the director, held the billed receipt — then Denis's ruling (D021,
      `CLAUDE_CODE_OAUTH_TOKEN`) and his supplied `.env` arrived; incorporated without ever reading
      the value

## 2. Carry forward `scheduled_main` / `[project.scripts]`

- [x] 2.1 Re-applied from the deleted `add-scheduled-loop` (nothing to fold — that change was never
      archived, so no promoted spec exists to conflict with re-adding the same code here):
      `runtime.loop.main(unattended=...)`, `scheduled_main()`, `pyproject.toml`
      `[project.scripts]`
- [x] 2.2 New: `_refuse_if_dirty` startup guard in `run_loop` — checks `places.workspace` via
      `git status --porcelain`, raises `LoopError` naming the dirty path before any `take_turn`
      call

## 3. Docker

- [x] 3.1 `Dockerfile`: `python:3.12-slim`, `uv` installed, `claude` installed pinned to
      `executor.claude.PINNED_VERSION` via Anthropic's own installer, `git safe.directory`
      configured, `UV_PROJECT_ENVIRONMENT` outside `/app`, package synced
- [x] 3.2 `docker-entrypoint.sh`: checks `CLAUDE_CODE_OAUTH_TOKEN` set and non-empty (never prints
      it), exits naming the variable if missing, otherwise execs the given command. **Scoped to
      the loop entrypoints only** (`yosefactory-loop`/`yosefactory-loop-scheduled`), not every
      command — `claude --version` and diagnostic `python -c` calls need to work without a token
      for task 3.6's own verification
- [x] 3.3 `docker-compose.yml`: source bind-mounted to `/app` (dev), queue/workspace bind-mounted
      to a **separate** path (`./.dev-workspace` — gitignored), `env_file: .env`, default
      `command:` invoking `yosefactory-loop-scheduled` against the separate path with the shipped
      ceiling/iteration defaults
- [x] 3.4 `.dockerignore`: excludes `.venv/`, `.git/`, `__pycache__/`, `.env` (defense in depth —
      never send the secret to the build context either)
- [x] 3.5 `.env.example`: `CLAUDE_CODE_OAUTH_TOKEN=` with a provenance comment, nothing else
- [x] 3.6 Verified: image builds; `claude --version` inside a container reports `2.1.225` exactly;
      `uv run python -c "import yosefactory"` succeeds with the venv at `/opt/venv`, outside `/app`;
      a probe module added to `src/` on the host **after** the image was built imports successfully
      inside the running container with zero rebuild between the edit and the check

## 4. Tests — every receipt in this section costs $0

- [x] 4.1 `_refuse_if_dirty`: dirty workspace refuses before any turn; clean workspace unaffected;
      error names the path (3 new tests, `tests/runtime/test_loop.py`)
- [x] 4.2 `scheduled_main`/`main` tests carried forward from `add-scheduled-loop` re-verified green
      in this change's tree — 19/19 in `test_loop.py`
- [x] 4.3 `make check`: `ledger/spend.jsonl` — 3 lines before, 3 after. 291 passed, 11 deselected.

## 5. The end-to-end receipt (Article XVI) — two parts, credential-gated on the second only

- [x] 5.1 **In-container, at $0 — done.** `docker compose run --rm factory
      yosefactory-loop-scheduled /data/workspace --owner scheduler --max-iterations 1
      --spend-ceiling-usd 0.50` against `./.dev-workspace` (seeded with one `snoozed` item —
      **correction to the plan below**: a truly empty backlog is not free, `take_turn` starts a
      real planning turn against it; nothing-ready needs a held-back item, matching
      `add-turn-loop`'s own test fixture). Read from the **host**, container long exited:
      `.dev-workspace/ledger/runs/20260817T021936Z-....json` (`outcome: nothing-ready`) and its
      `.wake.json` (`wake: startup`); `ledger/spend.jsonl` does not exist in that workspace —
      never created, consistent with $0.
- [x] 5.2 **Messaged the director before attempting the billed run.** The first real executor call
      this change made (the mis-seeded empty-backlog planning turn above, before the seed
      correction) came back `api status 401` — before any billing occurred (`spend: $0.0000`).
      Confirmed the token itself reaches the container (`[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]` → set,
      length 58, never printed) and that `claude auth status` inside the container reports
      `{"loggedIn": true, "authMethod": "oauth_token", "apiProvider": "firstParty"}` — so this is
      not a wiring defect on this change's side. Reported to the director; **held**, per Article
      XVI's own instruction not to claim a receipt not held.
- [x] 5.3 **Money path, once — done.** 401 was a truncated-token paste (58 of 108 chars), Denis
      regenerated it, director confirmed via length-only check (never the value). Re-verified
      presence + length (108) in-container before running. One real `ready` item seeded in
      `.dev-workspace` (no-op-shaped frame — "reply with exactly OK, do not touch any file"),
      `docker compose run --rm factory yosefactory-loop-scheduled /data/workspace --owner
      scheduler --max-iterations 1 --spend-ceiling-usd 0.50`. Real turn ran, real cost:
      `spend: $0.1633`. Read from the **host**, container long exited:
      `.dev-workspace/ledger/runs/20260817T023131Z-....json` (`outcome: failed`, `note: "...the
      agent wrote no proposal"` — expected, given the deliberately no-op frame; proves the
      auth→executor→record path, not a successful task) and its `.wake.json`
      (`wake: startup`). The spend row itself landed in **this checkout's own**
      `ledger/spend.jsonl` (`runtime/spend.py`'s own documented design — see design.md Money,
      "found while building the receipt"), joinable to the `.dev-workspace` ledger record by
      `run_id` across the two repos: `turn-20260817T023131Z-921dc1f7`, `$0.163275`. One shot, not
      a debugging loop, per the director's constraint.
- [x] 5.4 Token handling verified throughout: every check was presence-only
      (`[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]`, `${#CLAUDE_CODE_OAUTH_TOKEN}` length only); no command
      run during this change printed, logged, or echoed the value; `.env` confirmed present,
      gitignored (`git check-ignore` → `.gitignore:14`) and untracked (`git ls-files` — no match)
      without reading its contents
- [x] 5.5 Two findings folded into design.md per the director's instruction: **S194 instance**
      (`claude auth status`'s `loggedIn: true` reported presence, not validity — the truncated
      token that caused the first 401 read as logged-in right up until the real call), and
      **S987** (an empty backlog is a billed planning turn, not a free `nothing-ready` — named as
      a known, unaddressed cost with three candidate remedies, explicitly not built here; the
      ~$0.285/turn and ceiling figures are not extrapolated into an idle-cost estimate, because no
      empty-backlog planning turn has ever completed and billed to measure from)

## 6. Close

- [ ] 6.1 `openspec validate run-the-factory-in-a-container --strict` passes
- [ ] 6.2 Committed: change directory, `pyproject.toml`, `src/yosefactory/runtime/loop.py`,
      `tests/runtime/test_loop.py`, `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`,
      `.dockerignore`, `.env.example` — explicit literal pathspecs, `-F <message-file>`,
      `PREK_ALLOW_NO_CONFIG=1`, `git diff --cached` confirmed empty after. `ops/launchd/`'s
      deletion recorded in the commit message (Article XIV: deletions outside a MODIFIED block
      must be named — this deletion is of files this repo has never archived/promoted, so it is
      not a spec deletion, but naming it keeps the commit honest about what left the tree)
- [ ] 6.3 Archived; `openspec validate --specs --strict` passes; `containerized-loop/
      dev-and-production` promoted clean
- [ ] 6.4 Reported to director: commits, `make check` $0 proof, the in-container receipt (what ran
      it, the disk-read artefact, from the host), the billed receipt's outcome (or the stated gap
      if still blocked), quota-legibility finding, token-handling confirmation, anything found
      that contradicts this dispatch
