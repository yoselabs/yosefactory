# add-run-guardrails

Promotion: **D021** (executor is a thin wrapper; agent runs isolated; usage credits OFF),
**architecture.md §6** (I9 — verification is an invariant, not a guardrail) and **§7b**
(no executor has a cost cap or a wall clock; enforcement is the harness's, permanently),
**design-e2e.md §5b** (the guardrails, which are not optional). Explore notes:
[exploration.md](exploration.md).

## Why

The failure this repo is exposed to is not a crash. It is **300 green runs and zero
output** — a factory that reports success indefinitely while producing nothing, which is
indistinguishable from a working factory unless something is specifically built to tell
them apart. Nine executor surfaces were assessed and **not one has a cost cap or a
wall-clock cap**, so both enforcement and detection are ours permanently rather than
temporarily.

This change is independent of every other change in flight and is the only one that
limits the damage the others can do, which is why it goes first despite being listed last.

## What Changes

- **A turn-record shape and a four-value outcome enum** — `advanced | blocked |
  nothing-ready | failed` — frozen in `protocol/`, mandatory on every record in a new
  append-only `ledger/runs/` stream.
- **Two writers of that enum.** The agent writes its own verdict; the **supervisor**
  writes the verdict the agent cannot deliver, because a wall-clock kill is a SIGKILL and
  a killed process writes nothing. Records carry `enforced_by` (agent or harness) and
  `dirty` (was the tree left half-edited).
- **A stall detector** that fails loudly when the last N records contain no `advanced` —
  regardless of how green the rest are.
- **The absence rule, stated as a prohibition rather than left to judgement**: a missing
  turn record is `failed`, never "no data"; `nothing-ready` is never counted as success
  anywhere. Both will read as over-engineering to anyone who has not seen the failure
  above; the reason travels with the rule.
- **I9 as an invariant**: a `done` transition is writable only after an *independent*
  check confirms the claimed effect exists — tests pass, the commit is in the log, the
  tree is clean. An agent's self-report is not evidence. In this program, defects surfaced
  by repository-internal checks = 0, by foreign evidence = 5.
- **A run supervisor** enforcing a wall clock well under the 6-hour CI default and a turn
  ceiling, with `flock` (or a concurrency group) against overlapping runs.
- **An isolation policy**, typed and **default isolated**, with the chosen value recorded
  on every turn record; plus a preflight asserting a clean `$HOME`.

**Acceptance test for the whole change: a run that claims work it did not do FAILS rather
than reporting success.** That failure has already happened twice in this fleet.

## Non-goals

- **No spend cap, invented or otherwise.** D021: usage credits are OFF, so on exhaustion
  requests stop rather than flowing to metered API rates. Build the detector, learn the
  condition, decide later. (`--max-turns` stays — a loop-runaway guard is not a spend cap.)
- **No executor, no agent invocation.** Under D021 invocation belongs to the per-vendor
  thin wrapper. This change stops at policy.
- **No daemon, orchestrator, queue, or dashboard.** The supervisor is a function a job
  calls, not a process that stays up.
- **No retrofit of the three existing `ledger/*.toml` rows.** D002. They are out of the
  detector's scope *by construction* — a separate stream — rather than by a special case
  in code, because a special case is what someone deletes later without knowing why it
  was there.
- **No second user.** No multi-tenant config, no per-user policy.

## Known debts, owned by name

Two of the five pieces are runnable today against artifacts that already exist (the stall
detector, over `ledger/runs/` and git; the verification gate, over pytest and git). Three
are not: the wall clock, the turn ceiling and isolation have **no caller in this repo** —
there is no executor, no turn loop, and every `src/yosefactory/*/__init__.py` is empty.

They ship here as a supervisor API with tests that drive real short-lived subprocesses.
But **a guard whose only caller does not exist has never been proven to fire**, so:

> **Debt, owed by the executor change** (not yet dispatched): an integration receipt
> showing the wall clock, the turn ceiling and the isolation policy firing against a real
> agent invocation. Until that receipt exists, these three are tested, not proven.

The same change inherits a second obligation: **turning the isolation policy into actual
CLI flags.** The `--bare` trap is settled and must not be re-litigated — `--bare` does not
read `CLAUDE_CODE_OAUTH_TOKEN`, so on a subscription `--bare` and isolation are mutually
exclusive, and the policy object therefore never emits it.

## Capabilities

### New Capabilities
- `run-guardrails/turn-record`: the outcome enum, the turn-record shape, the two-writer
  rule, and the `ledger/runs/` append-only stream.
- `run-guardrails/stall-detection`: absence as the predicate — no `advanced` in the last
  N records, and a missing record, both fail loudly.
- `run-guardrails/verification-gate`: I9 — `done` only behind an independent check.
- `run-guardrails/run-supervision`: wall clock, turn ceiling, overlap prevention, and the
  supervisor-authored record on a harness kill.
- `run-guardrails/agent-isolation`: the isolation policy, default isolated, recorded per
  turn, with a clean-`$HOME` preflight.

### Modified Capabilities

None. `openspec/specs/` is empty; this is the repo's first spec-bearing change.

## Impact

- **`src/yosefactory/protocol/`** — first real content: the enum, the turn-record shape,
  the I9 invariant. Small and frozen by intent; C2 puts them here because changing them
  would make existing ledger rows non-comparable.
- **`src/yosefactory/runtime/`** — supervisor, detector, verification checks, isolation
  preflight. Replaceable without breaking old rows.
- **`ledger/runs/`** — new append-only stream. The three existing rows are untouched.
- **Config** — thresholds (N, wall-clock seconds, turn ceiling) are tuning, not protocol.
- **Public repo** — no config surface may carry a token, a credential, or a literal
  `$HOME` path; the isolation preflight returns a boolean and never echoes the path.
- **No new runtime dependencies** beyond the existing stack.
