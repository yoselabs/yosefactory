# ADR-0005 — The platform delivers the workspace commit by amending `HEAD`, never a new commit

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** `may_write_done`'s tree-clean requirement is relaxed so a turn can reach the
gate with uncommitted work — at that point "amend `HEAD`" no longer has a single candidate commit
to target and this decision needs re-examination against whatever replaces the clean-tree
precondition.

## Context

Denis, 2026-08-22: *"agent checkpoints, platform delivers."* A commit had been doing two jobs — the
agent's own save-as-you-go checkpoint, and the platform's unit of record at the turn boundary — and
`runtime/turn.py::commit()` (ADR-0004) had only ever been called with `places.queue`, never
`places.workspace`. `openspec/specs/commit-attribution/spec.md` read 26/26 clean under
`--specs --strict` while satisfied by a function never asked to mark a workspace commit at all —
including `9e183e4`, the a2web commit D014's first scoring attempt had to read from the queue's
ledger row instead of from a2web's own git log, for exactly this reason.

Explored before designing (Article XII): `verify.tree_clean` already requires the workspace clean
**before** `may_write_done` can pass. So "the agent commits its own work" was not merely a habit at
that gate — it was load-bearing. A design that has the platform commit *instead of* the agent, at
that same point, finds nothing left to commit: the tree is already clean by construction.

## Decision

`_deliver_workspace` amends, in place, the commit already sitting at the workspace's `HEAD` — the
one the gate just verified — appending the same two platform trailers ADR-0004 defines, via the
same `git interpret-trailers` path `commit()` uses. Subject, body, and every existing trailer are
preserved byte for byte; only trailers are appended, with `--no-verify` on the amend, because the
tree is unchanged from what already passed the hooks when the agent's own commit ran.

`HEAD` is read once, under the workspace lock, before the executor runs (`head_before`). If `HEAD`
is unchanged when delivery would happen, the turn produced no workspace commit and none is
invented — `_deliver_workspace` returns `""`, recorded honestly rather than fabricated.

No agent checkpoint before the gate-verified `HEAD` is touched. The amend targets `HEAD` alone,
never the commits before it — squashing or rewriting the agent's own checkpoint series was
explicitly out of scope for the dispatch this served.

## Consequences

- A workspace commit produced through the platform now carries the same
  `Co-Authored-By: yosefactory` / `Yosefactory-Run:` trailers the queue already got — D014's
  measurement unit is readable directly off `a2web`'s own git log, not only reconstructable from
  the queue's ledger row.
- `TurnRecord.workspace_commit: str = ""` is the reverse half of the join: the trailer lets a
  reader holding a commit find its run; this field lets a reader holding a run find its commit.
- Whatever commit-message convention the target repository already follows survives untouched,
  because delivery never rewrites subject or body — handled by construction, not by a per-repo
  convention lookup table.
- **Rejected alternative:** composing the commit message from the turn's own `effects`/
  `verified_by` fields. Named in the dispatch as "the prize, if reachable" and explicitly deferred
  — it changes what a commit message *is* (derived text, not agent prose) and needs its own
  ordering design against the same `tree_clean` precondition; not a small follow-on to this
  decision.

## References

- `src/yosefactory/runtime/turn.py::_deliver_workspace`.
- `openspec/changes/archive/2026-08-22-the-platform-delivers-the-workspace-commit/proposal.md`.
- `openspec/specs/commit-attribution/spec.md`.
- P160 D014 (success criterion), ADR-0004 (trailer composition).
