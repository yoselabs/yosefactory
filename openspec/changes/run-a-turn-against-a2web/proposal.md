## Why

No K promotion id — this is a direct dispatch against D014/D022's own deadline (2026-08-24), not a
build-time promotion. [[D014]] scores a commit to `a2web` produced through the platform; [[D022]]
fixed the unit to `take_turn` against a repository, not a session following a workflow by hand.
`add-cross-repo-workspace` (archived 2026-08-16) built `Places`/cross-repo `take_turn`. **It has
never run against a real second repository** — only `add-take-turn-integration-receipt`'s throwaway
fixture workspace, which never reached `done`. Everything the two most recent archived changes
(`run-the-loop-inside-the-container`, `pin-the-executor-and-close-the-push-grant`) built — a
container image, a `workspace_scoped` posture that can act unattended, pinned model/effort — has
likewise only run against yosefactory's own backlog. This change is the first real exercise of the
whole stack pointed at `a2web`.

## What Changes

- One real `take_turn` call, `Places(queue=yosefactory, workspace=a2web)`, run for real inside the
  built container (`yosefactory-factory:latest`), against a small, real, already-acknowledged a2web
  task (adding a missing host to a JS-heavy-site seed list — a2web's own `flag-interaction-gated-
  sections/tasks.md` task 7.5, bead `a2web-cid`).
- The container's mount topology widens from one bind mount (`/app`) to two: yosefactory (queue +
  ledger) and a2web (workspace) — nothing else. Demonstrated, not just declared: the run attempts to
  reach something outside both mounts and the receipt records what happened.
- Publication stays declined for both places (`publish_workspace=False`, `publish_queue=False`) —
  the dispatch forbids pushing either repository this run; D022 §2's push grant is not exercised here.
- No board/Issues wiring — a2web's item text and file paths must never reach yosefactory's public
  board.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
(none — this exercises already-shipped behaviour: `turn-cycle`, `turn-places`,
`claude-executor/isolation-invocation`, `claude-executor/model-and-effort`,
`containerized-loop/unattended-isolation-posture`, `containerized-loop/unattended-publication-
posture`, `commit-attribution`. No requirement in any of their specs changes — `skip_specs: true`.)

## Impact

- A driver script (one-off, not a `src/yosefactory` module) that seeds one backlog item in
  yosefactory's queue and calls `runtime.turn.take_turn` with cross-repo `Places`.
- `docker-compose.yml`, or a sibling override — whichever adds the second mount with the smaller,
  more reversible diff (decided in design.md).
- `ledger/` — the real run's `TurnRecord`, `.start` marker, and `ledger/spend.jsonl` row.
- `~/Workspaces/a2web` — one commit, on a branch, never `main`. Not pushed.

## Non-goals

- No CLI flag on `runtime/loop.py` for a second repository — cross-repo stays a direct caller of
  `take_turn`, exactly as `add-cross-repo-workspace`'s own proposal scoped it.
- No change to `IsolationPolicy` or its composition rules.
- No push to either remote (`origin` on yosefactory or a2web).
- No board/Issues wiring for this run.
- Not fixing "an agent proposes `done` without committing" if hit again — a separate, already-known
  defect (D022 §1's own trail). Report it; do not patch the skill here unless a fix falls out for
  free of something already in scope.
- Not attempting a second a2web task if this one turns out unreachable. Report exactly where the
  turn stopped.
- No production change to `src/yosefactory/protocol` or `runtime` unless the run itself surfaces a
  real defect only reachable by running cross-repo for real — in which case that is reported and
  scoped narrowly, not assumed in advance.
