# Resume Prompt — P8 Lock the shape (kickoff)

> **Paste this verbatim into a fresh session to execute P8.** The new agent has no prior context.

---

## What you are doing

Executing **P8 — Lock the shape**, the final V1.0 migration-phase. The spec is drafted and approved; you're starting step 1 of 6. P7 (Rename & relocate) landed on main — the tree now has `ingress/`, `gating/`, `effects/`, `middleware/`, `composition/`, `observability/` as top-level packages.

P8 encodes the layering rules from `docs/architecture.md` §2 as `import-linter` contracts + adds a pytest that enforces the "only dispatch + CLI imports from ≥5 a2sdlc packages" rule from `CLAUDE.md`. Appetite: 1 day.

## Required reads before any tool call

Read these in order. All are short.

1. `docs/superpowers/specs/2026-04-23-p8-lock-the-shape-design.md` — the full spec. §Plan gives the 6 steps; §Contract file + §Composition-root cap test give the target content verbatim.
2. `docs/architecture.md` §2 (Layering rules) — the ground truth the contract must encode. Updated in P7 step 8.
3. `CLAUDE.md` at repo root — has the "5+ a2sdlc packages" rule and the "domain purity is non-negotiable" rule the contract promotes from convention to CI.
4. Recent commits: `git log --oneline -20` — P7 is Executed; the tree is at its final layout.

## Immediate first action

**Before editing anything, discover the current import-linter state.** The P7 execution hit an error `a2sdlc.assembly is not allowed to import a2sdlc.pipeline` — something already enforces a contract. Run:

```bash
grep -rln "importlinter\|import-linter\|contract:" .agent-harness Makefile pyproject.toml packages/engine/pyproject.toml 2>/dev/null
find . -name ".importlinter*" -not -path "*/node_modules/*" -not -path "*/.venv/*" 2>/dev/null
```

- **If a contract file already exists**: step 1 is "add `import-linter` to dev deps if not present," step 2 is "modify the existing contract to match the spec," not "create new."
- **If nothing exists but the error fired anyway**: look at `agent-harness` itself — it may ship its own built-in arch check. In that case the spec's §Plan step 3 (wire into `make check`) may already be done and step 1 is just "choose where to put the new contract."

Record the finding in a TodoWrite task before proceeding.

## The 6 steps (from the spec)

1. **Discovery + install.** (Above — do this first.)
2. **Write the contract file.** Three contracts: `layers`, `independence` (peer tier A), `forbidden` (domain purity). Bodies are verbatim in the spec §Contract file. Run `lint-imports`; fix any legitimate cross-peer imports by refactor OR `ignore_imports` whitelist (one commit per decision).
3. **Wire into `make check`.** Confirm or add.
4. **Composition-root cap test** at `tests/architecture/test_composition_cap.py`. Body is verbatim in spec §Composition-root cap test.
5. **Mutation check.** Throwaway: add `import a2sdlc.pipeline` to `domain/models.py`, confirm `make check` fails, revert.
6. **Spec status → Executed.**

## Gotchas carried forward from P4–P7

1. **Pre-commit hook reformats then aborts.** If a commit silently doesn't land, re-stage (`git add -u <files>`) and retry. **Never `--no-verify`.**
2. **Solo-repo workflow**: no PRs. Commit + push directly to `main`.
3. **Cassette tier is live.** `make test-integration` replays 13 recorded tests. P8 shouldn't affect cassettes (no adapter code changes), but run it after step 4 as a sanity check.
4. **Diff-coverage is on.** Every new/changed line must be covered. The cap test + contract file changes are either test code (self-covering) or config (not subject to coverage). Should be a non-issue.
5. **`ty` is strict**. It rejected `# type: ignore[arg-type]` in P6 — had to use `cast(Any, …)`. If `ty` complains about the cap-test's `ast` types, use `cast` or `typing.Any` annotations.
6. **Layered contract may surface unexpected cross-peer imports.** E.g., `ingress/` might import from `effects/` via a module you didn't plan for. Don't suppress blindly — verify the import is architecturally legitimate first, then decide refactor vs. whitelist. **Per-decision commit.**

## Success criteria

- All 6 steps land as commits on `main`.
- `make check` green throughout.
- Step 5's mutation test proves the contract + cap test both fail on a seeded violation.
- Spec status is `Executed`.

## What to NOT do in this session

- Don't start P9+ (there is no P9 in V1.0 scope — RFC closes V1.0 at P8).
- Don't re-open settled P4–P7 decisions.
- Don't add L6 smoke to `make check` (spec explicitly non-goal; CI-job add is post-V1.0).
- Don't introduce `agent/`, `session/`, or `pipeline.py` flat-file (P7 scope-A decision).

Good luck. After P8 lands, V1.0 migration is done.
