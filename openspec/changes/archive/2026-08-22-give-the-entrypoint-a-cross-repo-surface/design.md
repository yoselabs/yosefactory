## Context

`runtime/loop.py::main` builds `Places.local(repo)` — one path plays all four `Places` roles
(queue, ledger, queue_lock, workspace, workspace_lock) plus both publish booleans. `Places` itself
already supports addressing queue and workspace separately (`turn-places` spec, pre-existing); the
gap is entirely in `main`'s argparse surface and its `Places` construction, not in `turn.py`.

The forcing case is `yoselabs/factory-state` (K D026: private queue+runner repo, public a2web
workspace). Its driver, `runner/take_one_turn.py` (read, not copied — this design states the union
of behavior, never the file's text), and this repo's own `scripts/run_a2web_turn.py` (a throwaway
one-off, explicitly "not a `src/yosefactory` module") both hand-construct `Places`, `Guardrails`,
and `IsolationPolicy` because `main` cannot express the split. The private driver's inventory:

| What the driver does | Where it lands in this change |
|---|---|
| `YF_QUEUE` / `YF_WORKSPACE` env vars → split `Places` | `--queue` / `--workspace` flags |
| `workspace_lock = workspace/.git/yosefactory-turn.lock` | same convention, derived automatically when queue != workspace |
| `publish_queue=False, publish_workspace=False` | existing `--publish` (absent = both False on the unattended path already) |
| `YF_TEST_COMMAND` (defaults `make check`) → `test_command` | `--test-command` |
| `YF_SPEND_CEILING_USD` → `Guardrails.cost_ceiling_usd` | `--cost-ceiling-usd` (new; distinct from existing `--spend-ceiling-usd`) |
| `YF_OWNER`, `YF_SKILL` | already exist: `--owner`, `--skill` |
| `IsolationPolicy(isolated=False, workspace_scoped=True, ...)` | already the unattended-path default in `main` |
| `Guardrails(window=10, wall_clock_seconds=45*60, turn_ceiling=40, grace_seconds=20, question_deadline_hours=24, max_attempts=3)` | already `main`'s hard-coded constants — using the entrypoint instead of a hand-rolled call site is what stops the `max_attempts` `TypeError` class of bug from recurring |
| `CLAUDE_CODE_OAUTH_TOKEN` presence check | already covered by `docker-entrypoint.sh` for both loop entrypoints; redundant once the driver is gone, not missing |
| One `take_turn` call, not a loop (D024 ruling 1) | `--max-iterations 1` against the existing loop — no new mode |

Nothing in the driver's inventory is left unexpressed by this list. That is the change's own
verify-by-construction check, restated in `tasks.md`.

## Goals / Non-Goals

**Goals:**
- Smallest CLI surface that makes the driver deletable, not a general parameterization of every
  `Places`/`Guardrails` field.
- Zero behavior change to the collapsed single-repo case (`compose`, existing tests, interactive
  use) — every new flag is additive and optional.
- Keep the two cost quantities (`--cost-ceiling-usd` per turn, `--spend-ceiling-usd` cumulative)
  impossible to typo into each other: different flag names, different docstrings, both testable
  independently.

**Non-Goals:**
- A stable, versioned invocation contract for out-of-repo callers in general (see proposal.md
  Non-goals and the report's closing discussion) — this change fixes the one breaking-change vector
  named in the dispatch (constructing this repo's dataclasses directly) by giving it a CLI. Whether
  a CLI flag surface is itself a durable enough contract, and what "durable" would require
  (a deprecation policy, a version flag, argparse compatibility tests) is a larger question this
  change does not resolve.
- Independent `--publish-queue` / `--publish-workspace` flags. No caller wants them split; D024
  ruling 3 keeps CI's own publication in a separate, credential-holding job that never invokes this
  entrypoint at all, so there is nothing on the CI path that would use independent control if it
  existed.
- A single-turn-specific code path distinct from `--max-iterations 1`.

## Decisions

**Collapse to two path flags, not seven.** `Places` has 5 path-shaped fields plus 2 booleans.
Exposing all seven as flags would let a caller build inconsistent combinations (e.g. a
`workspace_lock` under an unrelated tree) that `Places.local` structurally cannot produce today,
and every one of the two known callers (the private driver, `run_a2web_turn.py`) only ever needs
"queue over here, workspace over there" — `ledger` and both locks are always derived, never
independently chosen. `--queue` / `--workspace` plus derivation is the smallest surface that covers
every real caller and keeps the collapsed case's `Places` byte-for-bit identical to today's.

**Derive `workspace_lock` from whether queue == workspace, not from a third flag.** Both existing
ad-hoc drivers independently converged on `<workspace>/.git/yosefactory-turn.lock` when the
workspace differs from the queue. Making this automatic rather than a flag removes a footgun (a
caller could otherwise point two different queues' turns at workspaces that share a lock file by
typo) and matches the one convention that already has two independent implementations agreeing on
it.

**Two ceiling flags, not one, and different names.** `--spend-ceiling-usd` already exists and
means "stop the loop once cumulative recorded spend crosses this since the loop started"
(`LoopBound`). The driver's ceiling means "the executor's own post-turn budget detector for this
one turn" (`Guardrails.cost_ceiling_usd`) — a different mechanism (native `--max-budget-usd` in the
executor, not the loop's own spend-log arithmetic) enforced at a different granularity. Naming them
`--spend-ceiling-usd` (existing, loop-level) and `--cost-ceiling-usd` (new, turn-level) keeps the
two greppable and distinguishable in `--help` output and in any future incident report, rather than
relying on a shared flag with two possible meanings depending on invocation shape.

**No new "one-shot" mode.** `run_loop`'s first iteration is unconditionally `WakeReason.STARTUP`
with no wait; `--max-iterations 1` already terminates after that one call. The only overhead a
single-turn CI invocation pays that the driver's direct `take_turn` call did not is: a dirty-tree
refusal check (`_refuse_if_dirty`, strictly additional safety), a committed wake sidecar in the
queue (`_record_wake`, additional traceability, harmless since `publish_queue` stays `False`), and
a mandatory `--spend-ceiling-usd` value that is structurally almost inert for a single iteration
(the cumulative check evaluates before the turn starts, when nothing has been spent yet this
process). That last point is a genuine wrinkle — flagged in the closing report, not silently
absorbed — rather than something this design claims to have smoothed over.

**`--test-command` is a plain space-separated string, split with `shlex.split`.** Matches the
driver's own `.split()` convention closely enough for the one real value (`"make check"`) while
handling a quoted argument correctly if one is ever needed, which whitespace-`.split()` does not.

## Risks / Trade-offs

- **`--spend-ceiling-usd` stays mandatory on the unattended path and is now sometimes vestigial**
  for a `--max-iterations 1` invocation, per the wrinkle noted above. Not fixed here: relaxing that
  requirement is a change to `scheduled_main`'s existing, deliberately strict contract (ADR-0003),
  which the dispatch explicitly rules out touching. A caller that finds the requirement
  meaningless for its shape still supplies a value; that is friction, not breakage.
- **`shlex.split` on `--test-command` diverges slightly from the driver's plain `.split()`** for any
  future value containing quoted arguments. Behaviorally identical for every real value seen so
  far (`"pytest -q"`, `"make check"`); called out so a future reader does not assume byte-identical
  parsing.
- **Deriving `workspace_lock` automatically means a caller cannot override it** even if some future
  topology needs to. No known caller needs that; if one arrives, it is a new, deliberate flag, not
  a retrofit of this one.
