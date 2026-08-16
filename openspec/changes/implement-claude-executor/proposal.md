# implement-claude-executor

Promotion: **D021** (*"thin wrappers implementing the same interface so core will be
agnostic"*; the agent runs isolated), **architecture.md §7b** (the executor interface and its
four rules), **S182** (three endings), **S187** (`dirty`, and the observer inside the thing it
observes). Explore notes, including the live measurements this proposal rests on:
[exploration.md](exploration.md).

## Why

`add-run-guardrails` shipped a wall clock, a turn ceiling and an isolation policy **with no
caller**. Its own proposal says so and names the debt: *"a guard whose only caller does not
exist has never been proven to fire."* `govern()`'s `turns_taken` parameter is a seam with
nothing on the other side of it.

This change is that caller. It is the first thing in the repository that starts a real agent,
and therefore the first place the guardrails either fire or are shown not to.

The second reason is the one D021 turns on. Three lanes are coming — `claude -p`, `codex exec`,
`grok -p` — and the decision was one shape across all three rather than a vendor SDK per lane.
The shape is only real once something implements it. This is the reference implementation of
the interface, built against the lane whose credential actually exists today.

## What Changes

- **A new `src/yosefactory/executor/` package** holding the interface and one implementation.
  Nothing else in the repository imports a vendor name.
- **Three of §7b's four entry points**: `run`, `preflight`, `resolveVersion`.
  `capabilities(version)` is **deferred with reason** — see below.
- **`run(frame, workspace, limits) -> RunResult`**, the whole caller-facing surface. The caller
  is capability-blind by construction: it always gets its budget honoured and an outcome, and
  never branches on what the binary can do (§7b rule 3).
- **`preflight()` — once per job, never per turn.** A ~1-token canary, because silent auth
  expiry is otherwise indistinguishable from a bad task: it fails a job in seconds with an
  unambiguous reason instead of twenty minutes in. Token expiry is treated as unknown and
  checked, never assumed. The measured cost is $0.25 (exploration.md §2), which is worth
  paying once per job and is not worth paying per turn.
- **`resolveVersion()` — capabilities belong to the binary, not the adapter.** `preflight()`
  asserts the pinned version and fails `version_mismatch` when the binary moves.
- **A stream reader over `--output-format stream-json`** that distinguishes the two endings
  measured on this lane: `system|post_turn_summary` ends a *turn*, `type: "result"` ends the
  *run*. It supplies `govern()`'s two callables — a live turn count from the former, the
  verdict from the latter.
- **The verdict rule, enforced rather than documented.** `RunResult.outcome` is derived from
  the terminal event only. The exit code is recorded as evidence and is never consulted to
  decide the outcome; `143` maps to `cancelled`. **No terminal event is `failed`, on any exit
  code including 0.**
- **`rate_limit` as its own outcome**, driven by the native `rate_limit_event` stream type and
  by `api_error_status` — not by matching an error string. A factory starved of quota must not
  read as a broken model.
- **The isolation policy turned into invocation.** `IsolationPolicy` becomes explicit
  `--settings`, `--mcp-config`, `--strict-mcp-config` and `--allowedTools` arguments; repo
  config is treated as hostile. `--bare` is never emitted — settled, and not re-litigated here.
- **Isolation asserted from the stream, not from the flags.** `system|init` reports
  `memory_paths`, `mcp_servers`, `skills` and `plugins`. An isolated run that reports repo
  memory or unexpected MCP servers fails rather than proceeding. This is stronger than the
  assertion the policy could make on its own, and it is available only here.
- **A version pin.** Behaviour measured on 2.1.225; a capability claim without a passing check
  against a pinned version is invalid (§7b rule 4).

## Acceptance

Both are integration receipts, not unit tests:

1. **One real bounded `claude -p` invocation** producing a structured outcome derived from the
   terminal event.
2. **A run that exceeds its wall clock** produces `failed` with `enforced_by: harness` and a
   correct `dirty` — where "correct" means S187's definition: `dirty` is true when *the agent*
   left work half-done, never when the harness left its own evidence in the tree.

Together these discharge the debt `add-run-guardrails` recorded by name.

## Non-goals

- **No second executor.** Codex and Grok lanes are not written here. The interface is proven by
  one implementation; a second one built speculatively proves nothing about agnosticism.
- **`capabilities(version)` is deferred, with the reason recorded so a successor inherits the
  argument rather than the omission.** A three-state capability map exists to manage
  heterogeneity between executors. There is one executor. A negotiation protocol designed
  against a single participant degenerates into the union of everything that participant does,
  which is the failure the capability review itself warned about. It arrives with the **second**
  executor, when its shape can be derived from a real disagreement instead of guessed.

  **The rule that survives the deferral, and is specified now:** every capability that is
  `absent` must declare its harness-side emulation, or the adapter fails registration. With one
  executor this is trivially satisfiable; stating it now is what stops "we will add cost limits
  later" from shipping.
- **No changes to `protocol/`.** The outcome vocabulary is a named handoff, not a workaround
  left lying around — see below.
- **No cost cap.** D021: usage credits are OFF, so exhaustion stops requests rather than
  flowing to metered rates. Cost is recorded from `total_cost_usd`, not enforced.
- **No wall clock or turn ceiling of its own.** They exist in `runtime/supervise.py`. This
  change wires to them; rebuilding them here is the failure D021 guards against.
- **No retry, no resume, no session reuse.** The caller is a job that dies at the end of it.
- **No daemon, no queue, no dashboard, no second user.**

## Handoff — `TurnRecord.failure_kind`, owned elsewhere

`RunResult.outcome` carries `rate_limit` as its own value, as §7b rule 3 requires. A
`TurnRecord` cannot: `protocol.Outcome` has four values and is frozen.

The right diagnosis is not that the two conflict. **They answer different questions in one
field.** `Outcome` answers *did the turn advance?* — and widening it would make every existing
row incomparable, which is exactly what C2 freezes it against. `rate_limit` answers *why did it
fail?*, which is a sibling field, not a fifth value.

So: a `failure_kind` field on `TurnRecord` is dispatched separately and owned by whoever holds
`protocol/`. **Until it lands, this change carries the reason in `TurnRecord.note`** — typed
correctly in `RunResult`, degraded only at the record boundary. When `failure_kind` arrives the
`note` workaround is replaced by a typed field and the record becomes queryable, which is what
rule 3 actually demands. A starved factory must not read as a broken model.

## Resolved — the stdout capture

`govern()` inherited the parent's stdout, so the terminal event that *is* the verdict was
unreachable. Resolved by adding a single additive parameter, `stdout: Path | None = None`,
under a narrow grant: the file's author has retired, and ownership of an unowned file returns
to the director. The default preserves existing behaviour and every existing `test_supervise.py`
case passes unchanged — which is the test of whether it was truly additive.

The shell-redirect alternative was rejected on analysis rather than taste: it would make
`_terminate` signal the shell instead of the agent, destroying the grace window in which the
agent flushes its own verdict. Detail in exploration.md §4.

## Capabilities

### New Capabilities
- `claude-executor/run-interface`: `run(frame, workspace, limits) -> RunResult`, the outcome
  vocabulary, and the capability-blind caller rule.
- `claude-executor/terminal-verdict`: the terminal event is the verdict; absence of one is
  failure; the exit code is evidence only.
- `claude-executor/stream-endings`: turn ending and run ending are distinguished, and the turn
  count is live rather than terminal.
- `claude-executor/isolation-invocation`: policy to CLI arguments, `--bare` never emitted, and
  isolation asserted from the init event.
- `claude-executor/preflight`: the once-per-job canary, the pinned version assertion, and the
  absent-capability-declares-its-emulation registration rule.

### Modified Capabilities
- `run-guardrails/run-supervision`: gains its first caller, and with it the integration receipt
  the original change recorded as owed; and an additive `stdout` parameter.

## Impact

- **`src/yosefactory/executor/`** — new, and the only place a vendor name appears.
- **`src/yosefactory/runtime/supervise.py`** — one additive parameter, granted narrowly. No
  other edit.
- **Public repo** — no credential, token or home-rooted path reaches a record or a log; the
  session id from the stream is not written to the turn record.
- **No new runtime dependencies.** `claude` is an external binary, resolved on `PATH`.
