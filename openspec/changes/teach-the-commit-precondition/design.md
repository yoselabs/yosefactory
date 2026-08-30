## Context

See `proposal.md` — Why. Two facts fix the shape of the fix rather than leaving it open:

- **ADR-0005** ("agent checkpoints, platform delivers") already decided the agent commits its own
  work with a plain `git commit`, and `_deliver_workspace` only amends `HEAD`'s trailers *after*
  `verify.may_write_done` finds the tree clean. The tree being clean before the gate is load-bearing
  by that ADR's own text ("A design that has the platform commit *instead of* the agent, at that
  same point, finds nothing left to commit"), not an accident this change can quietly correct by
  moving the commit into the platform.
- The repo already fixed one instance of this exact defect shape — *agent behavior was correct, the
  skill was silent* — in `teach-event-vocabulary` (archived): the agent did real work, then invented
  a `done` event name because nothing taught it the real one, and `take_turn` correctly refused it.
  The fix there was not a bigger skill file; it was pointing the agent at
  `openspec/specs/backlog-item-format/spec.md` via `Invocation.vocabulary`, which is unbounded in
  length and already carries `done`'s field requirements.

## Goals / Non-Goals

**Goals:** teach the commit precondition somewhere the agent actually reads it, without reopening
ADR-0005 or inventing new enforcement (the enforcement — `verify.tree_clean` — already exists and
already caught the real failure correctly).

**Non-Goals:** changing `verify.gate`, `_deliver_workspace`, or any `src/yosefactory/` code; widening
`test_the_skill_stays_short`'s budget; a mechanized "the agent actually committed" test (that's
`verify.tree_clean`, not a new thing).

## Decisions

**Two loci, not one.**

1. **`openspec/specs/backlog-item-format/spec.md`** carries the substantive obligation — a full
   scenario, unbounded by the skill's word cap, naming `git add -A` explicitly as the wrong move and
   explaining why (`.factory/` under D033). This is the file `Invocation.render()` already points the
   agent at ("check it before you do") and the file that already states `done`'s other precondition
   (`effects`, `verified_by`), so a reader checking one precondition finds the other beside it.
2. **`workflows/turn-skill.md`** carries a short reinforcement, because it is what a turn reads
   unconditionally, every time, with no extra fetch — unlike the vocabulary pointer, which is phrased
   around field names and evidently did not, by itself, prompt this run to check for a commit
   obligation that did not yet exist anywhere. Fitting inside `test_the_skill_stays_short`'s <120-word
   cap requires trimming existing sentences (verified: "the path given as", "for the fields your
   event requires", "anything under", "that says so rather than an", "instead of one object" are
   compressible without losing meaning — frees roughly 20 words), not raising the cap.

**Folded in mid-apply: the skill's "backlog/" line was itself stale, by the same class of defect.**
`workflows/turn-skill.md` said "Do not edit anything under `backlog/`" — true only under
`Places.local`, where queue and workspace coincide. Under `Places.nested` (D033), the physical path
is `<workspace>/.factory/backlog/`; `git log` on the file shows it was never touched when D033
landed. An agent reading the literal word "backlog/" in a nested-queue workspace would not recognise
`.factory/` as the thing to avoid — the same `git add -A` hazard this change already addresses,
arriving from the naming side rather than the staging-command side. Reworded to
"the caller's own bookkeeping" — layout-agnostic, true under `local`, `nested`, and any future
`Places` variant, rather than naming a path that has already drifted once and would drift again the
next time a `Places` variant changes where the queue lives.
**Rejected: platform stages/commits the agent's own work.** Would reopen ADR-0005 on no new
evidence — the observed failure is "nobody told the agent," not "the agent cannot be trusted to
commit." ADR-0005's own revisit trigger is specifically "`may_write_done`'s tree-clean requirement is
relaxed," which nothing here proposes.

**Rejected: scope `verify.tree_clean` away from `.factory/`.** Traced the actual turn sequence
(`take_turn`): the claim/`started` commit for `.factory/`'s own items lands *before* the executor is
ever invoked, and the platform's own post-gate writes (`gate_rejected`, the run record, spend row)
land *after* `verify.may_write_done` is checked. So `.factory/` is not the thing that was dirty in
the observed failure, and there is no ordering under which it legitimately could be at gate time —
scoping the gate away from it would hide a real future defect (the agent actually editing platform
bookkeeping) rather than fix anything present.

**Rejected: a pytest that asserts an agent obeys the instruction.** Not buildable — obedience is a
property of an LLM's behavior on a given run, not of the repository at rest. What *is* buildable and
is included: a regression test guarding the instruction's own *presence* in `turn-skill.md`, modeled
directly on the file's own history — the harness's `Co-Authored-By: Claude` line died silently
because it was a habit nobody's test named (`orchestration.md`, "Commit attribution"). Naming the
same class of test here is the cheap insurance against the identical failure recurring for this line.

## Risks / Trade-offs

**[Risk]** The word-budget trim could itself drop meaning from the skill's existing sentences while
freeing room for the new one. **Mitigation:** each trim is a filler-phrase removal (verified against
the original sentence-by-sentence), not a removal of a distinct instruction; the full before/after
diff is reviewed in `tasks.md`'s verify step.

**[Risk]** Teaching the obligation does not prove any future unattended run will actually commit —
prose compliance from an LLM is not guaranteed by writing the words down anywhere. **Not mitigated
here** — named plainly rather than papered over; the enforcement layer that catches a failure to
comply is `verify.tree_clean`, which already exists and is exactly what caught this one.

## What this proves and does not

**Proves:** the instruction exists, in both places an agent would read it, and neither place silently
regresses (word-count test unchanged in spirit, new presence test added).

**Does not prove:** that the next unattended run commits. No unattended run has exercised this
wording yet — that receipt does not exist and this change cannot manufacture it.
