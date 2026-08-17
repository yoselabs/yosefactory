## Decision 1 — raw transcripts: gitignored and local-only, not redacted, not moved

**The transcript is genuinely valuable, not junk to delete.** This program's whole discipline is
*check the subject, not the instrument* — `run-guardrails/turn-record`'s own spec closes with
exactly that line, and `teach-event-vocabulary`'s receipt cites a literal `Read` call inside a
run's transcript as the proof a coordinator's claim actually held. When a run's behaviour is in
question, the transcript is the subject. So "delete it forever" was never the right frame — the
real question is *where it lives*, not *whether it exists*.

**Three candidates, argued against each other:**

| | Gitignore (chosen) | Redact at write time, then commit | Write to a second, container-mounted path |
|---|---|---|---|
| What publishes | nothing — the file stays untracked | a redacted stream, if the redaction is complete | nothing — same as gitignore, via a different mechanism |
| Failure mode if wrong | none — nothing is ever staged | a missed pattern republishes exactly what this change exists to stop, in a *durable*, committed row | a second path to keep straight; no failure mode beyond gitignore's own |
| What it costs to build | one `.gitignore` line | a redaction function correct over arbitrary tool-call payloads (`Read`/`Bash`/`Edit` args, free text) — open-ended, not a bounded transform | thread a second `runs_dir`-like path through `executor/claude.py`, `runtime/turn.py`, `runtime/supervise.py`, `runtime/stall.py` — all four already take `runs_dir` as a parameter for the *existing* path |
| Existing precedent | `protocol/turn.py::_HOME_ROOTED` already refuses a home path in `TurnRecord` fields — the pattern this change reuses, at a different boundary | none — no redaction path exists anywhere in this codebase today | none — `docker-compose.yml` bind-mounts the whole repo (`./:/app`); there is no existing second mount for run data the way `.dev-workspace` is separate for the queue/workspace |
| Trust required | none beyond "gitignore is honoured", already load-bearing everywhere else in this repo | trust that the redactor itself is correct on content the program's own philosophy says must be checked, not assumed | trust that every write site was updated to use the new path, forever, with no accidental fallback to the old one |

**Chosen: gitignore.** It is the only option whose failure mode is *nothing happens* rather than
*a redaction bug republishes the leak in a committed row*. Committing a "safe" transcript trades an
obvious, structural guarantee (untracked files are never pushed) for a probabilistic one (this
regex caught everything this time) — exactly the shape of claim this repository's own philosophy
distrusts. The transcript for `turn-20260817T051729Z-da1f32fc` alone quotes a home-relative
knowledge-base path and a private repo name inside *prose CLAUDE.md content the agent read back*,
not inside a filesystem call a `/Users/`-style regex would even match — a redactor scoped to
literal path syntax would have missed both, silently, the first time it mattered.

**What is lost:** the raw stream is no longer part of the portable git history. A clone that has
only the git repo — a different machine, a later date, an auditor without the original checkout —
cannot read a transcript for a run that happened before it obtained a copy some other way. This
narrows what `D002` ("nothing is ever deleted... applies to `ledger/`") can mean for this one file:
the raw stream was never actually inside the *frozen protocol* `D002` names — that's `TurnRecord`
(`ledger/runs/<slug>.json`, `.start`, `.wake.json`), which stays exactly as append-only and exactly
as committed as before. The stream only entered git for the first time in the commit this change
undoes; untracking it is confining `D002` to the layer it already names, not narrowing a guarantee
that previously held.

## Decision 2 — the guard is content-pattern-based, not a repo-name blocklist

The three concrete leaks named in this incident are a literal absolute path (the operator's home directory, 53
occurrences), a tilde-shorthand knowledge-base path (`~/Documents/Knowledge`), and a tilde-shorthand
private repo name (`~/Workspaces/...`). `_HOME_ROOTED`-style matching catches the first class and
not the second two, and that gap is deliberate, not missed: enumerating the specific repo or
directory names as a blocklist inside a script this public repo commits would put those names in
the one place this whole change exists to keep them out of. The gitignore (Decision 1) is what
actually stops the tilde-form leaks, structurally, by never committing the file that contains them
— the content-pattern guard is defense in depth for the literal-path class, on every other file.

## Verification

- `git grep "/Users/<operator>" $(git rev-list --all) -- ledger/` — empty, post-rewrite (`tasks.md` §2). <!-- hostpath-allow: placeholder -->
- `git log --all -p -- 'ledger/runs/*.stream.jsonl'` — no hunks, post-rewrite.
- `openspec validate stop-publishing-host-paths --strict` before apply.
- `openspec validate --specs --strict` after archive — 23/23 (22 existing + this change's new
  capability).
- `make check` unchanged, `$0` — confirmed by reading `ledger/spend.jsonl` before and after (6
  lines both times), not by the deselect count alone.
