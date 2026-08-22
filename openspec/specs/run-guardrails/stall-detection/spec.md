# run-guardrails/stall-detection Specification

## Purpose
Detects the failure this system is actually exposed to — a long run of green turns that
produce nothing — by treating the absence of progress, rather than the presence of errors,
as the thing worth alarming on.
## Requirements
### Requirement: Absence of `advanced` is the alarm condition

The stall detector SHALL examine the most recent N turn records and fail loudly when none
of them carries `outcome: advanced`. N is configurable.

The detector SHALL NOT require any record to be `failed` in order to fire. A window
composed entirely of `blocked` or `nothing-ready` records — every one of them a
non-error — is a stall and MUST fire.

**Reason, carried with the rule:** the predicted failure is not a crash. It is 300 green
runs and zero output, which is indistinguishable from a working factory to any check that
looks for errors.

#### Scenario: An all-green window with no progress fires the alarm
- **WHEN** the last N records are all `nothing-ready` or `blocked` and none is `advanced`
- **THEN** the detector fails loudly

#### Scenario: A single advance clears the window
- **WHEN** at least one of the last N records carries `advanced`
- **THEN** the detector does not fire

#### Scenario: Failures alone do not mask the stall condition
- **WHEN** the last N records mix `failed` and `nothing-ready` with no `advanced`
- **THEN** the detector fails loudly

### Requirement: A missing record is a failure, never missing data

Where a run was expected to append a record and no record exists, the detector SHALL treat
the gap as equivalent to `failed`. It SHALL NOT skip the gap, treat it as absent data, or
narrow its window to the records that happen to exist.

**Reason, carried with the rule:** a run that produced no terminal record is a run whose
outcome nobody knows, and an unknown outcome that is silently skipped is how a broken
factory reports success. Absence is the evidence, not the lack of it.

#### Scenario: A gap counts against the window
- **WHEN** an expected record is absent from the stream
- **THEN** the detector counts that position as `failed` rather than skipping it

#### Scenario: A window of nothing but gaps fires
- **WHEN** no records exist at all for the expected window
- **THEN** the detector fails loudly rather than reporting no data

### Requirement: The detector runs on a schedule, independent of any run

The detector SHALL be invocable without any run in progress, reading only the durable
record stream, and SHALL signal failure through a non-zero exit status so a scheduled
invocation surfaces it without a human reading logs.

#### Scenario: Detection needs no live run
- **WHEN** the detector is invoked with no agent running
- **THEN** it evaluates the stream and returns a verdict

#### Scenario: A stall is visible to a scheduler
- **WHEN** the detector fires
- **THEN** it exits non-zero and names the window it examined and what it found

### Requirement: The alarm states what it saw

When the detector fires, its output SHALL state the size of the window examined, the
outcomes found in it, the position of the most recent `advanced` record if one exists
outside the window, and **the classification of the window together with the recorded
reasons that produced it**.

**Reason, carried with the rule:** an alarm that says only "stalled" invites the reader to
dismiss it. One that says "40 turns, 40 nothing-ready, last advance 12 days ago" does not.
The classification is subject to the same test: "starved" alone invites the reader to wait
indefinitely, and naming the reasons behind it lets them see when waiting stopped being the
right answer.

#### Scenario: The alarm is diagnosable without reading the stream
- **WHEN** the detector fires
- **THEN** its output contains the window size, the outcome counts, and the age of the
  last `advanced` record or an explicit statement that there is none

#### Scenario: The alarm names why it chose its classification
- **WHEN** the detector fires on a starved window
- **THEN** its output names the classification and the recorded reasons found in the window

### Requirement: A non-progressing window is classified as starved or broken

When the detector finds no progress in its window, it SHALL classify the window as
**starved** or **broken** and name that classification in its verdict. The classification
SHALL be derived from the recorded reason each failed position carries, never inferred from
the shape of the window.

Exactly two recorded reasons are starvation: the run was stopped for want of quota, and the
run was stopped for want of budget. Every other reason is breakage. In particular, a failure
to authenticate SHALL be classified as breakage — it stops requests exactly as starvation
does and is resolved only by a human, so classifying it as starvation would instruct the
operator to wait out the one failure they must act on.

**Reason, carried with the rule:** a factory starved of quota and a factory whose model is
broken demand opposite actions — wait, versus fix. [[D014]] makes root-causing the platform
mandatory on a breach and forbids patching the gap, so an alarm that names starvation as
breakage spends a real investigation on a healthy factory.

#### Scenario: A window of quota failures is named starved
- **WHEN** the window contains no progress and every failed position was stopped for want of
  quota or budget
- **THEN** the verdict names the window starved

#### Scenario: An authentication failure is breakage
- **WHEN** the window contains no progress and its failures are authentication failures
- **THEN** the verdict names the window broken

#### Scenario: The classification is read, not deduced
- **WHEN** a failed position carries no recorded reason
- **THEN** the detector SHALL NOT infer one from the surrounding window

### Requirement: Starvation never suppresses the alarm

A starved window SHALL raise an alarm. The classification SHALL change what the alarm is
called and SHALL NOT change whether it fires. Both the starved and the broken verdict SHALL
signal failure through a non-zero exit status, and the two SHALL use **distinct** non-zero
statuses so a scheduled invocation can act differently on each without parsing prose.

**Reason, carried with the rule:** a factory permanently out of quota produces nothing, which
is the exact failure this detector exists to catch. This capability already forbids the twin
of the suppression argument — `nothing-ready` is not success — and a budget-exhausted turn is
`nothing-ready` wearing a reason.

#### Scenario: A starved window still fails loudly
- **WHEN** the window is classified as starved
- **THEN** the detector exits non-zero

#### Scenario: A scheduler can tell the two apart without reading prose
- **WHEN** one invocation reports starvation and another reports breakage
- **THEN** their exit statuses differ, and both are non-zero

#### Scenario: Progress still clears the window
- **WHEN** the window contains at least one `advanced` record
- **THEN** no alarm is raised and the classification is not reported

### Requirement: Any position that is not starvation makes the window broken

A window SHALL be classified as starved only when it contains no progress, contains at least
one starvation failure, and contains no position that is anything other than a starvation
failure. Any other composition SHALL be classified as broken.

This SHALL hold for a gap in particular. A position with no record carries no reason, and an
unattributable position SHALL NOT be excused as starvation.

**Reason, carried with the rule:** a single crash among starved turns means something is also
broken, and the broken thing is the one a human can act on. A `nothing-ready` or `blocked`
position means the factory was free to try and had nothing to do, which is a stall rather than
starvation. Excusing a gap would let the least informative position in the stream produce the
least alarming verdict.

#### Scenario: One crash among starved turns is breakage
- **WHEN** the window contains starvation failures and at least one crash
- **THEN** the verdict names the window broken

#### Scenario: A gap is never starvation
- **WHEN** the window contains starvation failures and at least one gap
- **THEN** the verdict names the window broken

#### Scenario: An idle backlog is not starvation
- **WHEN** the window contains starvation failures and at least one `nothing-ready` record
- **THEN** the verdict names the window broken

### Requirement: The loop's own CLI entrypoint surfaces the stall verdict in its exit code

`runtime/loop.py`'s `main()` (and, through it, `scheduled_main()` — the entrypoint the scheduler
template `ops/launchd/dev.yosefactory.loop.plist.template` already names) SHALL evaluate the stall
detector against the same ledger `run_loop` just wrote to, after `run_loop` returns and before the
process exits, and SHALL exit with the detector's own non-zero status (`STALLED` → 1, `STARVED` → 2)
rather than unconditionally returning 0. The detector's report line SHALL be printed regardless of
verdict, exactly as `stall.main()` already prints it standalone.

This is in addition to, not instead of, `stall.py` remaining invocable on its own — nothing about
this requirement narrows or replaces "the detector runs on a schedule, independent of any run."

**Reason, carried with the rule:** the detector was already correct and already invocable — S1021
found that nothing in this repository's own process ever *called* it. A `.github/workflows/*.yml`
that has never fired is its own catalogued failure mode (S195); wiring the exit code of an entrypoint
this repository already ships, and a scheduler template already names, costs one function call and
makes a freeze visible to whatever already invokes that entrypoint, without inventing new scheduling
infrastructure this repository has deliberately not built yet.

#### Scenario: A stalled ledger makes the CLI exit non-zero

- **WHEN** `main()` runs `run_loop` to completion and the resulting ledger's stall verdict is
  `STALLED`
- **THEN** the process exits with status 1
- **AND** the stall report line is printed to stdout before exit

#### Scenario: A starved ledger exits with its own distinct status

- **WHEN** the resulting ledger's stall verdict is `STARVED`
- **THEN** the process exits with status 2, distinguishable from `STALLED`'s status 1

#### Scenario: A healthy ledger exits zero exactly as before

- **WHEN** the resulting ledger's stall verdict is `OK`
- **THEN** the process exits 0, as `main()` already did before this requirement

