## Context

See `proposal.md` — Why. Three facts about the current code shape the approach.

`runtime/turn.py`'s `commit(repo, paths, message)` is the only place the platform runs `git commit`.
All three commit sites inside `take_turn` route through it: the run-marker declaration, the claim,
and the disposition. It runs against whatever repository `take_turn` is handed, which is what makes
it the right place — D014 counts commits to a2web, and a2web is reached by pointing `take_turn` at
it, not by any a2web-specific code.

`commit()` does not currently receive the run id. `take_turn` holds it (`run_id`, from
`new_run_id`), and `_finish`/`_dispose` carry it as a parameter already. Threading it one level down
is the whole mechanical cost of this change.

The turn-record stream is keyed by run id: `ledger/runs/<stamp>-<run_id>.json`. A commit carrying
the run id therefore names a file, not merely a concept.

## Goals / Non-Goals

**Goals**

- A reader holding only a commit can tell whether the platform produced it, and reach the run record
  that accounts for it, without searching.
- The marker is unforgeable by the agent, in the same sense the `done` gate is: it is applied by
  code the agent does not run.
- The format is frozen on first write, because every commit is compared against every other.

**Non-Goals** (design-level, beyond the proposal's)

- No git configuration, commit template, or hook. The trailer is a property of this platform's
  commit path, not of the operator's machine — a machine-level mechanism would mark hand-driven
  commits too, which is the exact confusion being removed.
- No new module. This is one function's signature and one string operation.

## Decisions

### Two trailers, not one

`Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` carries the claim.
`Yosefactory-Run: <run_id>` carries the route to the receipt.

A bare name answers *did a program make this*, and D014's count needs only that. The run id is what
makes the **other half** of D014 executable: *"on breach, root-cause the platform"* from a name alone
means reading the diff and guessing, when the run record already holds outcome, `enforced_by`,
`dirty`, and `isolated`.

**Alternative rejected — fold the id into the co-author identity** (`yosefactory <run-…@…>`):

> git keys the identity, so every run would register as a different co-author and `git shortlog`
> would report N platform authors instead of N platform commits. **The two trailers answer two
> questions and must not share a field.**

This is the same separation that kept `failure_kind` out of `outcome` — the third time this shape
has been ruled on in this codebase, which is enough repetitions to treat it as the local rule rather
than a case-by-case call.

**Alternative rejected — a bespoke single trailer** (`X-Produced-By: yosefactory run=…`): needs a
bespoke reader. `Co-Authored-By` is parsed today by GitHub, `git shortlog`, and
`git log --format=%(trailers)`, and it is the form Denis named.

**Alternative rejected — carry the platform's version or commit SHA.** A real root-cause input, but
the run record can hold it and the trailer already reaches the run record. Two copies drift, and
*the commit is the copy that cannot be corrected.*

### Applied in `turn.commit()`, never in a prompt

Single choke point, deterministic, repository-agnostic. The agent never composes the trailer, never
sees it, and cannot omit it.

**Alternative rejected — instruct the agent in `workflows/turn-skill.md`.** A trailer the agent
writes is a self-report, and the `done` gate exists precisely because this design refuses
self-reports as evidence. A provenance marker is the last place to make that exception: it is the
field a reader trusts when every other field is in doubt. Secondary but real — the skill is 92 words
by construction, and every invariant added to a prompt degrades the ones already in it.

### Append via `git interpret-trailers`, not string concatenation

git ships the parser. Concatenating `\n\nCo-Authored-By: …` onto a message reimplements rules the
tool already encodes: whether a trailer block exists, whether a blank line is needed, whether the
message ends in a newline, and what happens when the body's last paragraph already looks like
trailers. Each of those is a way to produce a message that reads correctly to a human and parses
wrong to a tool — the worst failure available here, since the whole point is machine-readability.

`git interpret-trailers --trailer <k>=<v>` reads the message on stdin and writes the amended message
on stdout. It preserves existing trailers, which is the append-never-replace requirement satisfied
by the tool rather than by our care.

**Alternative rejected — `git commit --trailer`.** Available in git ≥ 2.32 and simpler, but it is a
commit-time flag, so the composed message is not inspectable before the commit runs and cannot be
unit-tested without making a commit. Composition and commission stay separable.

**Failure posture:** if `interpret-trailers` fails, the commit does not proceed. An unmarked commit
is worse than no commit, because it enters the record as evidence of hand-driven work and cannot be
corrected afterwards (D002). This is a `TurnError` on the same path as a refused commit.

## Risks / Trade-offs

**The marker only covers commits the platform's own path makes** → The agent can run `git commit`
itself inside a run; those commits carry the harness trailer and not ours, and count as hand-driven.
Out of scope here and dispatched separately: a turn comparing `HEAD` before and after the executor
and refusing what it did not author. Recorded so the gap is not mistaken for coverage.

**The receipt is cross-repository** → A commit in a2web carries a run id whose record lives in
yosefactory's `ledger/runs/`. The trailer names a key, not a path, so resolving it requires knowing
where the ledger is. Accepted: this is what `Co-Authored-By` already does — it names a person you
must look up elsewhere. Encoding a path would bake the operator's directory layout into a public
repository's permanent history, which the turn-record spec already forbids for records.

**Commit → item is a weaker hop than commit → run** → The run record names the item only inside its
free-text `note`. So the trail is typed for one hop and untyped for the second. Not fixed here; it
is a turn-record field change and belongs with that spec.

**A frozen identity is frozen** → Choosing `yosefactory@yoselabs.dev` commits to it permanently; a
later rename splits the author. Accepted deliberately, and the alternative — a mutable identity — is
strictly worse, since it fails silently and only becomes visible when someone tries to count.

**Nothing has ever exercised this path** → `ledger/runs/` does not exist and `take_turn` has never
run against any repository, so the first marked commit will also be the first `take_turn` commit.
Tests carry the whole burden of the receipt until then, and they should be written knowing that.

## Open Questions

**What "produced through the platform" means is unsettled, and it is Denis's to settle.** D014's
clock started with `983c810`, whose hand-written ledger row records a session following
`workflows/workflow-a-spec-build-ship.yaml` by hand — no engine; `src/yosefactory/workflows/` is an
empty stub. So three readings are live: a session following a workflow definition; a `take_turn` run;
or anything yosefactory-attributed, which the trailer would define circularly.

**This does not block the change, and the reason is the point:** the trailer is what makes the
question answerable at all, under every reading and for every future run. What it cannot do is
answer it retroactively.

**But it does bound what the trailer covers, and that should not be discovered later.** This
mechanism marks commits made by `turn.commit()`. A session following a workflow definition by hand
commits with its own git and is *not* marked. So under the second reading the trailer is complete;
under the first it covers only part of what qualifies, and a hand-followed workflow run would still
be scored by reading the ledger row. Whether that gap needs closing depends entirely on the ruling,
which is why it is a question here and not a requirement.
