# ADR-0009 — `CLAUDE.md`'s Stack section points at ADR-0006 instead of restating a model/effort value

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a future ADR repins the executor's model or effort and `CLAUDE.md`'s Stack
line is found to name a value again instead of pointing at the current decision — at that point the
pointer discipline below failed and is worth re-examining, not just re-fixing the value.

## Context

`CLAUDE.md`'s Stack section (written 2026-08-12, `git blame` confirms) read: *"Model:
`claude-opus-5`, adaptive thinking, effort `high` default, `xhigh` for long agentic runs."* It sits
immediately after the sentence naming `claude-agent-sdk` as this platform's harness, and is
unqualified — no stated subject other than "the model" the harness runs.

`decisions/0006-executor-pinned-to-sonnet-5-medium.md` (2026-08-20, superseding nothing, itself
recording Denis's ruling) pins `executor/claude.py`'s `PINNED_MODEL`/`PINNED_EFFORT` to
`claude-sonnet-5`/`medium` for exactly that harness, and states the invocation always sends both
explicitly, never left to the binary's default.

**Verdict, checked rather than assumed: genuine contradiction, not ambiguity.** Both sentences name
the same subject — the model `claude-agent-sdk` invokes as this platform's own harness/executor,
not the model a human- or director-driven build session happens to run as (that is set by whoever
opens the session and has no code path through this repo's `CLAUDE.md` at all; the fleet's own
model constraint for build sessions lives in K's `orchestration.md`, a different governance
surface entirely). `CLAUDE.md`'s line simply predates ADR-0006 by eight days and was never updated
when the ADR superseded whatever informal default it had been describing. Nothing in the codebase
reads `CLAUDE.md`'s Stack section — `executor/claude.py`'s constants are the only thing that
governs runtime behavior — so the contradiction was a documentation-only drift with no live-code
consequence, but a real one: a worker reading `CLAUDE.md` alone would form a false belief about
what this platform runs.

## Decision

`CLAUDE.md`'s Stack section no longer names a model or effort value. It points at
`decisions/0006-executor-pinned-to-sonnet-5-medium.md` and states plainly that ADR's scope
(the platform's own harness invocations) versus what it does not cover (which model a build
session itself runs as). The standing ruling (ADR-0006, `claude-sonnet-5`/`medium`) wins over the
stale line outright — there was no case for the reverse.

The general rule this leaves behind: **a value that can be repinned belongs in exactly one place
(the ADR that pins it), and every other document that used to state it instead cites it.**
`CLAUDE.md`'s own communication-style section already argues this for prose ("pointer, never
restatement"); this applies the same discipline to a fact that drifts.

## Consequences

- `CLAUDE.md` cannot go stale on this again — repinning the executor updates `decisions/000N` and
  `CLAUDE.md`'s pointer keeps working without a second edit.
- A reader of `CLAUDE.md` alone, with no access to `decisions/`, no longer sees a concrete value —
  they see that one exists and where to find it. Judged acceptable: `decisions/` is checked into
  the same repo, not external.
- Nothing in `src/` changed; this is a documentation correction only.

## References

- `CLAUDE.md` — Stack section.
- `decisions/0006-executor-pinned-to-sonnet-5-medium.md`.
- `src/yosefactory/executor/claude.py` — `PINNED_MODEL`, `PINNED_EFFORT` (unchanged, ADR-0006 still
  governs them).
- `openspec/changes/write-down-the-operating-model/` — the change this ADR was written for.
