## 1. Mechanism — move the obligation to the archive seam

- [x] 1.1 Add `operations.archive.guidance` to `openspec/config.yaml`: the non-obvious test, the
      `Revisit trigger:` requirement, and the what-vs-how boundary reminder.
- [x] 1.2 Verify the guidance actually reaches the archive skill:
      `openspec instructions archive --change close-the-adr-gap --json` and confirm
      `operationGuidance` carries all three entries.
- [x] 1.3 Add the `Revisit trigger:` line to `decisions/README.md`'s template description, pointing
      at the archive seam as the trigger rather than restating the rule as a second source.

## 2. Backfill — six ADRs for undocumented build-time decisions, 2026-08-16 to 2026-08-22

- [x] 2.1 `decisions/0003` — the turn loop's bound is mandatory, no infinite mode
      (`runtime/loop.py::LoopBound`). Grounded in `add-turn-loop`'s archived proposal/design.
- [x] 2.2 `decisions/0004` — `turn.commit()` is the sole trailer-composing function, via
      `git interpret-trailers` (`runtime/turn.py`). Grounded in `mark-platform-authored-commits`.
- [x] 2.3 `decisions/0005` — the platform delivers the workspace commit by amending `HEAD`, never a
      new commit (`_deliver_workspace`). Grounded in `the-platform-delivers-the-workspace-commit`.
- [x] 2.4 `decisions/0006` — the executor is pinned to `claude-sonnet-5` / effort `medium`
      (`executor/claude.py` `PINNED_MODEL`/`PINNED_EFFORT`). Grounded in
      `pin-the-executor-and-close-the-push-grant`.
- [x] 2.5 `decisions/0007` — the image runs as uid 1000 because `bypassPermissions` refuses root
      (`Dockerfile`, `docker-entrypoint.sh`). Grounded in commit `5df739d` and
      `run-the-loop-inside-the-container`.
- [x] 2.6 `decisions/0008` — the host-path pre-commit guard and its `hostpath-allow` marker
      (`tools/hooks/forbid-host-paths.py`). Grounded in `stop-publishing-host-paths`.
- [x] 2.7 For each ADR: confirm the claim against the actual code (not only the docstring/archived
      proposal) before writing it. Report any discrepancy found rather than silently correcting
      code (documentation-only change — no runtime code edits).

## 3. Verify

- [x] 3.1 `python3 tools/hooks/forbid-host-paths.py --staged` (or `--committed` after landing)
      clean over every new/changed file — this repo is public.
- [x] 3.2 `openspec validate close-the-adr-gap --strict` passes.
- [x] 3.3 Confirm no runtime code (`src/`, `tools/` other than reading, `Dockerfile`,
      `docker-entrypoint.sh`) was edited — documentation-only, per dispatch.
