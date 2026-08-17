# Design — add-board-projection-and-inbox

Motivation: see [proposal.md](proposal.md). Requirements: see
`specs/board-projection/inbox/spec.md`.

## Context

architecture.md §7 settled the shape after two adversarial reviews: the board is a projection
(read-only mirror of git) plus a command inbox (append-only, ordered, with a consumer offset).
Nothing about the board is authoritative. This design implements that shape, not a redesign of it.

## Verified before building on it (S194 discipline)

The dispatch and the director both flagged the same risk: `priority_set`, `cancelled`, and
`answered` already exist in `protocol/backlog.py` and `protocol/question.py`, but S195 found eleven
declared-and-unreachable mechanisms in this repo, two of them exactly this shape — a typed event
with no consumer. Checked by `grep`, not assumed:

| Event | Producer today | Consumer today | Live? |
|---|---|---|---|
| `answered` | tests only, directly via `turn.append()` | `runtime.turn.apply_answers()` — called **unconditionally on every `take_turn`** (`turn.py:511`) | **Yes, fully wired.** `ingest()` needs to do nothing but append; `apply_answers()` already resolves the block. |
| `priority_set` | tests only | `runtime.turn.pick()` reads `backlog.priority(item)` to rank candidates every turn (`turn.py:258`) | **Yes.** The reader is live and unconditional. The event has no *dedicated* production writer yet, but the generic apply path any single-event agent proposal already goes through (`_dispose`, non-planning branch → `turn.append()`) accepts it — this is not an S195 dead field, it is an unexercised-by-real-traffic live mechanism. |
| `cancelled` | tests only | the fold's own `terminal` predicate (`eventlog.FoldedLog.terminal`) — a cancelled item stops being `eligible()`/counted by `should_plan()` | **Yes**, same shape as `priority_set`. |

Conclusion: building `ingest()` on top of these three is filling a gap (`apply_answers()`'s own
docstring names it), not papering over a dead mechanism. `ingest()` calls `runtime.turn.append()`
directly — the same primitive `apply_answers()` itself uses — never `_dispose()`, so it needs no
executor and no agent turn to apply a command.

## Goals / Non-Goals

**Goals:**
- A `BoardAdapter` Protocol matching architecture.md §7's exact four verbs plus the inbox read:
  `list_events`, `open`, `project`, `comment`, `close`.
- `project_all()`: read every backlog item from git, ensure the board reflects it. Provably
  re-derivable from git alone — no cache is load-bearing.
- `ingest()`: read unconsumed board events, apply each as an ordinary backlog/question event,
  record what was consumed. Idempotent by `event_id`.
- Every rejected command visible **on the board**, not only in a ledger row — architecture.md §7:
  "the loop may reject a command, and must say so... never silently ignore one."

**Non-goals:** see proposal.md. Restated here because it bears on a decision below: no loop-to-loop
messaging, so the `GITHUB_TOKEN`-suppression / echo hazard (§7's "hazard the board actually
carries") does not apply to this change — `ingest()` never posts as a reply that could be read as a
message *to* another loop, only as a reply *to Denis's own comment*.

## Decisions

### D1 — `gh` CLI via subprocess, not a Python GitHub client library

**Chosen:** the adapter shells out to `gh api`/`gh issue`, matching `runtime/turn.py`'s own
`_git()` pattern (subprocess, explicit argv, captured output, non-zero exit raises).

**Over:** `PyGithub` or a hand-rolled `httpx` client against the REST API directly.

**Why:** no new dependency, and `gh` already carries auth (locally, the operator's own OAuth
session; in a container, the PAT named in D3 below via `GH_TOKEN` env, which `gh` reads natively).
The codebase's own convention — shell out, don't wrap — extends cleanly; `commit()`/`_git()` in
`turn.py` already established it for git itself.

### D2 — Ref resolution has no authoritative cache; every `open()` call re-derives

**Chosen:** `open(item)` searches the repo's issues for one whose body carries the marker
`<!-- yosefactory:item=<item_id> -->`. If found, returns its ref (issue number as a string). If
not, creates one, embeds the marker, returns the new ref.

**Over:** a persisted `item_id → issue_number` mapping file, read first and only falling back to
search on a miss.

**Why:** this is the acid test itself, not an optimization deferred past it. A mapping file that
is *sometimes* consulted and *sometimes* rebuilt is two sources of truth with a race between them —
exactly the two-master-by-field shape §7 rejects for the board as a whole, reproduced one level
down inside the adapter. Search-by-marker means deleting every issue and re-running `project_all()`
is not a special "recovery" code path; it is the same code path as every other run, just starting
from an empty result set. The cost (`gh issue list` + scan, once per `open()` call) is O(open
issues on the board), not O(history) — architecture.md §10's bounded-index debt is about backlog
items, not this.

### D3 — Command syntax: a leading slash-token in an issue comment, one command per comment

**Chosen:**
```
/priority 3
/answer yes
/cancel wrong item, superseded by itm-...
```
Posted as a plain GitHub issue comment, on the issue `project_all()` already created for that item
(or, for an `answer`, on the issue whichever item is `blocked` on the named question — the adapter
resolves this by reading the same marker convention). A comment that does not start with `/` is
ignored by `list_events()` — Denis narrating is not accidentally a command.

**Why this shape and not a structured form (a GitHub issue form, a label click, a reaction):** it
is what "type something and send it" from a phone actually is — free text in the GitHub mobile
app's own comment box, no custom UI, no webhook receiver this program has nowhere to host. A
malformed or unrecognized command (`/prioritize`, `/priority high`) is a rejection, not a crash —
see D5.

### D4 — Idempotency: an append-only consumed-log, not a single offset pointer

**Chosen:** `ledger/board/consumed.jsonl`, one line per board `event_id` `ingest()` has
successfully or unsuccessfully processed: `{event_id, ts, consumed_at, result: "applied" |
"rejected", detail}`. The consumer offset for the next `list_events(since=...)` call is derived by
folding this file (max `ts` already present), never stored as a second field that could disagree
with the log.

**Over:** a single `{"last_consumed_event_id": "..."}` JSON file, overwritten each run.

**Why:** D002 (append-only) applies to this exactly as it applies to `backlog/items/*.jsonl` — a
rewritten pointer file is one shared mutable object two concurrent `ingest()` runs could race on;
an appended line per event cannot conflict the same way two backlog logs cannot conflict (they
never share a file... but this file *is* shared across all board events for one repo, so the
concurrency argument is weaker here than for per-item logs). Recorded honestly: this file is a
single shared append target, same class as `ledger/spend.jsonl` already is, and inherits that
file's existing concurrency posture (single-writer-at-a-time, via the same `queue_lock` `ingest()`
should be called under when wired into a turn) rather than solving concurrency itself.

**A rejected event is recorded too, and is never retried automatically.** Retrying a malformed
command blind risks applying it differently once the fold's own state has moved; a human correcting
it and re-sending is the deliberate remedy, matching architecture.md §6's own I9 spirit (an
internal retry is not evidence the second attempt is right).

### D5 — A rejection is a reply comment on the same thread

**Chosen:** when `ingest()` cannot apply a command — item/question not found, fold refuses the
transition (`LogError`), payload malformed — it calls `adapter.comment(ref, "rejected: <reason>")`
on the same issue the command arrived on.

**What this looks like to Denis, concretely, on his phone:** he types `/priority 9` on an issue
whose item is already `done` (terminal — `priority_set` is `ANY_NON_TERMINAL` only). Within the
next `ingest()` poll he sees a reply from the bot account: *"rejected: priority_set is illegal from
state 'done'"* — a GitHub push notification, the same channel the command itself went out on. He
never has to separately check a ledger or a log to learn his command did not land.

**Why not silence, and why not an emoji reaction:** §7's rule is explicit — reject and say so,
never silently ignore. A reaction is not text and cannot carry *why*; a reply comment is the
minimum that satisfies "must say so" with an actual reason attached.

**Corrected during the live receipt: no login-based actor guard on `list_events()`.** An earlier
version skipped every comment authored by the adapter's own `gh` identity, reasoning it must be a
reply, not a command — modelled loosely on architecture.md §7's actor guard for the loop-to-loop
hazard. It broke the live test outright: the acid test's own account (`iorlas`) is both the
operator posting `/priority 9` *and* the identity `gh` authenticates as, so every simulated command
was silently swallowed as "our own comment" — indistinguishable, from inside the guard, from a real
rejection reply. The guard was also redundant even where it worked: every comment this adapter
posts (`close()`'s `"closed: ..."`, `comment()`'s `"rejected: ..."`) is free text that never starts
with `/`, so `parse_command` already excludes it regardless of who posted it. Removed; command
detection is the sole discriminator. This matters beyond the test — a single-operator deployment
with no separate bot account (the realistic shape before Denis provisions the PAT named above) is
exactly the account shape that broke, and it is the shape this program runs in today.

## The credential gap named honestly (director's flag)

D021 keeps Claude's usage credits **off** for this program — a subscription token cannot run away
in dollars, so the executor side has a real ceiling with no code required to enforce it. **GitHub
has no equivalent.** A fine-grained PAT scoped to Issues read+write on one repo bounds *what* it can
touch, not *how much* — nothing throttles write volume the way D021 throttles spend. architecture.md
§7 already names the adjacent hazard (`GITHUB_TOKEN` echo, 80 writes/minute) for loop-to-loop
messaging, out of scope here; the general point stands regardless of scope: **scope is the only
GitHub-side guardrail this design has, and it is a weaker guarantee than D021's.** Concretely for
this change: idempotency (D4) and per-command application (never a batch write) keep write volume
at "one comment per human command plus one issue write per item per `project_all()` pass" — bounded
by how often a human types and how many items exist, not by anything the design enforces. Worth
carrying forward if this ever reaches a scheduled/looped caller rather than a manually-run receipt.

## What a rejected command looks like (summary for the report)

A reply comment, from the adapter's own account, on the issue the command was typed on, naming the
event that was attempted and the reason the fold gave. Nothing silent; nothing requiring Denis to
look anywhere but the thread he already has open.
