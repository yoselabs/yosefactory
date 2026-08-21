## Why

[[S989]]'s environment gap is closed: `ship-a2web-toolchain-as-a-stopgap` (`1a19172`) baked a2web's
`[browser]` extra into the factory image, and `docker run … make check` inside the container now
reads `1893 passed, 2 deselected, coverage 92.14%` on a2web's `fix-hepsiburada-js-heavy-host` HEAD
(`fd24220`) — identical to the host. `run-a-turn-against-a2web` (`8f46326`) proved the gate can run
for real and stopped there; both environment failures it hit are now fixed. [[D014]]'s window
closes 2026-08-24 and is scored from the ledger, not from a2web's git log ([[D014]] trail,
2026-08-17 ruling). No qualifying `take_turn` run against a2web has yet reached `Outcome.ADVANCED`.

## What Changes

- Re-run `scripts/run_a2web_turn.py` (built by `run-a-turn-against-a2web`, unchanged infrastructure)
  with a **new** frame — not the hepsiburada item, which is already committed to a2web
  (`fd24220`, branch `fix-hepsiburada-js-heavy-host`) from the prior attempt's turn 2 and would be
  make-work to redo. New target: `a2web-luh` — verify Reddit's `reddit_forbidden_hint` /
  `reddit_deleted_hint` terminal path escalates to a critical operator hint when the suggested
  archive fallback also fails (currently both construct with the default `info` severity, which
  `OperatorHint._omit_default_severity` drops from the wire entirely). Bounded: two named emission
  sites (`src/a2web/handlers/reddit.py:241`, `:924`), one capability test, real acceptance criteria
  already on the bead — not invented for this run.
- Run inside the container, in the container's own `factory` user, with exactly two mounts:
  `{yosefactory, a2web}`. No board, no push, per the dispatch's hard constraints.
- Report the `TurnRecord`, the spend row, a2web's `git log` on the run's branch, proof of
  in-container execution, and the boundary re-demonstration.
- Report on the known `Yosefactory-Run` trailer gap on workspace commits (open, not fixed here —
  see design.md).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
(none — this exercises already-shipped `take_turn`/container/isolation behaviour against a real
foreign repository; nothing in `src/yosefactory/protocol` or `runtime` changes)

## Impact

- `scripts/run_a2web_turn.py` — `FRAME` dict edited to the new item; no other code changes.
- a2web: one commit on a **new** branch, produced by the executor inside the container. `main` and
  `fix-hepsiburada-js-heavy-host` untouched.
- `ledger/`: one new `TurnRecord`, one `spend.jsonl` row.
- No push, either repository. No board.
