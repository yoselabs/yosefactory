# run-guardrails/stall-detection — delta

## ADDED Requirements

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

## MODIFIED Requirements

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
