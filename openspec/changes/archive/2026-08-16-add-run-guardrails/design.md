# Design — add-run-guardrails

Motivation: see [proposal.md](proposal.md) — Why. Requirements: see `specs/run-guardrails/*`.
Repo state as verified: see [exploration.md](exploration.md).

## Context

`src/yosefactory/` is five empty `__init__.py` files. There is no executor, no turn loop,
and no caller for any of this. That is not an obstacle to the two detectors — they read
durable artifacts — but it means the three enforcement pieces are being written ahead of
their only caller.

One constraint dominates the mechanics: **six sessions share one working tree.** Anything
this change writes must be safe under concurrent writers and must not produce merge
conflicts in the normal case.

## Goals / Non-Goals

**Goals (design-level, beyond the proposal's scope):**
- A record format that cannot collide when two runs finish at once.
- A gap in the record stream that is *detectable* rather than merely hypothesised.
- Enforcement code testable without an agent, against real processes.

**Non-goals (design-level):**
- No executor invocation, no CLI flag construction (owned by the executor change).
- No new top-level directory, no config framework, no plugin surface.
- No retry, no backoff, no recovery. A guardrail stops things; it does not repair them.

## Decisions

### D1 — One file per turn record, not one appended file

**Chosen:** `ledger/runs/<utc-timestamp>-<run-id>.json`, one file per record.

> **Amended at apply time.** This decision originally said TOML, to match the three existing
> `ledger/*.toml` rows. Writing TOML is not in the standard library — reading is (`tomllib`),
> writing needs a third-party package — so the original form bought idiom-matching at the price
> of a dependency added for one writer. JSON costs nothing in either direction and matches the
> repository's other machine-written log, `protocol/eventlog`, which is JSONL. The human-authored
> `ledger/*.toml` rows stay TOML, which makes the format difference carry the same message as the
> directory split: these are two streams, one written by hand and one by machine.

**Over:** a single append-only `runs.jsonl`.

**Why:** concurrent writers. A shared tree with six sessions makes a single appended file a
merge conflict generator and a lost-update risk; independent files never conflict.
Append-only is then a property of the *directory* — files are created, never rewritten —
which is exactly the D002 shape. It also keeps the enum's home format identical to the
ledger a reader already knows.

**Cost:** counting records means listing a directory, and ordering depends on the timestamp
in the filename being correct. Accepted — the detector's window is small and a scan is
cheap.

### D2 — A start marker is what makes a missing record detectable

The spec requires a missing record to count as `failed`. That is unimplementable unless
something knows a record was *expected*. The supervisor writing on termination covers the
ordinary kill, but not the case that matters most: the supervisor itself dying (CI job
timeout, runner loss, power).

**Chosen:** the supervisor writes a **start marker** before the run begins and the terminal
record supersedes it. An orphan marker — a marker with no matching record — is the
detectable gap, and the detector counts it as `failed`.

```
  supervisor start ──▶ ledger/runs/<ts>-<run-id>.start
        run ...
  terminal record ──▶ ledger/runs/<ts>-<run-id>.toml     marker now satisfied

  supervisor dies  ──▶ marker with no record  =  gap  =  failed
```

**Over:** inferring expectation from the cron schedule, which would require the detector to
know the schedule and would fire on every legitimately skipped fire.

**Why it matters beyond bookkeeping:** this is the mechanism that makes "absence is the
predicate" real rather than aspirational. Without it, the most complete failure available —
the run that vanished entirely — is the one that leaves no evidence.

### D3 — `protocol/` gets exactly three things

An outcome enum, a turn-record type with its validation, and the I9 predicate signature.
Nothing else. C2 puts them there because changing them makes existing rows non-comparable;
`protocol/` staying tiny is what makes everything above it replaceable, so the bar for
adding a fourth thing is a demonstrated comparability break, not convenience.

Everything that reads or enforces — supervisor, detector, verification checks, isolation
preflight — lives in `runtime/`.

### D4 — Verification runs as a separate actor, and its independence is partial

The gate shells out to the test runner and to git, and reads their results itself. Its
independence is **actor-independence**: the entity writing the `done` transition is not the
entity that performed the work.

Stated plainly because it will otherwise be overclaimed: this is *not* foreign evidence.
The gate inspects the same repository the agent just edited. The recorded 0-versus-5 result
that motivates I9 favours foreign evidence specifically. What actor-independence buys is
the class of failure actually observed here — an agent asserting an effect that does not
exist — which is caught by looking, from any actor. A remote check (the commit visible on
the remote, CI green on the pushed branch) is strictly stronger and is where this should go
once anything pushes.

### D5 — Termination is SIGTERM, a grace window, then SIGKILL

The agent gets a chance to flush its own verdict. If it does, the record is
`enforced_by: agent`; if the grace window expires, the supervisor writes
`enforced_by: harness`. The `dirty` value is always computed by the supervisor after the
process is gone, never taken from the agent.

**Why not SIGKILL immediately:** it guarantees the least informative outcome in every case,
including the ones where the agent knew exactly what happened.

### D6 — Single-flight via an OS-level exclusive lock, non-blocking

`fcntl.flock` on a lock file, `LOCK_EX | LOCK_NB`. A run that cannot take the lock exits
immediately without work. No queue, no wait — waiting would create the resident process the
architecture forbids, and a run that starts late is worth less than one that does not run.

### D7 — Configuration lives in `pyproject.toml`

Thresholds (window size N, wall-clock seconds, turn ceiling, grace window) go under a
`[tool.yosefactory.guardrails]` table. No new top-level directory, no config discovery
order, one obvious place. They are tuning, not protocol — moving them does not make old
rows incomparable.

### D8 — The isolation preflight reports a reason code, never a path

It returns a boolean plus an enumerated reason (`clean`, `user-config-present`,
`home-unset`). Public repo: no absolute path, no home directory, no operator identity in
any output or record.

### D9 — `dirty` excludes the harness's own stream (found by a failing test, not by design)

The first run of the supervisor tests reported `dirty: true` on a clean completion. Cause: the
supervisor writes its start marker *into the tree it is about to judge*, so an unfiltered
`git status --porcelain` sees an untracked file and every run reads dirty — the field stops
distinguishing anything, silently, while appearing to work.

**Chosen:** `tree_is_dirty(repo, ignore=runs_dir)` excludes the stream directory. `dirty` means
*the agent* left work half-done, never that the harness left its own evidence behind.

Worth recording rather than fixing quietly: this is the same shape as the failure the whole change
targets. A field that is always `true` is exactly as uninformative as a run that is always green,
and neither announces itself.

## Risks / Trade-offs

- **Three guards have no caller and cannot be proven to fire in situ** → tested against
  real short-lived subprocesses (a sleeper that overruns, one that exits non-zero, one that
  writes no record, one that leaves the tree dirty). The integration receipt is recorded in
  the proposal as a debt owed by the executor change, with a named owner rather than a note.
- **A start marker orphaned by an unrelated crash reads as a stalled factory** → the alarm
  states what it saw, so an orphan is distinguishable from a run of `nothing-ready`. False
  positives here are the acceptable direction of error.
- **`dirty` is computed after termination, so it is a TOCTOU read** → accepted; it is a
  signal for the next turn, not a lock.
- **`flock` semantics degrade on network filesystems** → the tree is local; if that ever
  stops being true, the lock is the first thing to re-verify.
- **N and the wall clock are guesses until there is traffic** → they are config, and D021's
  posture is explicitly *build the detector, learn the condition, decide the limit later*.
- **The detector could become the thing nobody looks at** → it exits non-zero and is meant
  to be a scheduled check; a detector whose alarm has no consumer is itself an instance of
  the failure it detects, and that is worth re-checking once it has run for a week.

## Migration Plan

Greenfield: nothing to migrate. The three existing `ledger/*.toml` rows are untouched by
construction — a different directory, not a compatibility branch. Rollback is reverting the
commit; no state written by this change is depended on by anything else yet.

## Open Questions

Genuinely deferrable — none of these changes the specs, the approach, or the tasks:

1. **Default value of N.** Needs traffic to choose. Ships with a conservative default and a
   comment saying it is a guess.
2. **Default wall clock.** Only constraint fixed now is "well under six hours".
3. **Whether the gate should also require a remote-visible commit** (D4). Deferred until
   something in this repo actually pushes; it strengthens the check without changing its
   shape.
