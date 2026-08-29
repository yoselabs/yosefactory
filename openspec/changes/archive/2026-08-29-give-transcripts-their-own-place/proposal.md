## Why

K D034 ("central control plane, local state, and the event is the wake not the assignment") rules
that raw transcripts are retained *in full, uncapped, in the runner repository* — the one artefact
this program wants for later inspection. Its own "Observability" section names the defect: today
`runs.ensure_transcripts_ignored` writes `*.stream.jsonl` into the workspace's `.git/info/exclude`,
correct for its stated purpose (S237 — a raw transcript nested under the workspace is an untracked
file the `done` gate would otherwise count as the agent's own uncommitted work) and not reverted
here. But under `Places.nested` (K D033), `places.ledger` sits inside the workspace, so every
transcript this guard correctly excludes is also never committed — it dies with the workspace's
container. The one artefact wanted for future inspection is the one thing being thrown away.

`Places` already names four independently-addressable roles (`turn-places` spec: queue, ledger,
lock, workspace); none of them is "where the executor's raw transcript goes" as a concept separate
from the ledger's own `.start`/terminal-record stream. This change adds that fifth seam so a caller
— the runner, per D034 — can point transcripts at a durable location outside the workspace, while
every existing caller is unaffected.

## What Changes

- Add a `transcripts: Path` field to `Places`, alongside its existing four roles. Every constructor
  (`Places.local`, `Places.nested`, `runtime.loop._places_for`) defaults it to `ledger` — today's
  location, byte for byte — so this change is inert until a caller supplies a different one.
- `Places.nested` gains an optional `transcripts` keyword argument, on the same "omitted = today's
  behaviour" contract.
- `turn.Executor`'s call signature gains a `transcripts_dir: Path` parameter, alongside the existing
  `runs_dir` (which continues to name where the `.start`/terminal-record files live — those still
  ride `places.ledger` and the turn's own commit, unchanged). `runtime.turn.take_turn` passes
  `places.transcripts` through on every executor call.
- `executor.claude.run` writes `<run_id>.stream.jsonl` under `transcripts_dir` (an optional
  parameter defaulting to `runs_dir`, so every caller that predates this change is unaffected).
- `runtime.turn.take_turn`'s call to `runs.ensure_transcripts_ignored` now guards `places.transcripts`
  rather than `places.ledger` — the two coincide under every existing caller, and diverge exactly
  when a caller has pointed transcripts outside the workspace, which is the one case
  `ensure_transcripts_ignored`'s own no-op (`runs_dir` not relative to `workspace`) already covers.
- `runtime.loop`'s CLI gains `--transcripts-dir`, matching the existing `--queue`/`--workspace`
  vocabulary, threaded through `_places_for`.

## Non-Goals

- **`ensure_transcripts_ignored` itself is not edited.** Its no-op-when-outside-the-workspace
  behaviour already covers the new configuration; this change only points its `runs_dir` argument at
  `places.transcripts` instead of `places.ledger` at the one call site, and adds a test proving the
  no-op still holds.
- **The `.start` file and the committed run record do not move.** They stay in `places.ledger`,
  riding the work's own commit — D028/D033's territory, untouched here.
- **No wiring on the runner side.** `factory-state` (private, Denis's own repository) is not this
  change's to edit — D034 names it as the destination; this change only builds the seam that lets a
  caller (that repository's driver) point at one.
- **No retention policy or cutoff.** D034's own body defers a cutoff explicitly; not decided here.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `turn-places`: adds `transcripts` as a fifth independently-addressable role, alongside queue,
  ledger, lock, and workspace — defaulting to the ledger so every existing configuration is
  unaffected.

## Impact

- `src/yosefactory/runtime/turn.py` — `Places.transcripts` field, `Places.nested`'s new keyword,
  `Executor`'s signature, the `ensure_transcripts_ignored` call site, both executor call sites.
- `src/yosefactory/executor/claude.py` — `run`'s `transcripts_dir` parameter.
- `src/yosefactory/runtime/loop.py` — `--transcripts-dir`, `_places_for`'s new parameter, the
  in-`main()` executor closure.
- `tests/` — new coverage (`tests/runtime/test_places_transcripts.py`,
  `tests/executor/test_claude.py`) plus signature updates to existing executor test doubles
  (`tests/runtime/test_turn_cycle.py`, `tests/runtime/test_turn_integration.py`,
  `tests/runtime/test_loop.py`) that stood in for `Executor` and needed the new parameter.
- `decisions/0019-*.md` — an ADR for the `Places` seam addition itself (why a field with a
  per-constructor default, not an `Optional` field defaulting itself).
