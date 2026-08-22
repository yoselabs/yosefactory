# ADR-0008 — A pre-commit guard refuses staged host paths, with a per-line `hostpath-allow` marker

**Status:** Accepted
**Date:** 2026-08-17
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a dedicated secrets/PII scanner is adopted for this repo — at that point this
guard's narrower, host-path-only scope should be re-examined for whether it becomes redundant or
stays as a cheaper, faster-running first check ahead of the broader one.

## Context

`wire-the-board-into-the-turn-cycle` (archived, unpushed at the time) committed the raw agent
transcript for two live turns (`ledger/runs/<run_id>.stream.jsonl`) into git — the executor's own
unfiltered stdout, which carries whatever the agent read or wrote that turn. It held 53 occurrences
of the operator's absolute home directory, a knowledge-base path, and the name of a private,
unrelated repository. `protocol/turn.py::_HOME_ROOTED` already refused a home-rooted path for
`TurnRecord`, but the raw stream never passes through that check — it is a separate file the
executor writes directly.

This repository is public (`CLAUDE.md` D005). The two offending commits were unpushed when found,
which is the only reason the fix was cheap: a history rewrite before any third party sees the
commits costs nothing; after a push it costs a coordinated force-push.

## Decision

`tools/hooks/forbid-host-paths.py` runs two independent checks, either sufficient to refuse a
commit:

1. **Path-based** — no staged path may match `ledger/runs/*.stream.jsonl` (belt to the
   accompanying `.gitignore` entry's suspenders, for a `git add -f` that bypasses it).
2. **Content-based** — no staged file's text may contain a literal path rooted at `/Users/`,
   `/home/`, or `/root`, the same pattern `_HOME_ROOTED` already enforces for turn records,
   checked line by line across every staged file.

A line ending in the literal marker `hostpath-allow` is exempt from check 2 — the sanctioned way to
write a genuine pattern example (this script's own regex line, its test fixtures, a design doc
naming the syntax) without either tripping the guard on itself or silently blessing every line in
the file. The marker is per-line, typed deliberately, and is not a path allowlist: an unrelated
real leak added later in the same file is still caught.

Two modes: `--staged` (default, the pre-commit hook's question — what is about to be committed)
and `--committed` (`make guard-host-paths`, the tip commit's own diff — still catches a
`--no-verify` commit the next time it runs).

## Consequences

- Deliberately **not** a general secrets scanner — scoped to the one leak class this incident
  produced (a host-rooted absolute path). No credential, token, or arbitrary-PII detection.
- Deliberately **not** a full-tree historical scan as an ongoing check — `--committed` reads only
  the tip commit's diff, because a full-tree scan would misfire against this repo's own legitimate
  mentions of `/root/`/`/home/` (the `Dockerfile`, the guard's own pattern, parametrized test
  fixtures) with no allowlist mechanism this guard deliberately does not carry beyond the per-line
  marker.
- **Does not catch** tilde-shorthand paths (`~/Documents/...` — no username, but a private
  repo/project name after it still publishes something real) or Windows-style paths (out of scope,
  single-operator macOS machine, D005). Stated explicitly in the module docstring so a later reader
  does not assume broader coverage than exists.
- The two already-committed transcripts were removed from unpushed history via `git filter-repo`,
  confirmed against `origin/main` first (nothing already pushed was touched).

## References

- `tools/hooks/forbid-host-paths.py`.
- `openspec/changes/archive/2026-08-17-stop-publishing-host-paths/proposal.md`.
- `openspec/specs/run-guardrails/transcript-publication/spec.md`.
- `src/yosefactory/protocol/turn.py::_HOME_ROOTED` (the pattern this guard mirrors for staged
  content).
