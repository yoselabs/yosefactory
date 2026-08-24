## 1. Part 1 — the confirmed defect

- [x] 1.1 In `backlog.context()`'s `unblocked` branch, take the `isinstance(resolution, Mapping)`
      hunk from `sweep-blocked-and-snoozed-deadlines` commit `2262f7e` — that hunk only, nothing
      else from that branch.
- [x] 1.2 Test: `context()` over an `unblocked` event whose `resolution` is the literal string
      `"timeout"` folds to `{}` instead of raising `AttributeError`. Confirm it fails on `main`
      before the fix (temporarily revert, run, restore) or cite `design.md`'s live confirmation.

## 2. Part 2 — `Rule` grows a `types` field

- [x] 2.1 `protocol/eventlog.py`: add `types: Mapping[Path_, type | tuple[type, ...]] =
      field(default_factory=dict)` to `Rule`.
- [x] 2.2 `_check_payload`: add a third loop over `rule.types`, checked only when the field is
      present (same posture as `patterns`), raising `LogError` naming the path, the value, and the
      expected type(s) on mismatch.
- [x] 2.3 Test (`tests/protocol/test_eventlog_rules.py`): a `Rule` with a `types` entry rejects a
      wrong-shaped present field and accepts a correctly-shaped one; a field absent that has a
      `types` entry but no `required` entry is not itself an error (types do not imply presence).

## 3. Declare types for the three events `context()` reads

- [x] 3.1 `ITEM.rules["gate_rejected"]`: `types={("report",): str, ("attempt",): int}`.
- [x] 3.2 `ITEM.rules["failed"]`: `types={("reason",): str, ("attempt",): int, ("retryable",): bool}`.
- [x] 3.3 `ITEM.rules["unblocked"]`: `types={("resolution",): (str, Mapping)}`.
- [x] 3.4 Test: a hand-built `failed` record with `retryable` as the string `"true"` fails
      `backlog.load()`.
- [x] 3.5 Test: a hand-built `unblocked` record with `resolution` as e.g. a list fails
      `backlog.load()`; the existing string and mapping shapes both still load.

## 4. Spec delta

- [x] 4.1 `specs/backlog-item-format/spec.md`: one new scenario under "The event vocabulary and its
      transitions" — a declared type mismatch fails the read, naming the field — mirroring "A
      malformed on_timeout still fails wherever it appears." No requirement text changes; this is
      MODIFIED (the requirement gains a scenario) not ADDED.

## 5. Close

- [x] 5.1 `make check` (lint, ty, test, citations) green.
- [x] 5.2 `openspec validate type-the-payloads-context-reads --strict` passes on the change.
- [x] 5.3 Decide whether this change's mechanism choice (extend `Rule` over pydantic/`TypedDict`)
      needs a `decisions/000N-*.md` ADR — likely yes: a future worker could plausibly reach for
      pydantic without knowing D032 already weighed it and this change chose otherwise.
- [ ] 5.4 Archive. Confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows only
      additions inside the declared MODIFIED block (deletions = 0, or every deletion is named in
      the commit message).
- [ ] 5.5 Re-run `make check` after archiving.
