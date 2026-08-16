## Purpose

Detects the failure this system is actually exposed to — a long run of green turns that
produce nothing — by treating the absence of progress, rather than the presence of errors,
as the thing worth alarming on.

## ADDED Requirements

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
outcomes found in it, and the position of the most recent `advanced` record if one exists
outside the window.

**Reason, carried with the rule:** an alarm that says only "stalled" invites the reader to
dismiss it. One that says "40 turns, 40 nothing-ready, last advance 12 days ago" does not.

#### Scenario: The alarm is diagnosable without reading the stream
- **WHEN** the detector fires
- **THEN** its output contains the window size, the outcome counts, and the age of the
  last `advanced` record or an explicit statement that there is none
