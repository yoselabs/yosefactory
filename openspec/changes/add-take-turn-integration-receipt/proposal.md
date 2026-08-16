## Why

No K promotion id — this change was dispatched directly against a gap another worker verified: every
integration test in `tests/executor/test_integration.py` drives `executor.claude.run()` in isolation.
**Not one drives `runtime.turn.take_turn` against a real executor.** The reducer's behaviour with a
real agent inside it — real `Places` where queue and workspace are different repositories, a real
claim/act/dispose/commit cycle, real commit trailers — has never been observed. A green `make check`,
strict-valid specs and clean types are all silent about that.

## What Changes

- **New test file** `tests/runtime/test_turn_integration.py`, skip-guarded exactly like the existing
  executor receipts (skip when `claude` is absent or the pinned version has moved).
- Drives `take_turn` end to end: real `claude` binary, a real second (foreign) workspace repository,
  a trivial one-line-file task, real guardrails (wall clock, turn ceiling, `--max-budget-usd` via
  `Guardrails.cost_ceiling_usd`).
- Asserts, each independently and from the subject (git log, files on disk, the ledger row's own
  contents) rather than from `take_turn`'s return value or the flags passed to it:
  1. the turn runs against `Places` with queue != workspace and a real executor, and advances;
  2. the workspace receives the agent's own commit and gets zero queue bookkeeping written into it;
  3. `ledger/runs/<stamp>-<run_id>.json` exists in the queue with a `run_id` matching the returned
     `TurnRecord.run_id`;
  4. the queue's commits carry both `Co-Authored-By: yosefactory` and `Yosefactory-Run: <run_id>`,
     read via `git log --format=%(trailers)`;
  5. a second turn: the co-author trailer is byte-identical across both turns' commits, and the two
     run ids are genuinely independent;
  6. a turn that crashes before reaching `commit()` (triggered for real, not mocked, by pointing
     `Places.workspace` at a path that does not exist, so `subprocess.Popen` fails before any `claude`
     process spawns) leaves the ledger's `.start` marker committed in the queue with no matching
     `.json` — a legible gap, not a lie.

No production code changes. If `take_turn` genuinely cannot do any of the above end to end, that is
the finding this change exists to surface — the test is not adjusted to make it pass.

## Finding: `isolated=True` cannot do work headlessly — observed, not inferred

While designing the executor wrapper for the foreign-workspace scenario, reading `isolation.py`
suggested that `IsolationPolicy(isolated=True)` (the default, per D021) emits `--permission-mode
manual`, and that headlessly nothing can answer a manual approval prompt. **This was checked against
the running binary rather than left as a reading of `build_argv`:**

A throwaway probe — `claude.run()` under `IsolationPolicy(isolated=True)` (default), one turn, a goal
requiring a single `Write` tool call, `claude 2.1.225` — produced:

```
outcome:            needs_approval
permission_denials: [{tool_name: 'Write', tool_use_id: '...', tool_input: {...}}]
file written?:       False        (the target file does not exist on disk afterward)
cost:                $0.0708
```

**The denial is directly observed** (the terminal `result` event's own `permission_denials` field,
and the absence of the file it would have produced), not inferred from the flag passed. One
discrepancy worth recording rather than chasing: the same run's `init` event reports
`permissionMode: "default"`, not `"manual"` — the value the flag actually names. The *mechanism name*
doesn't match what was passed; the *denial* is real regardless (nothing approved the call, nothing was
written). This is the same shape as the already-recorded `--strict-mcp-config` case (a flag accepted
and not doing what its name says) and is flagged here, not investigated — out of this change's scope.

**Consequence for D021.** D021 set `isolated` as the default posture and `workspace_scoped` as an
opt-in for a repository whose conventions are worth admitting. This observation makes it structural
rather than a preference: **an isolated, unattended run can read and talk and cannot act.** For any
`take_turn` invocation whose task requires a tool call — which is every real one — `workspace_scoped`
(or an explicit opt-out with `allowed_tools`) is not the recommended posture for a foreign workspace,
it is the *only* posture under which an unattended turn can do anything at all. This reverses which of
the two is the exception, and is written back to K project 160 against D021 separately from this
change (a corpus write-back, not a code change here).

## Finding: the `done` transition has no live path for an unattended real agent

**Observed on a real run, not inferred.** With the `Read`-denial above fixed (the executor wrapper's
`allowed_tools` widened to include `Read`), a second real run was driven against the pinned binary:
the agent did the actual work correctly —

```
workspace notes.txt:   "receipt-a3fbd159"
workspace git log:     199717e "Add notes.txt with receipt line"   (clean, real, correct commit)
```

— and then wrote its completion proposal as `{"event": "goal_met", "goal": "...", "file": "notes.txt",
"created": true, ...}`. `take_turn` refused it: `unknown event 'goal_met'`. Turn recorded `FAILED`.

**This is not a defect in the reducer.** `take_turn` was *right* to refuse an event it had never seen
— `backlog-item-format`'s own requirement is that an unknown event fails loudly rather than being
absorbed. The gap is one layer up: `workflows/turn-skill.md` — the only thing telling the agent how to
report — says only `{"event": "<name>", "...": "the fields that event carries"}`; `<name>` is a
literal placeholder. Nothing anywhere reachable by an unattended agent names the actual vocabulary
(`done` requires `effects` and `verified_by`; the full table lives only in
`openspec/specs/backlog-item-format/spec.md`, which nothing points the agent at). **Every existing
test of the `done` transition uses a fake executor, which sidesteps this by construction** — this is
the first time anything has driven it with a real one, and that is why nothing caught it before.

**Two things this is not, stated because both were live options and both were rejected:**
- **Not a frame problem.** The event name and its required fields are reporting mechanics, not goal or
  method — D019's frame is not the right home for them, and putting them there would smuggle protocol
  vocabulary into the one thing this platform compares run-to-run for falsifiability.
- **Not something this change fixes.** The fix is production content (teaching the vocabulary
  somewhere an agent can reach it) and is out of this change's declared scope (`skip_specs: true`, no
  production code changes). It is deliberately deferred to its own change, explored and proposed
  properly, so it is not sneaked into an `apply`. Two questions that change will need to argue rather
  than assume: whether `workflows/turn-skill.md`'s 120-word ceiling should legitimately rise to carry
  it (the ceiling exists to keep *workflow* — sequencing, invariants — out of the prompt; the event
  vocabulary is the *interface*, not workflow, so the same argument may not apply), and whether the
  skill is even the right home versus pointing at the spec by an absolute path through `Invocation`
  (which already carries `skill`, and absolute is what makes a path work from a foreign cwd).

**Consequence for this change's scope.** This receipt is narrowed to what it can honestly prove
without the agent needing any taught vocabulary: `Places` separation, the workspace's own real commit,
the ledger row, both commit trailers (written on every terminal record regardless of outcome — see
`runtime/turn.py`'s `_finish`, which always calls `commit()`), and the crash-before-commit gap. The
`done` path — the receipt D014 actually needs — is deferred to the follow-up change and extends this
one once the vocabulary has somewhere to live.

## Capabilities

### New Capabilities
(none — see `skip_specs: true` in `.openspec.yaml`)

### Modified Capabilities
(none — this exercises already-shipped behaviour: `turn-cycle`, `turn-places`, `commit-attribution`,
`claude-executor`, `run-guardrails`. No requirement in any of their specs changes.)

## Non-goals

- **No new production capability.** This is a test artifact against existing behaviour.
- **No relaxation of `verify.may_write_done`, any `IsolationPolicy` posture, or any guardrail** to make
  the test pass. A failure here is a finding to report, not a gate to soften.
- **No CI wiring.** Like the existing executor receipts, this runs opt-in (real binary, real spend) —
  wiring it into an automated pipeline is a separate, later decision.
- **No coverage of every `take_turn` branch.** This is one receipt for the never-observed path
  (real executor x split `Places`), not a full integration suite.

## Impact

- **`tests/runtime/test_turn_integration.py`** — new file only.
- No changes to `src/`.
- **Real spend against the operator's Claude subscription, end to end: $1.63.** The director approved
  the cap ($1) as a pre-run guess, and approved the final $0.40 explicitly once the reason for going
  over it was on record. Every dollar bought a real, informative finding except one:
  - $0.07 — the `isolated=True` probe (proposal.md - Finding, first section) — confirmed by
    observation, not inferred from the flag path
  - $0.25 — first receipt run, found the `Read`-tool omission
  - $0.20 — second receipt run, found the vocabulary gap (proposal.md - Finding, second section)
  - $0.18 — narrowed receipt (`Outcome.FAILED` path), confirmed passing
  - **$0.53 — a real `claude` process spawned by a design mistake in the crash-before-commit test,
    not requested by anything above.** `Places.workspace` was pointed at a path that did not exist,
    expecting `subprocess.Popen(cwd=<missing>)` to fail before any process spawned. It didn't:
    `single_flight`'s lock acquisition does `lock_path.parent.mkdir(parents=True, exist_ok=True)`
    *before* `Popen` runs, which silently created the "missing" directory as a side effect, so `Popen`
    found a directory (empty, not a git repo) and a real agent ran against it — correctly detecting
    it wasn't a git repository and correctly getting refused for the event it proposed, but for $0.53
    nobody needed to spend. The code under test destroyed the test's own precondition, as a side
    effect of acquiring a lock, and `pytest.raises(FileNotFoundError)` passing or failing said nothing
    about it — this was caught by reading the ledger's own `.json` record, not the test's outcome.
    **Fixed for $0**: the test now points `workspace` at a regular *file*, which makes
    `mkdir(parents=True)` raise `NotADirectoryError` immediately, before any subprocess — verified free
    (1.16s, no transcript file produced). The mistake and its fix are recorded in the test's own
    docstring so a later reader sees why this form was chosen over the more obvious one, rather than
    "simplifying" it back.
  - $0.20 + $0.19 = $0.40 — the second-turn scenario (byte-identical trailer, independent run ids),
    approved and run after the report above. Both turns ended `FAILED` as expected; the two run ids
    differ and the `Co-Authored-By: yosefactory ...` trailer is byte-identical across both commits.
  - The follow-up change (the vocabulary/`done` path) will cost more when it lands; no run for it has
    happened yet.
