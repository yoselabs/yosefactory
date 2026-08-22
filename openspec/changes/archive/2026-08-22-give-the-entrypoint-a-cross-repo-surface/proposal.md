## Why

`runtime/loop.py::main` — the entrypoint `yosefactory-loop`/`yosefactory-loop-scheduled` install —
builds its `Places` with `Places.local(repo)`, collapsing all five `Places` seams (queue, ledger,
queue_lock, workspace, workspace_lock) plus the two publish booleans onto one path argument.
`main`'s own docstring calls this deliberate and names "a caller that imports `run_loop` directly"
as the way to run cross-repo. `turn-places` (this repo's own spec) already gives `Places` the
capability to address queue and workspace separately — it has since `add-turn-loop`-era work — but
nothing on the CLI surface exposes it.

That gap is no longer theoretical. `yoselabs/factory-state` (K D026: private queue+runner repo,
public workspace repo) needs exactly this split and cannot reach it through the shipped entrypoint,
so it carries a hand-written driver (`runner/take_one_turn.py`) that constructs `Places`,
`Guardrails`, and `IsolationPolicy` directly — machine code living outside this repository. That
driver has already caused two production failures: a `TypeError` when `Guardrails` gained a
required `max_attempts` field (ADR-0012) and the driver's call site was never updated, caught only
when a container started; and, earlier, hand-rolled workarounds for the spend-path and mount
topology that accumulated because the entrypoint could not express the split at all. Every field
this repo adds to a dataclass another repository constructs directly is a breaking change
discovered at runtime, in a container, after a pull — never at review time, because nothing in
this repository knows that caller exists.

No K project 160 promotion id governs this change — it was dispatched directly this session,
citing K decisions D026 (queue/workspace split), D024 (CI topology: no forge credential, one turn
per invocation, publication is a separate job), ADR-0003 (`--max-iterations` has no default; no
infinite mode) and ADR-0012 (`Guardrails.max_attempts`) as background the CLI surface must not
contradict.

## What Changes

Give `runtime/loop.py::main` (and therefore `scheduled_main`) a small set of new flags sufficient
that `factory-state`'s driver can be deleted, not merely shortened:

- `--queue` and `--workspace`, each an optional path defaulting to the existing `repo` positional.
  When both resolve to the same path, `Places` is built exactly as `Places.local` builds it today
  (same lock file for both roles) — the collapsed single-repo case is bit-for-bit unchanged. When
  they differ, `workspace_lock` is keyed to the workspace's own identity
  (`workspace/.git/yosefactory-turn.lock`), matching the convention both existing ad-hoc drivers
  (`scripts/run_a2web_turn.py`, the private driver) already use by hand.
- `--test-command`, a space-separated string overriding the hard-coded `DEFAULT_TEST_COMMAND`
  (`pytest -q`), so a foreign workspace's own gate (a2web's `make check`) can be named.
- `--cost-ceiling-usd`, feeding `Guardrails.cost_ceiling_usd` (the per-turn budget the executor's
  `--max-budget-usd` enforces after the fact) — kept explicitly distinct in name and docstring from
  the existing `--spend-ceiling-usd`, which bounds the *loop's* cumulative spend across iterations,
  a different quantity the driver never touched.

`--publish` is not changed: it already collapses `publish_queue`/`publish_workspace` to one
boolean, and no known caller — including the CI driver, which sets both `False` — ever wants them
independent. Named as a considered non-change, not an oversight.

A single turn against a split queue/workspace (what the driver does today) is already expressible
with the unchanged `--max-iterations 1`: `run_loop`'s first iteration always fires immediately
(`WakeReason.STARTUP`), so no loop-specific behavior needs to change for the one-shot case — it
only needed somewhere to point `queue` and `workspace` separately.

## Capabilities

### New Capabilities
- `containerized-loop/cross-repo-invocation`: the entrypoint's CLI can address queue and workspace
  separately, name a foreign test command, and set a per-turn cost ceiling independent of the
  loop's cumulative spend ceiling.

### Modified Capabilities
(none — `turn-places` already specifies `Places`'s own addressability; this change only wires the
existing capability through the CLI a scheduler or container actually invokes)

## Non-goals

- Not building a stable, versioned invocation contract for out-of-repo callers (a CLI-vs-import
  API-stability question larger than this change) — flags fix the immediate breaking-change vector
  by giving `factory-state` a CLI instead of an import; whether that is *sufficient* is reported
  back, not built here.
- Not making `publish_queue`/`publish_workspace` independently settable from the CLI — no caller
  needs it and D024 ruling 3 keeps CI's own publication in a separate credential-holding job outside
  this entrypoint's reach entirely.
- Not adding a "single turn, no loop" mode distinct from `--max-iterations 1` — the existing
  behavior already satisfies the driver's "one turn, not a loop" requirement (D024 ruling 1)
  without a new code path.
- Not touching `CLAUDE_CODE_OAUTH_TOKEN` presence checking — `docker-entrypoint.sh` already checks
  it for both `yosefactory-loop` and `yosefactory-loop-scheduled` before either runs; the driver's
  own duplicate check becomes redundant, not missing, once the driver is deleted.

## Impact

- `src/yosefactory/runtime/loop.py` — `main`'s argparse surface and the `Places` construction it
  feeds.
- `openspec/specs/containerized-loop/cross-repo-invocation/spec.md` — new.
- `tests/runtime/test_loop.py` (or equivalent) — a test exercising the CLI end-to-end across two
  temporary git repositories, per the dispatch's verification requirement.
- No change to `turn.py`, `Places`, `Guardrails`, or `verify.py` — every seam this change exposes
  already exists; only the CLI's construction of them changes.
