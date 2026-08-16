# Tasks — implement-claude-executor

- [x] 1. `runtime/supervise.py`: add `stdout: Path | None = None` to `govern()`, wired into
      `Popen`. Additive only. **Gate: `tests/runtime/test_supervise.py` passes unedited** — if
      any case needs changing, stop and report, because that proves it was not additive.
- [x] 2. `executor/outcome.py`: the executor outcome vocabulary and `RunResult`, with the
      mapping down to `protocol.Outcome` at the `govern` seam and the reason carried in `note`
      until `TurnRecord.failure_kind` lands.
- [x] 3. `executor/stream.py`: reader over `--output-format stream-json`. Distinguishes
      `system|post_turn_summary` (turn ending) from `type: "result"` (run ending); exposes a
      live turn count and a terminal verdict; recognises `rate_limit_event`; exposes the
      `system|init` fields isolation is asserted from.
- [x] 4. `executor/claude.py`: `resolveVersion()`, `preflight()`, `run()`. Isolation policy to
      CLI arguments; `--bare` never emitted; isolation asserted from the init event, not from
      the flags passed.
- [x] 5. Unit tests over recorded stream fixtures — including the case that matters most:
      **exit 0 with no terminal event is `failed`.**
- [x] 6. Integration receipt 1: one real bounded `claude -p` producing a structured outcome
      from the terminal event.
- [x] 7. Integration receipt 2: a run exceeding its wall clock produces `failed`,
      `enforced_by: harness`, and a correct `dirty` — S187's definition, by construction.
- [x] 8. `make check`, then commit with explicit pathspecs (Article V) and `PREK_ALLOW_NO_CONFIG=1`.
