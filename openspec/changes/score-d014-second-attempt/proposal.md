## Why

[[D014]]'s window closes 2026-08-24. Three scored attempts so far (`score-d014-against-a2web`),
each failing one step later: (1) gate crashed, `make` missing — fixed by
`ship-a2web-toolchain-as-a-stopgap`; (2) gate failed, a2web needed browser backends — fixed by the
same change; (3) turn 1 hit its own budget ceiling before committing — cap raised; turn 2 (`9e183e4`
on a2web) did real work, a2web's own `make check` gate passed, and the turn still ended `failed`:
the `done` proposal omitted the required `effects` field.

`teach-the-done-event-schema` diagnosed why: not a missing instruction ([[S990]] — the vocabulary
pointer *was* present and correct) but distance-from-the-action decay on a long, real,
budget-pressured turn. It repositioned the reminder into `turn-skill.md` and `Invocation.render()`,
proven present-and-near by two $0 tests, explicitly **unproven** against a real long turn.

This change is that proof: one more `take_turn` against a2web, scored from the ledger per D014's
2026-08-17 ruling, to measure whether the repositioned reminder converges on a well-formed `done`
event under real budget pressure.

## What Changes

- Edit `scripts/run_a2web_turn.py`'s `FRAME` to a **fresh** a2web backlog item — not `a2web-luh`
  (already committed, `9e183e4`) and not `a2web-cid` (already committed, `fd24220`); both would be
  the make-work D014 exists to prevent. In passing: `a2web-luh` is also still `bd ready`-listed
  despite the fix already sitting on disk, and so is `a2web-1uh` despite `SECURITY.md` already
  existing on `main` — both stale-open beads, neither this change's scope to close.
- New target: `a2web-qgo` — surface the page's own primary image URL (`og:image` /
  `twitter:image` / JSON-LD `Product.image` / literal hero `<img src>`) to `ask` callers, currently
  dropped entirely by `_ASK_META_ALLOWLIST` in `src/a2web/fetcher_response.py`. Bounded: one
  function, one allowlist, ADR-0012 (never manufacture a selection) and ADR-0014 (grounded URLs
  only) already state the constraints, one capability test.
- a2web checked out to clean `main` (`6f26e89`) before the run, not the leftover
  `fix-reddit-archive-rescue-escalation` branch — a fresh branch for a fresh measurement, per
  Article VII's requirement to decide and record this deliberately.
- Run inside the container, `docker run` directly (not compose), exactly two mounts
  `{yosefactory, a2web}`, board off (re-verified by reading `run_a2web_turn.py` and
  `runtime/turn.py`/`runtime/loop.py`: no `board` import or reference anywhere on the `take_turn`
  path), no push.
- Report the `TurnRecord`, the joined spend row, a2web's `git log` on the produced branch, the
  boundary re-demonstration, and the host-path grep with its investigation — and, distinct from
  D014 itself, whether the `done` event this time carried `effects` (the second measurement this
  run produces, per S990).
- Ceiling $2.80 of the $3.00 granted; do not spend the remainder on a second turn without
  reporting back first.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
(none — exercises already-shipped `take_turn`/container/isolation behaviour against a real foreign
repository; nothing in `src/yosefactory/protocol` or `runtime` changes)

## Impact

- `scripts/run_a2web_turn.py` — `FRAME` dict edited to the new item; `owner`/`actor` bumped to a
  fresh worker id; no other code changes.
- a2web: at most one commit on a **new** branch off `main`, produced by the executor inside the
  container, or none if the turn fails before committing. `main` untouched.
- `ledger/`: one new `TurnRecord`, one `spend.jsonl` row (or two, only if a second turn is run and
  reported first per the budget note above).
- No push, either repository. No board. The gate itself (`verify.may_write_done`,
  `backlog.ITEM.rules`, `VOCABULARY_SPEC`) is not touched under any circumstance.
