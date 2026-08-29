## 1. Diagnose

- [x] 1.1 Run `pytest -q -m live -rs` on both files at HEAD, capture the verbatim skip list.
- [x] 1.2 Read `runtime.turn.Executor.__call__`'s real signature; compare against the stale
      assertion.
- [x] 1.3 Confirm both files share the identical exact-version guard, and count how many tests it
      silently disables.

## 2. Fix the assertion

- [x] 2.1 `test_the_wrapper_matches_the_executor_protocol`: update the expected parameter list to
      `["frame", "workspace", "limits", "run_id", "runs_dir", "transcripts_dir", "context",
      "invocation"]`.

## 3. Move the offline test out of the live gate

- [x] 3.1 `tests/runtime/test_turn_integration.py`: replace the module-level `pytestmark` with
      per-test `@pytest.mark.live` + an absent-binary `skipif`, applied to the five behaviour
      tests individually. `test_the_wrapper_matches_the_executor_protocol` carries neither.

## 4. Split the guard: absent (skip) vs. drifted (fail)

- [x] 4.1 `tests/runtime/test_turn_integration.py`: add `require_pinned_claude` fixture (plain
      `assert installed == PINNED_VERSION`, requested explicitly, not autouse); each of the five
      behaviour tests requests it.
- [x] 4.2 `tests/executor/test_integration.py`: same split — module-level `pytestmark` narrows to
      absent-binary skip only; each of the six tests requests `require_pinned_claude`.
- [x] 4.3 Confirm the fixture's failure message names both the installed and pinned versions.

## 5. Spec

- [x] 5.1 `claude-executor/run-interface` spec delta: ADDED requirement — the protocol-conformance
      check runs unconditionally.
- [x] 5.2 `claude-executor/live-test-gating` (new spec file): ADDED requirement — absent-vs-drifted
      split.

## 6. ADR

- [x] 6.1 `decisions/0021-fail-loud-on-claude-version-drift-not-a-minimum-version-guard.md` —
      Decision 1 and Decision 2 from `design.md`, condensed.

## 7. Verify

- [x] 7.1 `make check` green (the wrapper-conformance test now included, unconditionally).
- [x] 7.2 `PREK_ALLOW_NO_CONFIG=1 uv run pytest -q -m live -rs tests/runtime/test_turn_integration.py tests/executor/test_integration.py`
      on this machine: the conformance test no longer appears in this run at all (it runs under
      plain `pytest`, not `-m live`); the other ten fail loudly, naming `2.1.251` vs `2.1.225`,
      none skip silently.
- [x] 7.3 `openspec validate the-conformance-test-that-cannot-fail --strict` passes.
- [ ] 7.4 Commit, then archive; re-run `make check` after archiving.
