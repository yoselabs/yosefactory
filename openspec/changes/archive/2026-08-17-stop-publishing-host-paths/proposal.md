## Why

`wire-the-board-into-the-turn-cycle` (archived, unpushed) committed the raw agent transcript for
two live turns — `ledger/runs/<run_id>.stream.jsonl` — into git for the first time. The raw stream
is the executor's own stdout, unfiltered: it carries whatever the agent read or wrote that turn,
including 53 occurrences of the operator's absolute home directory, a reference to the local
knowledge-base path, and the name of a private, unrelated repo. `protocol/turn.py`'s `TurnRecord`
already refuses a home-rooted path at write time (`_HOME_ROOTED`); the raw stream never passes
through that check, because it is not a `TurnRecord` — it is a separate file the executor writes
directly (`executor/claude.py::run`).

This repository is public. Nothing has been pushed yet, so nothing has actually leaked — but all
17 unpushed commits sit on `main`, and a push publishes them as committed. That window is the only
reason this is cheap: a history rewrite before any third party has seen the commits costs nothing;
after a push it costs a coordinated force-push and a "sorry, please re-clone."

## What Changes

- **Raw transcripts are never committed.** `ledger/runs/*.stream.jsonl` is gitignored. The file
  still gets written to the same path by `executor/claude.py` — untracked, not deleted — so it
  remains available on disk as evidence for whoever ran the turn. See Decision 1 in `design.md`
  for why this was chosen over redacting the stream at write time or moving it to a second mount.
- **A new guard, `tools/hooks/forbid-host-paths.py`,** refuses a commit whose staged content
  contains an absolute path rooted at `/Users/`, `/home/`, or `/root` (the same pattern
  `protocol/turn.py::_HOME_ROOTED` already enforces for turn records, applied here to every staged
  file), or whose staged path matches `ledger/runs/*.stream.jsonl` directly (the belt to the
  gitignore's suspenders, for `git add -f`). Wired both as a `prek` pre-commit hook (`--staged`,
  fast, every commit) and as `make guard-host-paths` (`--committed`, the tip commit's own diff —
  still catches a `--no-verify` commit the next time it runs).
- **History rewrite.** The two already-committed transcripts are removed from the two unpushed
  commits that added them (`149ae78`, `d211ae9`), via `git filter-repo`. Every other commit's
  message and content is preserved unchanged; only these two files are gone from history. `main`
  is not rewound past `origin/main` — every SHA already on the remote is untouched (nothing to
  rewrite there; the two offending commits are both unpushed).
- **New spec capability, `run-guardrails/transcript-publication`,** stating the two requirements
  above (`.stream.jsonl` never committed; a staged host path is refused) so they are checked, not
  merely remembered.

## Non-goals

- **Not a redaction pipeline.** No attempt to scrub host paths out of the transcript stream at
  write time and commit the scrubbed result — argued against in `design.md` Decision 1.
- **Not a general secrets scanner.** This guard is scoped to the one class of leak this incident
  produced: a host-rooted absolute path. It does not look for credentials, tokens, or arbitrary
  PII, and does not replace a dedicated secret-scanning tool if one is ever adopted.
- **Not a full-tree historical audit as an ongoing check.** `make guard-host-paths` reads only the
  tip commit's diff, deliberately — see `_committed_paths`'s own docstring in the script for why a
  full-tree scan would misfire against this repo's own legitimate mentions of `/root/` and
  `/home/` (the Dockerfile, the guard's own regex, the parametrized test fixtures).
- **Not a rewrite of anything on `origin/main`.** Confirmed via `git log origin/main..HEAD` before
  touching history; only unpushed commits are rewritten.
- **Not `protocol/turn.py::_HOME_ROOTED` itself.** It already does its job for `TurnRecord`; this
  change adds a second, independent check for everything else, rather than trying to route the raw
  stream through the first one.

## Impact

- `.gitignore` — one new entry.
- `tools/hooks/forbid-host-paths.py` — new.
- `tests/scripts/test_forbid_host_paths.py` — new.
- `.pre-commit-config.yaml` — one new hook.
- `Makefile` — one new target, `guard-host-paths`.
- `openspec/specs/run-guardrails/transcript-publication/spec.md` — new capability.
- Git history: two unpushed commits rewritten (transcript blobs removed; messages and every other
  file unchanged). SHAs for those two commits and everything after them change — reported in
  `tasks.md` with the old→new mapping.
- **Real spend budget: $0.** This is git and policy; no `claude` invocation is needed to verify it.
