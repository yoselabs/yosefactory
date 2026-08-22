## The mechanism: amend the boundary commit, not a new one

`may_write_done` (`runtime/verify.py`) requires `tree_clean` before a `done` proposal can even reach
the vocabulary check. So by the time this change's delivery step could run, the workspace has no
uncommitted diff to commit — the agent's own `git commit` already put it there, or the gate would
have already failed the turn. **"The platform commits the workspace instead of the agent" cannot
mean a second commit; there is nothing left to commit.** It has to mean: mark the commit that is
already there.

```
  BEFORE this change                    AFTER this change
  agent commits (unmarked) ──┐          agent commits (unmarked) ──┐
                              │                                     │
  gate: tree_clean, tests ───┤          gate: tree_clean, tests ───┤
                              │                                     │
  done proposed, appended ───┘          gate passes ──▶ AMEND HEAD  │
                                         (append trailers only) ────┤
                                         done proposed, appended ───┘
```

`HEAD` at the moment the gate passes is, by definition, the commit the gate just verified —
`tree_clean` and `tests_pass` were run against exactly that tree. Amending it is not choosing an
arbitrary commit to mark; it is marking the one commit this run has actual, gate-backed evidence
about. Every earlier checkpoint the agent made during the same turn is untouched — the dispatch's
"do not squash or rewrite the checkpoint series" is satisfied because the mechanism only ever
touches the single commit at the boundary, never the ones before it.

**Read once, under the lock, before the executor runs.** `runtime/turn.py` already acquires
`_workspace_lock(places)` around the executor call on the item path; this change adds one read of
`git rev-parse HEAD` inside that block, before the executor starts, and threads the value down to
`_dispose`. Two commits from a foreign trailer scheme never collide with it, because the SHA is a
plain observation, not a claim anything else depends on.

## Why amend and not `prepare-commit-msg` (Option B, from the archived design)

`teach-the-done-event-schema`'s design.md left this open between Option A (platform commits) and
Option B (a hook installed for the run's duration). Option B needs a hook mounted into a workspace
the platform does not own, torn down per-run, invisible outside a live turn, and — because the agent
already commits inside its own sandboxed turn before the platform ever sees the tree — still has to
answer "which of the agent's several commits get the trailer" the same way this change does: the
last one. Option B buys nothing this change does not already get, and costs a mount/teardown
lifecycle in a repository the platform is a guest in. Amend, once, after the gate, is smaller.

## The dirty-workspace boundary case

The dispatch asks what a delivery commit means when the workspace is dirty at the boundary. **The
answer is that this case cannot reach delivery at all**, and that is not a new gap this change opens
— `tree_clean` has gated `done` since the gate existed. A dirty tree fails the gate, the turn ends
`failed`, no delivery step runs, and the tree is left exactly as the agent left it: unmarked,
uncommitted, and untouched by the platform, same as today. Delivery is defined only on the one path
where the platform already has verified evidence to attach a claim to.

The other edge, worth naming because it is new: **`HEAD` unmoved.** A turn can pass the gate having
made zero workspace commits — an investigation-only turn that concludes `done` with no code change,
for instance. `head_before == head_after` there, and delivery is a no-op: `workspace_commit` records
`""`, nothing is amended, nothing is invented. Manufacturing a commit to have something to mark would
misrepresent what happened; the record instead says plainly that this run produced none.

## Hooks: skipped on the amend, and why that is not a gate bypass

`git commit --amend` re-runs `pre-commit`/`commit-msg` hooks by default. This change passes
`--no-verify` for the amend specifically.

**The tree does not change.** The amend touches only the commit object's message; the diff it
represents already passed whatever hooks the workspace has, because the agent's own `git commit`
ran them to produce the commit that now sits at `HEAD`. Running them again asks the same question
of the same tree a second time, at the platform's expense (a2web's suite, its lint, whatever else is
wired into its hooks) — this program has already paid once for that answer via `verify.may_write_done`
running the repository's own `make check`. It is also a new failure surface entirely orthogonal to
correctness: a commit-message linter checking exact trailer syntax against a convention it does not
expect (`Yosefactory-Run:` is not a trailer any repository's hooks were written to allow) could
reject a message whose diff is fine, for a reason that has nothing to do with the work.

**This is not the gate being bypassed.** `verify.may_write_done` — tests, tree cleanliness, the
verdict — has already run and passed before delivery starts; `--no-verify` only means the *second*,
redundant run of the workspace's own hooks on an unchanged tree is skipped. Article V's "never skip
hooks" is about this repository's own gate on this repository's own work; a foreign workspace's
hooks, re-asked a question they already answered, are a different case and named as one here rather
than silently inherited.

## Repo conventions: handled by construction, not by a lookup

D023's logic — the workspace declares its environment — extends the same way to its commit
convention: it is not the factory's business to know that a2web wants
`feat(ask): … (a2web-qgo)` or that some other repository wants Conventional Commits or nothing at
all. This change never needs to know, because it never writes a subject or a body — only appends
trailers to whatever message the agent (following that repository's own conventions, as it already
does today) already wrote. No repo-detection table, no hardcoded a2web format, nothing to maintain
as new repositories are added. If Option-A-extended ever composes messages from the `done` event
(see below), *that* change would need to solve this for real; this one does not, because it does not
touch the part of the message that carries convention.

## The prize: composing the commit message from the `done` event

**Scoped out of this change**, and the reason is the same ordering constraint that shaped the
mechanism above, not a lack of appetite.

The `done` event's `effects`/`verified_by` fields are only known once the agent proposes `done` —
which is after `may_write_done` has already required a clean tree, which is after the agent's own
commit already exists with the agent's own message. Composing the *commit* message from the *done
event* would mean one of:

- **(a) Delay the workspace commit until the event is known**, holding the tree dirty until after
  the gate — but the gate itself requires the tree already be clean to pass, so this inverts a
  constraint this change deliberately did not touch, and is exactly the second, larger design the
  dispatch anticipated ("outside a two-line-reword change's scope" was `teach-the-done-event-schema`'s
  own words for a smaller instance of this same shape).
- **(b) Rewrite the message a second time**, after the event is known — a second amend, replacing
  the agent's own subject/body with derived text. This is a materially different capability: it
  decides what a commit message *is* for a platform-produced commit (derived, not agent-authored),
  needs its own requirement in `commit-attribution` (today's spec explicitly protects the message
  body — "SHALL NOT overwrite the message body" — which this change relies on and a message-composing
  change would have to amend, not just extend), and reopens the repo-convention question this change
  closed by construction: derived text has to *match* a target repository's own convention rather
  than inheriting it for free.

Both are real designs, not small deltas on this one. This change ships the join (a) — attribution
that always joins to a real ledger row — without also deciding (b) — what the platform is allowed to
say on the agent's behalf. Shipping both in one change would make the receipt for one hide inside the
receipt for the other; keeping them separate means a future change to (b) can be reviewed and
reverted without touching the join this change is worth on its own.

## What is not in `TurnRecord`'s existing spec surface

`model`/`effort` were added to `TurnRecord` by an earlier change with no dedicated schema
requirement in `openspec/specs/` — field additions to the record have not been independently
spec-governed. `workspace_commit` follows the same convention: no new spec file, no schema
requirement; the one new thing this field exists to make true — a reader holding a run can find its
commit — is asserted directly in `commit-attribution`'s new requirement, since that is the capability
the field serves.
