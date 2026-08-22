# ADR-0014 — Cross-repo CLI surface collapses to `--queue`/`--workspace`, not all seven `Places` fields

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a second real caller needs a `workspace_lock` convention other than
`<workspace>/.git/yosefactory-turn.lock`, or needs `publish_queue`/`publish_workspace` set
independently rather than together. Until then, both are named-but-unexercised generality and are
deliberately not exposed.

## Context

`Places` has five path-shaped seams (`queue`, `ledger`, `queue_lock`, `workspace`,
`workspace_lock`) plus two publish booleans; `runtime/loop.py::main` built it only via
`Places.local(repo)`, collapsing all seven onto one argument. `main`'s own docstring called this
deliberate and named "a caller that imports `run_loop` directly" as the escape hatch. Two callers
took that escape hatch independently: this repo's own `scripts/run_a2web_turn.py`, and
`yoselabs/factory-state`'s `runner/take_one_turn.py` (a private repo; read, not copied — this ADR
states the convention both arrived at, not either file's text). Both hand-construct `Places`,
`Guardrails`, and `IsolationPolicy`, and the private one drifted out of sync with
`Guardrails.max_attempts` becoming required (ADR-0012), causing a `TypeError` caught only when a
container started — a breaking change in this repo, discovered at runtime, in a different
repository, after a pull.

`give-the-entrypoint-a-cross-repo-surface` gives the entrypoint a CLI surface sufficient to delete
that driver rather than shorten it.

## Decision

Expose exactly `--queue` and `--workspace` (each optional, defaulting to the existing `repo`
positional) rather than one flag per `Places` field. When they resolve to the same path, the
constructed `Places` is identical to `Places.local(repo)` — the collapsed case is unchanged
byte-for-field. When they differ, `ledger` and `queue_lock` are always derived under the queue, and
`workspace_lock` is always derived as `<workspace>/.git/yosefactory-turn.lock` — never independently
settable. Both existing ad-hoc drivers converged on that exact lock path without coordinating with
each other, which is the evidence this is the one right default rather than a guess.

Also added: `--test-command` (names a foreign workspace's own verification gate, e.g. `make check`
for a2web) and `--cost-ceiling-usd` (a single turn's `Guardrails.cost_ceiling_usd`, kept distinct
in name from the pre-existing `--spend-ceiling-usd`, which bounds the *loop's* cumulative spend
across iterations — a different mechanism at a different granularity that shares a unit and would
otherwise be easy to confuse).

**Alternative considered and rejected:** exposing all five path fields plus both booleans as
independent flags. Rejected because every real caller only ever wants "queue over here, workspace
over there" — nobody has ever wanted an independently-placed lock file or ledger — and a fully
general surface would let a caller construct a `Places` combination `Places.local` structurally
cannot produce today (e.g. a `workspace_lock` unrelated to either the queue or the workspace),
which is a footgun with no offsetting real use.

**`--publish` is unchanged** (still one boolean setting both `publish_queue`/`publish_workspace`
together on the unattended path). No known caller — including the CI topology this change targets,
which declines publication entirely (K D024 ruling 3: a separate, credential-holding job
publishes) — ever wants them independent.

**No new "single turn" mode.** `run_loop`'s first iteration is unconditionally
`WakeReason.STARTUP` with no wait, so `--max-iterations 1` against a split queue/workspace already
behaves as one turn and stops — exactly what a CI job firing on its own external trigger needs
(D024 ruling 1). Building a second code path for the same behavior was considered and rejected as
needless duplication.

## Consequences

- `factory-state`'s driver becomes deletable: every item in its behavior inventory (queue/workspace
  split, test command, per-turn cost ceiling, workspace-keyed lock, declined publication, one turn
  per invocation) is now reachable through `yosefactory-loop-scheduled` itself. Verified by
  construction against the driver's own inventory (design.md's table), not merely by "the tests
  pass."
- `--spend-ceiling-usd` stays mandatory on the unattended path (ADR-0003's contract, deliberately
  untouched) and is now sometimes structurally near-inert for a `--max-iterations 1` invocation —
  the cumulative check evaluates before the one turn starts, when nothing has been spent yet this
  process. Not fixed here; flagged as friction a future caller pays, not breakage.
- This does not make the CLI a *versioned* contract — no deprecation policy, no compatibility test
  across `argparse` changes. It closes the one breaking-change vector this change was dispatched
  against (a foreign repository constructing this repository's dataclasses directly); whether a
  flag surface is durable enough on its own is a larger question this ADR does not resolve.
