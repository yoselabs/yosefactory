## 1. `AGENTS.md` becomes the worker-facing operating model

- [x] 1.1 New "## Operating model" section at the top: OpenSpec exclusivity (naming the actual
      `.claude/commands/opsx/*` slash commands and `.claude/skills/openspec-*` skills), a pointer
      to `openspec/config.yaml`'s `context` block for "explore does not authorize building" (not
      restated), commit-with-literal-pathspec discipline citing `orchestration.md` Article V,
      validate-before-archive and the two `openspec` traps citing Article XIV, archive-is-part-
      of-the-change citing Article XV, the end-to-end receipt question citing Article XVI, and
      one-working-tree citing Article XVII.
- [x] 1.2 Demote the beads/shell-hygiene material below the new section under a
      "## Issue tracking (beads)" heading; managed blocks (`BEGIN/END BEADS INTEGRATION`,
      `BEGIN/END BEADS CODEX SETUP`) left byte-for-byte inside their markers.
- [x] 1.3 State which of the seventeen K articles were judged fleet/design governance rather than
      worker mechanics and are deliberately not restated (recorded in the section's own text and
      in this change's closing report, not duplicated a third time).

## 2. Drift checker, not a generator

- [x] 2.1 `tools/hooks/check_orchestration_citations.py`: extracts `orchestration.md Article <id>`
      citations from `AGENTS.md`, checks each id's header still exists in K's `orchestration.md`
      when that file is reachable, skips cleanly (exit 0) when it is not.
- [x] 2.2 Wired into `make check` (new `citations` target), not the pre-commit hook — K is
      routinely absent for other clones/CI, and a hook that silently no-ops most invocations is a
      false-confidence shape; `make check` is deliberate and shows the skip.
- [x] 2.3 Run it directly and confirm it reports the five cited ids (V, XIV, XV, XVI, XVII) present.

## 3. Resolve the `CLAUDE.md` Stack / ADR-0006 model contradiction

- [x] 3.1 Checked, not assumed: `git blame` on the Stack line (2026-08-12) vs `decisions/0006`'s
      date (2026-08-20) and scope (`executor/claude.py`'s `PINNED_MODEL`/`PINNED_EFFORT`); grepped
      the tree for any code path reading `CLAUDE.md`'s Stack section (none).
- [x] 3.2 Verdict: genuine contradiction (same subject — the platform's own harness invocation),
      not ambiguity. Standing ruling (ADR-0006) wins.
- [x] 3.3 `CLAUDE.md`'s Stack section rewritten to point at `decisions/0006-...md` instead of
      restating a value, with the scope boundary stated explicitly (governs the platform's harness
      invocations; does not govern which model a build/worker session itself runs as).
- [x] 3.4 `decisions/0009-claude-md-stack-model-line-points-at-adr-0006.md` written, recording the
      contradiction and the pointer-not-restatement resolution, per `openspec/config.yaml`'s
      non-obvious test (a future worker editing the Stack section could plausibly restore the
      stale value without knowing ADR-0006 exists).

## 4. Reconcile the beads commit/push profile

- [x] 4.1 Checked K's D022 directly rather than assuming: push is granted to **the platform**
      (`runtime/turn.py`'s `commit()`/`take_turn`), not to a build/worker session — confirmed
      against `decisions/D022-the-platform-is-the-machine-and-it-may-push.md`.
- [x] 4.2 `AGENTS.md` gains an "### Overrides to the managed block above" section (same pattern as
      `CLAUDE.md`'s existing one), placed after both managed beads blocks: states commit authority
      comes from an active OpenSpec change, push is the platform's own narrower grant and not a
      worker session's, and the rest of the managed checklist still applies.

## 5. Host-path triage — `AGENTS.md`, `CLAUDE.md`, `decisions/0001`

- [x] 5.1 Enumerated every `~/` occurrence in the three files (`grep -n "~/"`); classified each
      functional / gratuitous / over-disclosing. Full table in this change's closing report.
- [x] 5.2 Fixed: `decisions/0001-onboard-shelf-and-beads.md`'s reference to the operator's
      personal memory-system path — replaced with prose, no path (unmanaged file, safe to edit).
- [x] 5.3 Found but NOT fixed, and said so rather than silently skipping: the same class of
      occurrence inside `AGENTS.md`'s `BEGIN/END BEADS CODEX SETUP` managed block. Editing inside
      a managed block would be silently reverted by the next `bd setup codex` run — flagged in the
      new "Overrides to the managed block above" section instead of edited in place.
- [x] 5.4 `CLAUDE.md`'s own paths left in place (shelf resolver block explicitly functional per
      dispatch; the rest already covered by the file's disclaimer) — disclaimer broadened by one
      line so it plainly covers the whole file, not only the block immediately under it, closing
      the gap for the "Reuse before writing" section's paths without moving or removing them.

## 6. Verify

- [x] 6.1 `python3 tools/hooks/forbid-host-paths.py --staged` clean over every changed file.
- [x] 6.2 `make check` (lint + ty + test + citations) passes.
- [x] 6.3 `python3 tools/hooks/check_orchestration_citations.py` run directly, output confirmed.
- [x] 6.4 `openspec validate write-down-the-operating-model --strict` passes.
- [x] 6.5 Confirm no `src/` changes beyond what (c) required — none were required; `CLAUDE.md`'s
      Stack section is documentation, `decisions/0006`'s code constants are untouched.
