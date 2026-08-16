## Context

See proposal.md - Why. [[D022]] grants push narrowly: current branch to `origin`, no force, no tags,
no new remotes, no branch creation/deletion, after commits land, never mid-turn. This covers how
that grant is built and enforced in code rather than left to caller discipline.

## Goals / Non-Goals

**Goals:**
- Publish both repositories a turn touches, deterministically gated on the turn's own outcome.
- Make a push rejection distinguishable from a push that never should have been attempted (no
  remote configured, detached HEAD) — both are "did not publish," but only one is a finding.
- Keep `take_turn`'s existing contract — one record per turn, the turn is the writer — untouched.
  Publication is a step after the turn's own transaction, not inside it.

**Non-Goals:**
- Retrying a rejected push. D022 is explicit: report, don't retry blind.
- Reconciling a rejected push (fetch, rebase, merge). Out of scope; a rejection is a finding for a
  human or a later turn, not something this code resolves.
- Cross-machine coordination (`cas_push`, `cross_machine`). Unrelated flag, unrelated mechanism —
  this proposal does not touch it.

## Decisions

### Publish is a step after `_finish`, not inside it

`take_turn` already has a frozen contract: "Every turn writes exactly one turn record, and the turn
writes it" (`turn-cycle`). Folding publish into `_finish` would make a push rejection a candidate for
changing what that one record says, and the record is already correct at that point — the turn
genuinely advanced, whether or not the evidence became visible elsewhere. Keeping publish strictly
after `_finish` returns means a push failure can never retroactively make a true record read false.

**Alternative considered**: publish before the queue's own final commit, so the record could name
whether publication succeeded. Rejected — this reintroduces exactly the ordering hazard `turn-places`
already reasoned through for atomicity: publishing before the record that describes what happened
exists locally would mean a remote could observe work with no record of it at all if the turn died
between the two.

### The outcome gate is code, not caller discipline

Publish takes the record it is publishing on behalf of and checks `record.outcome is
Outcome.ADVANCED` itself, returning a "skipped" result rather than a "failed" one for every other
outcome. **Deliberately narrower than "not failed"**: `blocked` and `nothing-ready` are not failures,
but `blocked`'s workspace state was never run through `verify.may_write_done` (that gate only fires
on a `done` proposal), so nothing here can vouch for the workspace tree being any particular thing —
publishing on the strength of an unverified state is the mistake D022's "must not run when the turn
failed" is guarding against, stated more narrowly than its own words to stay inside what is actually
verified.

**Alternative considered**: gate on "not failed" (i.e., publish for `advanced`, `blocked`, and
`nothing-ready`). Rejected for the reason above — `blocked` carries no verification receipt for the
workspace side, so publishing it would publish on trust rather than on the same evidence `done`
requires.

### Workspace publishes before queue

A published queue record (via `commit-attribution`'s `Yosefactory-Run` trailer, or per `turn-places`
§6.3's option 3, a SHA the record names directly) is a claim that points at a workspace commit. If
the queue published first and the process died before the workspace push, the claim would be public
and the thing it points at would not exist anywhere Denis can reach yet. Publishing the workspace
first means the referent always exists publicly before the reference to it does — the same ordering
discipline `_dispose` already uses for `may_write_done` (verify the workspace before writing the
queue's `done`), carried one step further.

**Alternative considered**: queue first, on the argument that the queue's own record is the more
important artifact to make visible quickly. Rejected — a queue record naming an unpublished commit
is a dangling reference the moment it is read, which is a worse failure mode than a workspace commit
existing publicly with (temporarily) nothing pointing at it. An unreferenced published commit is
still discoverable by anyone who clones the workspace; a reference to nothing is not resolvable at
all until the second push eventually happens.

### A rejection is reported, not swallowed and not raised past a successful turn

Push runs after the turn has already correctly recorded its own outcome. A push failure must be
visible without making a genuinely successful turn look like it failed to its caller. `publish`
returns a report (`PublishResult`, per-repository) rather than raising, and `take_turn` additionally
raises **`stdlib` `warnings.warn`** with a dedicated warning class (`PublicationFailed`) carrying the
detail, so a caller who does nothing still gets a visible, machine-filterable signal (`pytest.warns`,
`-W error`, a log aggregator's warning capture) without the turn's return value changing shape.

**Alternative considered**: add a field to `TurnRecord`. Rejected — the record is committed to the
queue before publish ever runs (Decisions, above), so there is no legal moment to write a publish
outcome into it without either delaying the record's own commit (reintroducing the ordering hazard)
or amending an already-committed, append-only record (`D002` forbids it, and `turn-cycle`'s "every
turn writes exactly one turn record" would be violated by a second write for the same run).

**Alternative considered**: log via the `logging` module. Rejected only for consistency — nothing
else in this codebase uses `logging`, and `warnings.warn` is stdlib, requires no configuration to be
visible, and is straightforward to assert against in tests (`pytest.warns`). Revisit if the platform
grows a real logging story.

### Push mechanics

`git push origin HEAD:<branch>` — an explicit refspec naming the current branch on both sides, never
a bare `git push` (which could push more than the current branch under some configurations) and never
`--force`/`--force-with-lease`/`--tags`/`--delete`. Current branch is read with `git rev-parse
--abbrev-ref HEAD`; `HEAD` (detached) is refused rather than pushed under a synthetic name. `origin`'s
existence is checked with `git remote get-url origin` first; its absence is a skip, not a failure —
D022 grants push to an *already-configured* remote, so a repository with none configured is simply
out of scope for this capability, not misconfigured.

Pre-push hooks are not bypassed. D022 grants push, not a hook exemption, and a repository with a
pre-push hook (this one included, since `places.queue` may itself be `yosefactory` in the collapsed
case) is trusted to run the same hook a human push would.

## Risks / Trade-offs

- **A workspace push can succeed while the queue push fails**, leaving a published commit with no
  published record pointing at it yet. Accepted per the ordering argument above — this is the
  smaller failure mode of the two orderings, not a solved one. The queue push can be retried later
  (by a human, or a future turn) without re-doing any work, since the workspace side is already done.
- **`warnings.warn` is easy to miss** if nothing captures Python warnings. Accepted for now — it is
  strictly more visible than the status quo (nothing at all), and the alternative (a new persisted
  field) has the correctness problems above. Revisit if D014's operator finds this insufficient.
- **Both locks stay held during both pushes.** Publication runs inside the same `_workspace_lock` (and
  outer `queue_lock`) span that already covers execution and commits, rather than releasing either
  before pushing. A slow or hanging push blocks another turn from starting against the same queue or
  workspace for its duration. Accepted — this program has no queueing or daemon, turns are expected to
  be infrequent, and holding the lock is simpler and safer than the alternative of publishing outside
  it, which would let a second turn start executing against a workspace whose most recent commit is
  not yet published.
