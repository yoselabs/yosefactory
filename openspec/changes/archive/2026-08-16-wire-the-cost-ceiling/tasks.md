## 1. Baseline

- [x] 1.1 Record `make check` baseline and `git status --porcelain`; `runtime/turn.py` is YF-5's, untouched by this change
- [x] 1.2 Re-confirm `claude -p --help` on this machine still lists `--max-budget-usd` and no turn-count flag, since the last check was minutes old but the rule is check-before-claim every time, not once per session

## 2. Config

- [x] 2.1 Add `cost_ceiling_usd: float | None = None` to `Guardrails` in `runtime/config.py`, validated only when not None (positive, finite) and otherwise left alone
- [x] 2.2 `from_mapping` accepts the new key without widening `_SECRET_ISH` or breaking the unknown-key rejection

## 3. The executor

- [x] 3.1 `build_argv` gains a `cost_ceiling_usd: float | None = None` keyword, emitting `--max-budget-usd <value>` when set, in both the isolated and opted-out branches
- [x] 3.2 `run` threads `limits.cost_ceiling_usd` through to `build_argv`
- [x] 3.3 Correct `NATIVE`'s comment: it already says wiring is separate; update it to say this change is that separate wiring, or remove the now-stale forward reference

## 4. Tests

- [x] 4.1 No ceiling set: `build_argv` output is byte-identical to before this change for both postures
- [x] 4.2 A ceiling set: `--max-budget-usd` and the value appear in argv
- [x] 4.3 `Guardrails` rejects a non-positive or non-finite ceiling when one is supplied, and accepts `None`
- [x] 4.4 A real invocation is NOT added here — no new live-binary cost for a flag whose format is checkable from argv alone

## 5. Close

- [x] 5.1 `make check` green against the 1.1 baseline
- [x] 5.2 `openspec validate wire-the-cost-ceiling --strict` passes before archiving (Article XIV)
- [x] 5.3 One commit, `git commit -F <file> -- <literal paths>`, `PREK_ALLOW_NO_CONFIG=1`, `git diff --cached` confirmed empty. A gate rejection naming a file in `runtime/turn.py` is YF-5's, not debugged here (S184)
- [x] 5.4 Archive; confirm the new capability's spec promotes cleanly with no deletions anywhere (nothing MODIFIED)
- [x] 5.5 Report: the flag is wired and unit-tested; no live receipt was added, consistent with the previous change's finding that no integration layer exists to honestly produce one

## Outcome

**Landed.** `Guardrails.cost_ceiling_usd` (nullable, additive) threads through `run()` into
`build_argv`, which sends `--max-budget-usd <value>` in both invocation postures when set and no flag
at all when not — verified against the real binary's `--help` before writing, not inherited from the
dispatch. 6 new tests, all unit-level: 3 on `build_argv` (no subprocess, no pinned-binary dependency),
3 on `Guardrails` validation. No new live-binary cost, consistent with `write-the-reason-fields`'s
finding that no integration layer exists to honestly exercise this end to end.

**Shared-tree accounting:** `make check` read 255 locally, not the 244 (238+6) my own diff would
predict — the gap is YF-5's uncommitted `runtime/turn.py`/`test_turn_cycle.py` work, present on disk
and counted by a shared-tree run but excluded from this commit's pathspecs.

**Left, as scoped:** the `take_turn`-against-real-executor integration layer, named again rather than
built. `--max-turns` reconfirmed absent from `claude -p --help` at this session's check, so `EMULATED`
stays correct and untouched.
