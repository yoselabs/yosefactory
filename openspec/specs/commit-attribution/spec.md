# commit-attribution Specification

## Purpose

Defines what a commit produced by the platform carries so that a later reader can tell it from a
hand-driven one and reach the run record that explains it. D014 counts commits produced through the
platform; without a marker on the artefact itself, the count cannot be taken and a breach cannot be
root-caused.
## Requirements
### Requirement: A platform-produced commit identifies the platform as a co-author

Every commit the platform produces SHALL carry the trailer
`Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>`.

The identity is **frozen**. Every commit ever written is compared against every other commit, so a
later change to the name or the address splits one author into two and silently breaks the count
this trailer exists to make possible.

**Reason, carried with the rule:** D014's unit of measurement is *a commit produced through the
platform*. A hand-driven session and a platform run otherwise emit identical trailers, so the
criterion cannot be scored from its own artefact.

#### Scenario: A commit made by the platform names it

- **WHEN** the platform produces a commit
- **THEN** the commit message carries `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>`
- **AND** a reader separates it from a hand-driven commit without reading the diff

#### Scenario: The identity is byte-identical across commits

- **WHEN** two commits are produced by the platform at any distance in time
- **THEN** both carry the same co-author name and address exactly
- **AND** a tool grouping commits by co-author identity counts them as one author

### Requirement: A platform-produced commit reaches its run record

Every commit the platform produces SHALL carry the trailer `Yosefactory-Run: <run_id>`, naming the
run whose turn record accounts for the work.

The value SHALL be the same run id the turn-record stream is keyed by, so that a reader holding only
the commit can locate the record without a search.

**Reason, carried with the rule:** D014 has two halves. The count needs only a name; *"on breach,
root-cause the platform"* needs the receipt. A trail that dead-ends at a name leaves a reader
reading the diff and guessing at what the run decided, when the run record already records outcome,
who enforced it, whether the tree was left dirty, and under what isolation it ran.

#### Scenario: A commit leads to the record that explains it

- **WHEN** a reader holds a platform-produced commit and nothing else
- **THEN** the `Yosefactory-Run` value names a run in the turn-record stream
- **AND** the corresponding record is located by that value alone

#### Scenario: Both trailers appear on the same commit

- **WHEN** the platform produces a commit
- **THEN** the message carries both `Co-Authored-By: yosefactory <...>` and `Yosefactory-Run: <run_id>`
- **AND** neither substitutes for the other

### Requirement: Identity and receipt are separate trailers

The run id SHALL NOT be carried inside the co-author identity, and the co-author identity SHALL NOT
be carried inside the run trailer. Two questions, two fields.

**Reason, carried with the rule:** git keys a co-author by its identity string. Folding the run id
into that string would register every run as a different co-author, so a tool grouping by author
would report N platform authors rather than N platform commits — destroying the count the co-author
trailer exists to enable. This is the same separation that keeps `failure_kind` out of `outcome`.

#### Scenario: The count survives many runs

- **WHEN** many commits are produced across many distinct runs
- **THEN** grouping by co-author identity yields exactly one platform author
- **AND** the distinct run ids remain individually readable from their own trailer

### Requirement: Trailers are appended, never replacing what the message already carries

Applying the platform's trailers SHALL preserve every trailer and every line the message already
holds, including a harness-emitted `Co-Authored-By`. The platform SHALL NOT remove, rewrite, or
deduplicate an existing trailer, and SHALL NOT overwrite the message body.

Co-authorship is a set, not a slot: a commit may name several co-authors, and the platform's claim
is an addition to whatever else is true of the commit.

**Reason, carried with the rule:** *"fine to leave what harness provides"* — Denis, 2026-08-16. A
platform commit authored from code carries no harness trailer today, so this rule has nothing to sit
alongside yet; it becomes load-bearing the moment anything else composes part of the message, and a
rule adopted after the first loss is adopted too late.

#### Scenario: An existing co-author survives

- **WHEN** a message already carries `Co-Authored-By: Claude <model>` and the platform commits it
- **THEN** the resulting commit carries both that trailer and the platform's
- **AND** the original trailer is unchanged

#### Scenario: The message body is untouched

- **WHEN** the platform applies its trailers to a message with a subject and a body
- **THEN** the subject and body are byte-identical to what the caller supplied
- **AND** the trailers appear as trailers, not as body text

### Requirement: The trailers are written by the platform, never by the agent

The trailers SHALL be applied by the deterministic commit path. No agent SHALL be asked, instructed,
or permitted to compose them, and no skill, prompt, or frame SHALL mention them.

**Reason, carried with the rule:** a trailer an agent writes is a self-report, and this design
refuses self-reports as evidence — that refusal is the entire reason the `done` gate exists. A
provenance marker is the last place to make an exception, because it is the field a reader trusts
when every other field is in doubt. It is also the failure mode instruction-dilution predicts: a
prompt carrying one more invariant carries all of them slightly worse.

#### Scenario: An agent that says nothing about attribution still produces marked commits

- **WHEN** a run completes and no instruction given to the agent mentions attribution
- **THEN** every commit the platform produced for that run carries both trailers

#### Scenario: The marker cannot be omitted by the agent

- **WHEN** an agent's output attempts to suppress, alter, or supply the trailers
- **THEN** the commit still carries the trailers the platform applied
- **AND** the agent's version has no effect on them

### Requirement: Trailer composition depends on git, and the dependency is stated

Composing the trailers SHALL use git's own trailer parser rather than assembling the message by
string manipulation. The platform therefore depends on a `git` providing
`interpret-trailers --trailer <key>=<value>`, present since git 2.4. Verified against git 2.53.0 on
the operator's machine, 2026-08-16.

Where that dependency is unmet or the composition fails for any reason, the commit SHALL NOT
proceed, and the platform SHALL NOT fall back to assembling the message itself.

**Reason, carried with the rule:** hand-assembly reimplements rules git already encodes — whether a
trailer block exists, whether a blank line is required, whether the body's last paragraph already
parses as trailers. Each is a way to produce a message that reads correctly to a human and parses
wrong to a tool, which is the worst failure available when machine-readability is the entire point of
the marker. Failing closed is correct here for the same reason: the failure mode of an unmarked
commit is a permanent false negative in a measurement instrument, and D002 forbids correcting it
afterwards.

#### Scenario: A commit is refused rather than written unmarked

- **WHEN** trailer composition fails
- **THEN** no commit is created
- **AND** the failure is reported as an error naming the composition step

#### Scenario: An existing trailer block is extended, not duplicated

- **WHEN** a message already ends in a trailer block
- **THEN** the platform's trailers join that block
- **AND** no second trailer block and no stray blank line is introduced

### Requirement: No existing commit is amended

Applying this capability SHALL NOT amend, rebase, annotate, or otherwise rewrite any commit that
already exists, in this repository or any other. The inconsistency between marked and unmarked
history is resolved forward only.

**Reason, carried with the rule:** D002 — nothing is ever deleted. Rewriting history to make an old
commit look platform-produced would fabricate exactly the evidence D014 is scored on.

#### Scenario: History is unchanged

- **WHEN** the platform begins producing marked commits
- **THEN** no commit that predates the change has a different hash, message, or trailer set

### Requirement: The workspace's platform-produced commit is the gate-certified boundary commit, amended in place

When a turn reaches `may_write_done` and the gate passes, the platform SHALL apply its trailers
(`Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` and `Yosefactory-Run: <run_id>`) to the
commit at the workspace's `HEAD` by amending it, using the same trailer-composition path the queue's
commits use. The platform SHALL NOT create a new commit for this purpose and SHALL NOT amend or
rewrite any commit other than the one at `HEAD` at the moment the gate passed.

**Reason, carried with the rule:** `tree_clean` already requires the workspace be free of
uncommitted changes before `may_write_done` can pass, so by the time delivery could run there is
nothing left to commit — only the commit already there to mark. `HEAD` at that instant is the one
commit the gate has actual, checked evidence about; every earlier commit the agent made during the
same turn is a checkpoint, untouched, exactly as `orchestration.md`'s ruling requires.

#### Scenario: The boundary commit carries both trailers after delivery

- **WHEN** a turn's agent proposes `done`, the gate passes, and the workspace's `HEAD` at that moment
  is a commit the agent made during the turn
- **THEN** that commit, after delivery, carries `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>`
  and `Yosefactory-Run: <run_id>`
- **AND** its SHA changes (the amend produces a new commit object), but the subject, body, and any
  trailer it already carried are unchanged

#### Scenario: Earlier checkpoints in the same turn are untouched

- **WHEN** the agent made more than one commit in the workspace during a single turn before proposing
  `done`
- **THEN** only the commit at `HEAD` when the gate passed is amended
- **AND** every earlier commit from the same turn keeps its original SHA, message, and trailers

### Requirement: A workspace commit is never invented

When a turn reaches the point delivery would run, and the workspace's `HEAD` has not moved since
before the executor ran, the platform SHALL NOT create or amend any commit. The turn's record SHALL
show no workspace commit for that run.

**Reason, carried with the rule:** a turn can pass the gate having made no workspace change — an
investigation that concludes `done` with nothing to commit. Manufacturing a commit to carry the
trailers would assert a workspace effect that did not happen, which is exactly the kind of
self-report this design's verification gate exists to refuse.

#### Scenario: No commit is created when nothing changed

- **WHEN** a turn's agent proposes `done` and the gate passes, and the workspace's `HEAD` is the same
  commit it was before the executor ran
- **THEN** no commit is created or amended in the workspace
- **AND** the turn's record carries no workspace commit for that run

### Requirement: A reader holding only a run finds its workspace commit

The turn record SHALL carry the delivered workspace commit's SHA, so that a reader holding the run
alone can reach the commit without searching the workspace's history, completing the other half of
the join `Yosefactory-Run` already provides in reverse.

#### Scenario: The record names the commit it produced

- **WHEN** a turn delivers a workspace commit
- **THEN** the turn's record carries that commit's SHA
- **AND** the commit itself, read independently, carries a `Yosefactory-Run` trailer equal to that
  run's id

#### Scenario: The join resolves in both directions

- **WHEN** a reader holds only the workspace commit
- **THEN** its `Yosefactory-Run` trailer names a run whose record exists in the ledger
- **AND** when a reader holds only that run's record
- **THEN** its recorded workspace commit SHA is present in the workspace's git history

### Requirement: The amend does not re-ask the workspace's own hooks a second question

Amending the boundary commit SHALL NOT re-run the workspace's own commit hooks. The diff the amended
commit represents already passed those hooks when the agent's own commit produced it; the amend
changes only the message.

**Reason, carried with the rule:** re-running hooks on an unchanged tree asks the same question the
workspace's gate already answered, at the platform's expense, and introduces a new and unrelated
failure surface — a hook validating message syntax against a convention that does not expect this
platform's trailer names could reject a commit whose diff is fine, for a reason unconnected to the
work the gate already verified.

#### Scenario: A workspace with hooks still receives its delivered commit

- **WHEN** the workspace has its own pre-commit or commit-msg hooks configured
- **THEN** delivery still amends the boundary commit with both trailers
- **AND** the workspace's hooks are not invoked a second time by the amend

