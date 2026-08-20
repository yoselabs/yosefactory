## 1. Pin model and effort

- [x] 1.1 `executor/claude.py`: `PINNED_MODEL = "claude-sonnet-5"`, `PINNED_EFFORT = "medium"`
      module constants beside `PINNED_VERSION`. `build_argv` gains `model: str = PINNED_MODEL,
      effort: str = PINNED_EFFORT` and always appends `["--model", model, "--effort", effort]`.
- [x] 1.2 `executor/stream.py`: `InitFacts` gains `model: str = ""`, parsed from the init event's
      `"model"` key in `StreamReader.consume`.
- [x] 1.3 `executor/outcome.py`: `RunResult` gains `model: str = ""`, `effort: str = ""`.
- [x] 1.4 `executor/claude.py::run`: sets `model`/`effort` on the returned `RunResult` — `model`
      from `reader.init.model` when the init event was captured, else the `model` argument;
      `effort` from the `effort` argument, always.
- [x] 1.5 `protocol/turn.py`: `TurnRecord` gains `model: str = ""`, `effort: str = ""`, threaded
      through `to_dict`/`from_dict` (missing key on read → `""`, same pattern as `note`). Not added
      to `_REQUIRED`.
- [x] 1.6 `runtime/turn.py`: `_dispose`/`_finish` thread `result.model`/`result.effort` into the
      `TurnRecord` they construct, at all four `_finish` call sites reached from a started executor.

## 2. Close the push grant

- [x] 2.1 `runtime/loop.py::main`: new `--publish` CLI arg (`store_true`, default `False`).
- [x] 2.2 After `places = Places.local(repo)`: when `unattended`, `places = replace(places,
      publish_workspace=args.publish, publish_queue=args.publish)`. Interactive path unchanged.
- [x] 2.3 `main`/`scheduled_main` docstrings updated to state the new default and how `--publish`
      reopens it.

## 3. Spec

- [x] 3.1 `openspec/specs/claude-executor/model-and-effort/spec.md` — new capability, ADDED only.
- [x] 3.2 `openspec/specs/containerized-loop/unattended-publication-posture/spec.md` — new
      capability, ADDED only.
- [x] 3.3 `openspec validate pin-the-executor-and-close-the-push-grant --strict` passes.

## 4. Tests

- [x] 4.1 `test_claude.py`: `build_argv` sends `--model`/`--effort` with the pinned defaults when
      the caller states no opinion; sends an override verbatim when supplied.
- [x] 4.2 `test_stream.py`: `InitFacts.model` parses from a synthetic init event carrying
      `"model"`, and reads `""` when the key is absent.
- [x] 4.3 `test_turn.py` (protocol): a `TurnRecord` round-trips `model`/`effort` through
      `to_dict`/`from_dict`; a payload with neither key loads with both reading `""`.
- [x] 4.4 `test_loop.py`: an unattended `scheduled_main()` invocation with no `--publish`
      constructs `Places` with both publish flags `False`; `--publish` flips them `True`.
      Interactive `main()` is unaffected either way (asserted True regardless of the flag).

## 5. Verify

- [x] 5.1 `ruff check src/ tests/` and `ty check src/` clean.
- [x] 5.2 Full non-live/non-boardlive suite (the same selection `make check` runs): 353 passed, 13
      deselected — 344 pre-existing + 9 new.
- [x] 5.3 `openspec validate pin-the-executor-and-close-the-push-grant --strict` passes on the
      change (not `--specs --strict` on the result — that is clean when nothing promoted).

## 6. Live receipts

- [x] 6.1 One live turn, in the pinned container image (`yosefactory-factory:latest`,
      `claude 2.1.225`), driving `runtime.turn.take_turn` directly with no model/effort override.
      Its `TurnRecord`, written to `ledger/runs/*.json` in the scratch queue repo, carries
      `"model": "claude-sonnet-5", "effort": "medium"`. `model` is confirmed to have come from the
      run's own `system|init` event (`InitFacts.model`), not an echo of what was sent — the same
      run also exercised the fallback path in code, but this run's init event reported a model, so
      the value on the record is the verified one.
- [x] 6.2 The same live turn's `Places` were constructed exactly as `runtime.loop.main()`'s
      unattended branch now builds them (`publish_workspace=False, publish_queue=False`) — a direct
      construction mirroring `main()`'s own wiring (unit-tested separately in 4.4) rather than a
      run through the CLI entrypoint itself, so the receipt isolates the `publish()` behaviour from
      argparse plumbing. The turn reached `advanced`; `publish()`'s return value, printed from the
      run, was `(PublishResult(repo=.../workspace, status='declined', ...),
      PublishResult(repo=.../queue, status='declined', ...))`. `git log origin/main..HEAD` on both
      scratch repos shows the turn's real commits ahead of `origin`, never pushed.
- [x] 6.3 `make check` spend proof: `ledger/spend.jsonl` was 10 rows before any code change and 10
      rows immediately after `make check` (unchanged, confirmed by `git diff` on the file being
      empty) — the check suite itself spends $0. The two live receipts above are separate,
      deliberate spends (task 6), recorded as their own rows.

## 7. Archive

- [x] 7.1 `openspec archive pin-the-executor-and-close-the-push-grant` after 3.3/5.3 pass and both
      receipts (6.1/6.2) are on disk.
