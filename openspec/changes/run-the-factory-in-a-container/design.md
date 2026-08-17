# Design — run-the-factory-in-a-container

Motivation: see [proposal.md](proposal.md) — Why. Requirements: see
`specs/containerized-loop/dev-and-production/spec.md`.

## Context

Everything upstream of this change assumed the loop runs on the same machine, in the same
filesystem, as a person typing the command. `add-scheduled-loop` kept that assumption and only
changed *who* typed the command (a scheduler, not a person) — same host, same checkout. This
change removes the assumption itself: the loop's process, its Python environment, and (per Denis)
potentially its filesystem view of the queue/workspace all move inside a container boundary, while
development still needs to feel like editing a normal checkout.

Three properties shaped every decision below, in the order they were found:

1. **The mount race, found by the launchd detour and explicitly not to be lost.** A bind mount
   that makes source edits live is the same mechanism that lets a running loop and a human editor
   observe/modify the same files concurrently. `take_turn`'s commit path goes through `prek`, which
   stashes the whole tree for the duration of any hook run (S184, orchestration.md Article XI) —
   colliding with that stash was the launchd receipt's actual failure, not a container-specific
   defect, but a bind mount makes the collision the *default* posture of development rather than a
   rare timing accident.
2. **Auth cannot cross the container boundary as it exists today.** The working auth mechanism on
   this Mac is a keychain-backed OAuth session — OS-level state, not a file, not portable, and
   `claude --help`'s own `--bare` flag documents that even Anthropic's own stripped-down mode
   refuses to read it. A Linux container has no macOS Keychain at all; this is not a permissions
   problem to work around, it is a different auth mechanism entirely.
3. **The platform under the code changes.** `claude`'s pinned version (`executor/claude.py`) is a
   real binary with a real platform target; `uv`, git's `safe.directory` trust model, and file
   ownership on a bind-mounted volume all behave differently under Linux-in-a-container than under
   this Darwin host.

## Goals / Non-Goals

**Goals:**
- A `Dockerfile` that builds an image carrying the pinned `claude` binary, `uv`, and the package.
- `docker compose` for development: source bind-mounted, edits live without a rebuild, the
  virtualenv unaffected by the mount.
- The loop's queue/workspace mounted **separately** from the source tree, so the default dev
  posture does not reproduce the mount race by accident.
- Ledger and spend records readable from the host, from outside the container, after a run.
- No credential in the image, in compose, or in the repository tree.
- State plainly what is dev-only and what is production (Money / Platform sections).

**Non-goals:** see proposal.md.

## Decisions

### D1 — The mount race: separate the source mount from the queue/workspace mount, plus a startup guard

**Chosen:** two mounts, two purposes, never the same path:
- `./:/app` (bind mount, dev only) — the yosefactory **source tree**, live-editable, used so the
  package inside the container reflects a code change without an image rebuild.
- a **different** path — a named volume in the default dev compose file, or a separate
  bind-mounted host directory — is what `Places.local` is pointed at as the loop's queue and
  workspace. **The loop is never, by default, pointed at `/app` itself.**

On top of that separation, as defense in depth: `run_loop` now refuses to start if
`places.workspace` has uncommitted changes at the moment it is invoked (`_refuse_if_dirty`,
`LoopError`, checked once at startup — matching where `LoopBound` validation already happens,
before any turn runs). This does not replace the separation above; it exists for the case where
someone deliberately (or by misconfiguring compose) points the loop back at the source mount.

**Over:** (a) doing nothing and documenting "don't do that" — rejected, because the whole point of
Denis's instruction is a compose setup someone actually uses during development, and the default
configuration is what people run, not what the README warns them against; (b) making `take_turn`
itself retry or auto-stash around a dirty tree — rejected, because a retry-around-dirty-state
mechanism is exactly the kind of thing that turns a loud, safe failure (what happened under
launchd — nothing lost, nothing corrupted, just refused) into a quiet one that commits over
something a human had open in an editor. **A refusal that is easy to understand beats a recovery
that is hard to trust.**

**Why this is not new scope creep beyond "container":** the mount race is the container's own
version of Article III (*"the tree is shared and nobody is isolated"*) and Article XI
(`prek` stashes tree-wide) — both already constitutional, both already measured (S184), just never
previously in a position to fire on every `docker compose up` the way a default dev mount would.

#### What "separate mount" looks like operationally
```
  host                          container                          purpose
  ─────────────────────────────────────────────────────────────────────────
  ./ (repo)                 →   /app                    bind, dev  live source
  ./.dev-workspace/ (gitignored) → /data/workspace       bind, dev  loop's queue+workspace
  (named volume, prod)      →   /data/workspace          volume     loop's queue+workspace
```
`./.dev-workspace/` is created by the developer (or a `make` target) as its own small git repo —
exactly the throwaway-pair pattern `add-turn-loop`'s and `add-scheduled-loop`'s own live receipts
already used, now made the *default* rather than something assembled by hand for a receipt.

### D2 — Auth: `CLAUDE_CODE_OAUTH_TOKEN` only, supplied at `docker compose` run time, never baked in

**Decided by Denis, and it is a constraint, not a preference:** `CLAUDE_CODE_OAUTH_TOKEN` (from
`claude setup-token`), not `ANTHROPIC_API_KEY`. **D021 keeps usage credits off** — the setting that
makes a dollar runaway *impossible* rather than merely bounded by a ceiling a bug could still cross.
The subscription token bills against a fixed plan quota, never a running dollar total;
`ANTHROPIC_API_KEY` would reverse that property, and this loop — the first thing in the repo that
can spend unattended — is precisely what D021 was protecting against. The container reads the
token from the environment (`env_file: .env`; `.env` already gitignored, presence and gitignore
status confirmed via `git check-ignore` / `git ls-files` — **without reading its value**).
`.env.example` is committed with the variable name, an empty value, and a one-line comment: *from
`claude setup-token`, requires an active Claude subscription*. Neither the `Dockerfile` nor
`docker-compose.yml` names a literal value anywhere, and no command run while building or
verifying this change prints, logs, or interpolates it — verification is "set and non-empty
inside the container," never "displays as."

**Over:** (a) baking a token into the image at build time — refused outright, an image is a
distributable artefact and this repo is public; (b) mounting the host's `~/.claude` credential
state into the container — refused, because on macOS that state is keychain-backed and not a
portable file at all, and even where a portable credential file exists, mounting a *host* identity
into a container blurs exactly the boundary this change exists to draw; (c) relying on `claude`'s
interactive login flow inside the container — refused, a container has no browser to complete an
OAuth redirect and no interactive session for an unattended run to pause into (the same class of
gap orchestration.md's "known hole in Article I" already names for unattended runs generally);
(d) `ANTHROPIC_API_KEY` — available, works identically at the wiring level, and rejected on D021
grounds above, not on a technical one.

**Fails loudly, not obscurely, when the token is absent.** `docker-entrypoint.sh` checks
`CLAUDE_CODE_OAUTH_TOKEN` is set and non-empty **before** exec-ing into `yosefactory-loop-scheduled`
and exits immediately, naming the missing variable, if it is not — the check tests only presence
(`[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]`), never the value, so the failure path itself cannot leak it
either. Without this, a missing `.env` would surface three layers down as whatever `claude -p`
itself does on an unauthenticated invocation — a generic executor failure indistinguishable from a
real bug, exactly the discriminator problem this dispatch's second half names for quota exhaustion,
one layer earlier.

**What the ceiling means, and does not mean, under a subscription token (carried from D4/Money):**
`scheduled_main`'s `--spend-ceiling-usd` stays mandatory, but under `CLAUDE_CODE_OAUTH_TOKEN` the
dollar figures `ledger/spend.jsonl` records are not amounts Denis is billed — no invoice follows
them. They remain meaningful as a **rate signal**: `total_cost_usd` is still what the pinned
`claude` binary reports per turn (`Usage.total_cost_usd`, unchanged plumbing), so the ceiling still
bounds *how many turns* (roughly) a single invocation can run before stopping, and a spike in
recorded cost still means "this turn did more work than usual" even though nothing is invoiced for
it. What it does **not** mean: a guarantee against a real bill. Anyone reading `ledger/spend.jsonl`
after this change ships must not read it as Denis's Anthropic invoice.

### D2b — Quota exhaustion is already a distinct, wired outcome — checked, not assumed

**The dispatch's ask:** *"a loop that hits a subscription limit at 3am is indistinguishable, from
the outside, from a broken factory"* unless exhaustion lands in the record as its own thing, not a
generic `task_error` — the same discriminator failure S194's sixth instance already found once.

**Checked against the actual code, not the enum names alone** (`src/yosefactory/executor/`):
- `RunOutcome.BUDGET_EXHAUSTED` and `FailureKind.RATE_LIMIT` both exist in `outcome.py`, **and**
- `stream.py` actually emits them from real signal, not merely declares them: a `rate_limit_event`
  stream event sets `self.rate_limited = True` (`stream.py:153-154`); an HTTP `429`
  (`_RATE_LIMIT_STATUS`) is checked explicitly (`stream.py:186-187`); the terminal-classification
  path returns `RunOutcome.FAILED, FailureKind.RATE_LIMIT, "quota exhausted, no terminal event"`
  when the stream was rate-limited but never reached a terminal event (`stream.py:179-180`), and
  `RunOutcome.BUDGET_EXHAUSTED` is returned directly from the CLI's own `budget_exhausted` subtype
  (`stream.py:202`, `_BUDGET_REASON`). This is wired, tested, and reachable — not an S195 instance.

**Conclusion: no new field is needed, and none is added.** A subscription-quota exhaustion during
a container-run turn already lands as `RunOutcome.FAILED` with `FailureKind.RATE_LIMIT` (or, for a
per-turn budget ceiling specifically, `RunOutcome.BUDGET_EXHAUSTED`) on that turn's `RunResult`,
carried into the ledger record exactly as any other typed outcome is — `protocol_outcome` maps
both to `Outcome.FAILED`, distinguishable from a crash (`FailureKind.CRASH`) or a task-shaped
failure (`FailureKind.TASK_ERROR`) by `failure_kind` alone, readable from disk. What this change
adds is not code here but the design record confirming the taxonomy already answers the question
the dispatch raised — stated rather than silently assumed, per the instruction not to invent a
field without saying so.

**What is still Denis's, stated plainly (Article XII — don't claim a decision that is not made):**
he has now supplied the token; nothing about *which* variable or *its value* is left open. What
remains his is any production deployment decision this change deliberately does not make
(Non-goals).

**A twelfth-family S194 instance, found diagnosing the first token.** `claude auth status` inside
the container reported `{"loggedIn": true, "authMethod": "oauth_token", ...}` against a token that
turned out to be truncated (58 of 108 characters — a short paste, nothing account-side). The
real cause of the `401` this change hit first. **`loggedIn: true` was correct and useless at the
same time**: it reports that a token is *present and shaped like a token*, not that it is *valid*
— the same instrument-not-subject gap S194 already names, one layer lower than any of its other
instances (a CLI's own self-report about its own auth state, not this platform's). Recorded here
because nothing in this repo would otherwise say so: if `claude auth status` is ever used as a
readiness check for this container (it is not, today — this change only ran it as a manual
diagnostic), it answers "is a token configured," not "will the next real call succeed."

### D3 — Base image, `uv`, and the pinned `claude` binary

**Chosen:** `python:3.12-slim` (Debian-based, matches `requires-python = ">=3.11"` and the `.venv`
this repo already builds under CPython 3.12 on the dev host). Install `uv` via its own installer
script (same mechanism this repo's `uv.lock` already assumes exists on a dev machine). Install
`claude` via Anthropic's own installer (`curl -fsSL https://claude.ai/install.sh | bash -s --
2.1.225`), **pinned to the exact version** `executor/claude.py::PINNED_VERSION` names — a
different version is a different capability map by that module's own docstring ("behaviour is a
property of the binary... invalid unless checked against a pinned version"), so the container must
carry the same one the code's own claims were measured against, not "whatever's current."

**`UV_PROJECT_ENVIRONMENT` set to a path outside `/app`** (e.g. `/opt/venv`) — the standard fix for
"the venv `uv sync` built at image-build time otherwise gets shadowed the instant the dev bind
mount covers `/app`, and every `uv run` inside the running container silently falls back to
resyncing from scratch (or fails) instead of using what the image already built." Verified, not
assumed: task 3 in tasks.md runs `uv run python -c "import yosefactory"` inside the mounted
container and confirms it resolves without a fresh sync.

### D4 — Compose command: `yosefactory-loop-scheduled`, mandatory ceiling carried forward unchanged

**Chosen:** the default `command:` in `docker-compose.yml` invokes `yosefactory-loop-scheduled
/data/workspace --max-iterations <N> --spend-ceiling-usd <C>` — the exact entrypoint
`add-scheduled-loop` built, unchanged. The container is simply the new "who invokes it";
`scheduled_main`'s argument-parser-enforced ceiling is exactly as load-bearing here as it would
have been under `launchd`, because the property it defends against (something that can spend
without a human watching) is a property of *unattended invocation*, not of *which unattended
mechanism*.

## Money

Same figures `add-scheduled-loop`'s design reasoned to, unchanged premise (D022 §3's interactive
deferral fails once nothing is watching, whether the "nothing watching" mechanism is `launchd` or
a container's own restart policy) — **with one change from D2/D2b above: under
`CLAUDE_CODE_OAUTH_TOKEN`, no dollar amount below is actually invoiced.** They remain real
*numbers* (`total_cost_usd` is still what the binary reports per turn) and a real *rate signal*,
and the ceiling remains a genuine stop condition `LoopBound` enforces — what changes is only that
crossing it protects subscription quota, not a bill.

- **Compose default: `--spend-ceiling-usd 2.00`, `--max-iterations 5`.** ~40% headroom over
  `5 × $0.285 = $1.425` measured cost, a real ceiling `LoopBound` enforces, not a target — now read
  as "roughly how many turns before this invocation stops," not "how many dollars this invocation
  is allowed to cost."
- **Dev posture (this change's default `docker-compose.yml`): no restart policy, run on demand**
  (`docker compose run factory` / `docker compose up`, not `restart: unless-stopped`) — a developer
  watches it start, matching the same "a human is present" premise D022 scopes its own deferral to,
  even though the entrypoint's ceiling is mandatory regardless.
- **Production posture (not built, stated for contrast — Non-goals): a scheduled/restarting
  container** (`restart: unless-stopped`, or an external scheduler invoking `docker compose run` on
  a timer) **would need the same reasoning `add-scheduled-loop`'s design applied to `launchd`'s
  `StartInterval`** — an interval choice bounding worst-case sustained spend. Not designed here
  because it is a deployment decision Non-goals defers to Denis, but the number that answered it
  under `launchd` (15 min / `$8/hour` worst case) transfers unchanged if a restart-policy container
  is what he chooses.

**Found while building the receipt, worth recording rather than silently working around:**
`runtime/spend.py`'s own docstring states its resolution deliberately — *"spend belongs to the
platform that paid for the call, not to the repository the call happened to be working on"* —
`SPEND_LOG` resolves from `Path(__file__)`'s own location (yosefactory's checkout), not from
`Places.queue`, on purpose, so a turn against a foreign workspace still bills yosefactory's ledger.
Under this change's dev bind mount, `/app` **is** yosefactory's checkout (bind-mounted from the
same host directory this change is developed in), so a container-run turn's spend row lands in the
**real** `~/Workspaces/yosefactory/ledger/spend.jsonl` — the same file `git status` in this
checkout sees — exactly as intended, not a leak between the source mount and the D1-separated
queue mount. Practical consequence: a live in-container receipt's spend row is expected to show up
as an uncommitted change in this very checkout afterward, and gets committed as part of this
change's own record, matching `add-turn-loop`'s own precedent of committing its live receipt's
spend rows. Not a defect; not fixed; recorded so a future reader does not mistake it for one.
- `make check` stays $0 — verified by reading `ledger/spend.jsonl` line count before/after in
  tasks.md, same discipline every prior change in this repo has used.

### Known, unaddressed cost — an empty backlog is a billed planning turn, not a free `nothing-ready` ([[S987]])

**Found live, not designed for:** the first attempt at this change's $0 receipt ran against a
genuinely empty `.dev-workspace` and, instead of the free `nothing-ready` path every prior receipt
in this repo assumed, `take_turn` started a real planning turn — a real executor call. It only cost
$0 that time because the call happened to fail (the truncated-token `401`, above) before billing.
The free receipt this change actually holds (tasks.md 5.1) required seeding one `snoozed` item to
hold the loop in the `nothing-ready` branch on purpose — the same fixture pattern
`add-turn-loop`'s tests already used, now load-bearing rather than incidental.

**Why a scheduler makes this the dominant case, not an edge case.** A human running the loop by
hand mostly does it when there is something to look at; a scheduler on a fixed interval wakes up
on a clock regardless, and *most* of those wakes will find nothing ready — that is what "idle" is.
Under the shipped 15-minute default, **the common case is discovering there is nothing to do, and
paying for the discovery.** `LoopBound.spend_ceiling_usd` bounds what a *working* loop can spend;
it says nothing about what an *idle* one spends finding out it has nothing to do, because that
spend happens inside a single planning turn the bound has no visibility into until after the fact.

**Not measured, and not reported as measured.** Every dollar figure this design cites elsewhere
(`$0.285`/turn, the `$2.00`/`5`-iteration ceiling) comes from turns that did real work. No
empty-backlog planning turn run under this change has ever completed and billed — the one this
change triggered failed on auth before any cost was incurred. An extrapolation like "$X/day idle"
would be arithmetic wearing the costume of a measurement; not done here.

**Deliberately not remedied in this change** — the scope is "the factory runs in a container,"
not "the loop is cost-optimal when idle," and a fix here would be exactly the kind of quietly
smaller version of the dispatch Article VII warns against. Named instead, with candidates for
whoever picks it up:

1. **A free pre-flight eligibility check before waking the executor for planning.** Cheapest in
   principle — if `should_plan()`'s own answer can be made cheap to compute *and* distinguished
   from "planning is actually warranted," this removes the cost at the source. Not attempted here;
   `should_plan`'s own cost characteristics were not investigated as part of this change.
2. **A longer interval.** Blunt, already partially the shipped posture (15 min, chosen for wiring
   receipt cadence — design.md, Money) — trades discovery latency for fewer paid discoveries,
   without addressing that each discovery still bills.
3. **A wake condition that fires on arrival rather than only on a clock.** Already one of the
   three `run_loop` wake conditions (`WakeReason.READY_ITEM` / `EXTERNAL_EVENT`) — the heartbeat
   is what forces a wake with nothing new to react to. A configuration that relies more heavily on
   arrival-based wakes and less on the heartbeat would reduce how often the loop wakes into an
   empty backlog at all, at the cost of the staleness the heartbeat exists to bound
   (`turn-loop/wake-and-bound`'s own reasoning for why the heartbeat cannot simply be dropped).

None of these is built here. This section exists so the cost is a stated, named debt rather than a
silently shipped default that bills on every idle wake.

## Platform — what differs between this Darwin host and a Linux container

- **`claude` binary.** Native, platform-specific. The Dockerfile installs the Linux build inside
  the image; the Darwin binary on the host is irrelevant to what runs in-container. Pinned version
  must match (D3).
- **Auth.** Keychain (Darwin, today) vs. env var (container, this change) — D2. Not a detail, the
  actual mechanism changes.
- **`uv`.** Installed fresh inside the image (Linux build); this repo's `uv.lock` is
  platform-portable (uv resolves wheels per-platform from the same lock), so no lock change is
  needed — verified by `uv sync` succeeding inside the Linux image in task 2.
- **git `safe.directory`.** A bind-mounted repo owned by a different UID than the container process
  trips git's ownership check (`fatal: detected dubious ownership`) — set via
  `git config --global --add safe.directory /app` in the image, not left to fail inside the
  container the first time any git command runs there.
- **File ownership on the mount.** A process running as root inside the container (the default,
  simplest posture, and this change's choice per Non-goals — UID/GID matching is out of scope)
  writes root-owned files back through the bind mount into the host directory. Cosmetic on
  Docker Desktop for Mac in practice (its virtiofs/gRPC-FUSE layer does not enforce host-side
  ownership the way a native Linux bind mount would), but stated here rather than discovered by
  someone hitting a permission error later.
