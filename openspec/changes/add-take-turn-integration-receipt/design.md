## Context

See `proposal.md` - Why. Relevant current state:

- `take_turn`'s `Executor` protocol is `(frame, workspace, limits, *, run_id, runs_dir, invocation) ->
  RunResult` — no `policy` parameter. `executor.claude.run()` takes `policy: IsolationPolicy | None`
  separately. Any real executor passed to `take_turn` must be a closure that bakes a chosen policy in.
- `IsolationPolicy(isolated=True)` (D021's default) cannot do a task requiring a tool call at all —
  **confirmed by observation, not by reading `build_argv`.** A throwaway probe run against the pinned
  binary (`claude.run()` under the default `IsolationPolicy(isolated=True)`, one turn, a goal
  requiring one `Write`) came back `outcome=needs_approval`, the terminal event's own
  `permission_denials` field naming the denied `Write` call, and the target file absent from disk
  afterward — see `proposal.md` - Finding. `workspace_scoped` (or a bare opt-out) is therefore not a
  stronger option among several for a foreign workspace, it is the only posture under which an
  unattended turn can act at all, and `allowed_tools` is the only wired mechanism to pre-approve tool
  calls without an interactive prompt.
- `take_turn` commits the ledger's `.start` marker to the queue *before* it ever calls the executor,
  on every path (nothing-ready, planning, and claimed-item). This is what makes assertion 6 (crash
  leaves a legible gap) triggerable for real and for free: point `Places.workspace` at a path that does
  not exist, and `subprocess.Popen(cwd=<missing>)` inside `runtime.supervise.govern` raises
  `FileNotFoundError` before any `claude` process spawns — no mock, zero cost, and the exception
  propagates unhandled out of `take_turn` (nothing in `take_turn` or `_dispose` wraps the executor call
  in `try/except`).
- `_finish` — the one place every turn ends — calls `commit()` unconditionally, for every `Outcome`
  including `FAILED`: `[*paths, written, written.with_suffix(".start")]` land in the queue with both
  platform trailers regardless of whether the agent's own proposal was accepted. So the ledger row, the
  trailers, and the crash-gap mechanics do not depend on the agent reaching `done` — see `proposal.md` -
  Finding for why `done` itself is out of reach for an untaught agent, and why that finding changed
  what this receipt asserts.

## Goals / Non-Goals

**Goals:**
- One test file that drives the real reducer end to end, cheaply, and asserts from the subject (git
  log, files on disk, the ledger row's own contents) — never from `take_turn`'s return value or the
  flags passed in.
- Cover assertions 1-4 and 6 from the proposal (queue != workspace with a real executor; the
  workspace's own commit with zero queue bookkeeping leaking in; the ledger row; both trailers; the
  crash-gap) as independent, individually-failing checks, via a terminal outcome that needs no taught
  vocabulary from the agent.

**Non-Goals:**
- **Not the `done` path.** Reaching `done` needs vocabulary nothing currently teaches the agent (see
  `proposal.md` - Finding). This receipt does not force it and does not assert `Outcome.ADVANCED` —
  extending to `done` is the follow-up change's job once the vocabulary has a home.
- Not a general-purpose "real agent" test harness for other workflows.
- Not CI-wired (matches the existing `tests/executor/test_integration.py` posture: opt-in, real spend).
- Not a stress test of concurrency, publication (`push_repo`), or every `RunOutcome` branch — those
  are already covered against a fake executor in `tests/runtime/test_turn_cycle.py`; this receipt's
  job is specifically "a real executor was observed inside `take_turn` at least once."

## Decisions

**Executor wrapper, not a new production seam.** A local closure in the test file, not a change to
`Executor` or to `claude.run`'s signature:

```python
def real_executor(frame, workspace, limits, *, run_id, runs_dir, invocation=None):
    return claude.run(frame, workspace, limits, run_id=run_id, runs_dir=runs_dir,
                       invocation=invocation, policy=POLICY)
```

`POLICY = IsolationPolicy(isolated=False, workspace_scoped=True, allowed_tools=("Bash", "Write",
"Edit", "Read"), opt_out_reason="foreign workspace needs real tool use; isolated=True cannot do this
headless")`. `Read` was added after the first real run: the agent needs it to load the skill file at
its absolute path, and a first attempt without it produced a real, observed `permission_denials` for
`Read` — the same mechanism as the `isolated=True` finding, just against an incomplete allowlist
rather than the safe-mode floor. No `recorder` is passed — `take_turn` already declares and writes the ledger row itself
(`runs.open_run` / `runs.append` inside `take_turn`); passing a `Recorder` into `claude.run` would call
`open_run` a second time for the same `run_id` and raise `StreamError`.

**The frame stays a frame — goal and method for the work, nothing else.** D019's frame is the unit of
falsification: `goal`, `method`, `assumptions` are claims that can be *wrong*, and they land in the
item's permanent trail, compared across every run. `Invocation` (`skill`, `proposal_path`) exists
specifically so operating instructions never need to travel through the frame — a file path is not a
claim that can be wrong, only stale, and a prior worker already refused to smuggle one into `method`,
and refused the narrower version (an `instruction` key inside the frame) for the same reason one level
less visibly. So the frame here carries only the work:

```
goal:        "notes.txt in this repository ends with the line '<marker>', committed to git."
method:      "Append the line to notes.txt (creating it if absent), then `git add` and `git commit`
              the change."
assumptions: "git user.name and user.email are already configured in this repository."
```

That is a legitimate goal and a legitimate method, not a blob of reporting instructions wearing a
frame's field names. `workflows/turn-skill.md` — the actual "write one JSON event to `proposal_path`"
instruction — reaches the agent the way every other turn's does: through `Invocation.render()`,
appended after the frame. Passing `skill=<absolute path to workflows/turn-skill.md>` keeps it readable
regardless of the workspace's foreign cwd (the `Read` tool takes absolute paths), which is exactly why
nothing needs duplicating into `method` in the first place.

**The receipt asserts `Outcome.FAILED`, not `Outcome.ADVANCED`, and says why.** `verify.may_write_done`
is never reached — `_dispose` only calls it when the agent's one proposed event is literally `"done"`,
and nothing here teaches the agent to write that. The agent reliably does the real work (two real runs
now show this: a real commit lands in the workspace both times) and then writes *some* proposal, which
`take_turn` correctly refuses because the event name is not in `backlog.ITEM`'s vocabulary. The
assertion checks the outcome is `FAILED` with a comment pointing at `proposal.md` - Finding, rather
than asserting the exact refusal text — the agent's invented event name is not something this receipt
should pin, since pinning it would imply the *specific* invented word is the interesting fact, when the
interesting fact is that *some* invention was unavoidable.

**Two turns, one queue+workspace pair, for the trailer/run-id assertions.** Reusing the same `Places`
across two sequential `take_turn` calls (two backlog items, two unique markers) is cheaper and more
direct than two separate fixtures, and it is what "a second turn" means — the same queue accumulating
a second commit. This still needs no taught vocabulary: both turns are expected to end `FAILED`, and
`_finish`'s unconditional commit is what makes the trailer comparison meaningful regardless.

**Assertion 6 uses a separate, minimal `Places`.** Empty backlog (so `take_turn` takes the planning
branch, needing no claimed item) and `workspace` pointed at a `tmp_path` subdirectory that is never
created. This isolates the crash scenario from the two successful turns and keeps it a single,
obviously-correct trigger rather than something layered onto the working scenario.

## Risks / Trade-offs

- **Real spend, non-deterministic agent behaviour.** [Risk] the agent might not follow the embedded
  instructions exactly (e.g., commit message wording, extra edits). → [Mitigation] assertions check
  observable outcomes (a commit exists, the marker line is present, the gate's `done` requirements are
  met) rather than exact transcript content; `record.note` is surfaced on failure for diagnosis.
- **Flakiness from wall-clock/turn-ceiling tuning.** [Risk] too tight a guardrail turns a working run
  into a harness-enforced failure. → [Mitigation] generous but bounded values (wall clock ~180s, turn
  ceiling ~8, `cost_ceiling_usd` ~1.0) — loose enough for a trivial task, still a real ceiling.
- **Skip-guard means this never runs in an environment without the pinned `claude` binary.** Same
  trade-off the existing executor receipts already accept; not new here.

## Migration Plan

Additive only — one new test file, no rollback beyond deleting it.
