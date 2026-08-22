## Why

Denis, 2026-08-22: **"agent checkpoints, platform delivers."** A commit has been doing two jobs —
the agent's save button during work, and the unit of record at the boundary — and the second is the
platform's business, not the agent's.

**Confirmed against disk before designing, per Article XII.** `runtime/turn.py`'s `commit()` is the
only function that composes the platform's trailers (`git interpret-trailers`), and its three call
sites (`~510`, `~570`, `~797`) all pass `places.queue`. `places.workspace` is never an argument to
`commit()` anywhere. So `commit-attribution`'s spec — 26/26 clean under `--specs --strict` — is
satisfied by a function that is never asked to do the thing the spec exists for; the platform's
`Co-Authored-By: yosefactory` and `Yosefactory-Run:` have never appeared on a workspace commit,
including `9e183e4`, the commit D014's 2026-08-17 ruling had to score from the queue's ledger row
instead of from a2web's own git log because of exactly this gap. The RCA in the dispatch is correct.

One correction to it, found while designing rather than a refutation: the gate the RCA calls "the
last inch" also requires (`verify.tree_clean`) that the workspace already be clean **before**
`may_write_done` can pass — so "the agent must commit its own work" is not merely a habit, it is
load-bearing today. A design that has the platform commit *instead of* the agent, at that same
point, has nothing left to commit: the tree is already clean by construction. That is why this
change amends rather than replaces the agent's own act (see `design.md`).

## What Changes

- **`runtime/turn.py`** gains a workspace-delivery step, run only on the path that already reaches
  `may_write_done` and only after `gate.passed`: the commit sitting at the workspace's `HEAD` —
  whichever commit the gate just verified — is amended, in place, to carry
  `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` and `Yosefactory-Run: <run_id>`, via the
  same `git interpret-trailers` path `commit()` already uses for the queue. Subject, body, and every
  existing trailer are preserved byte-for-byte; only trailers are appended.
- **No agent checkpoint is touched.** The amend targets `HEAD` alone — the one commit the gate
  certified — never the commits before it. `HEAD` is read once, under the workspace lock, before the
  executor runs; if it is unchanged when delivery would happen, the turn produced no workspace
  commit and none is invented.
- **`protocol/turn.py`**: `TurnRecord` gains `workspace_commit: str = ""` — the delivered SHA, or ""
  when the turn had none to deliver. This is the reverse half of the join: the trailer lets a reader
  holding a commit find its run; this field lets a reader holding a run find its commit.
- **`openspec/specs/commit-attribution/spec.md`**: one ADDED requirement stating what "the platform
  produces a commit" means for the workspace specifically — amend, not replace; `HEAD` only; nothing
  invented when the agent made no commit; hooks skipped on the amend (argued in `design.md`).
- **Two receipts**: unit/integration coverage at $0, and one live turn against a2web (standing
  allowance $5) producing a real workspace commit whose `Yosefactory-Run` trailer resolves to a row
  in this repo's ledger — the join, quoted both directions, per the dispatch's Article XVI answer.

## Non-goals, stated rather than silently dropped

- **Composing the commit message from the `done` event's `effects`/`verified_by`.** The dispatch
  calls this "the prize, if reachable" and asks for a judgment, not a default. It is out of scope
  here — see `design.md`'s "The prize" section for why, and it is not a small follow-on: it changes
  what a commit message *is* (derived text, not agent prose) and needs its own spec and its own
  ordering design against the same `tree_clean` constraint that shaped this change.
- **Repo commit-convention detection or enforcement (e.g. a2web's `feat(scope): … (bead-id)`).**
  Not needed as a separate mechanism: because delivery only appends trailers and never rewrites
  subject or body, whatever convention the agent already followed for that repository survives
  untouched. Handled by construction, not by a lookup table — see `design.md`.
- **Squashing or rewriting the agent's checkpoint series.** Explicitly ruled out by the dispatch;
  this change amends exactly one commit (`HEAD` at gate time) and rewrites none of the others.
