Motivation: see [proposal.md](proposal.md) — Why. No spec-level capability delta (`skip_specs:
true`) — this is a publish-pipeline trigger and an ADR correction, not runtime behavior.

## Decision 1 — Trigger: drop the path filter, fire on every push to `main`

### The property to hold

"Anything that changes what is inside the image causes a rebuild." Not "anything that changes
behavior" — content, because a receipt that names a `sha-` tag is claiming to describe *that
image's bytes*, and a path filter that misses a byte breaks the claim silently, the way it did
tonight.

### Mechanical derivation, not a guess

```
tracked files (git ls-files):           451
excluded by .dockerignore:                 0
kept in the Docker build context:        451
```

`.dockerignore` (full contents):

```
.venv/  .git/  __pycache__/  *.pyc  .pytest_cache/  .ruff_cache/  .ty_cache/
.coverage  coverage.xml  .env  .dev-workspace/
```

Every one of those patterns matches paths git does not track anyway (build/dev artifacts, the
`.git` directory itself, a local `.env`). Checked mechanically (`python3` script matching every
`git ls-files` entry against every `.dockerignore` pattern, output in the commit's working notes):
**zero tracked files are excluded.** `Dockerfile`'s `COPY . .` (line before the second `uv sync`)
therefore copies the entire tracked tree into the image, full stop — there is no tracked file that
is "clearly safe to exclude from the image" the way a path filter needs there to be.

Top-level tracked entries, all of them `COPY`'d: `.agents/ .beads/ .claude/ .codex/ .opencode/
backlog/ decisions/ ledger/ openspec/ questions/ scripts/ src/ tests/ tools/ workflows/`, plus
`.dockerignore .env.example .github/ .gitignore .pre-commit-config.yaml AGENTS.md CLAUDE.md
Dockerfile Makefile README.md docker-compose.yml docker-entrypoint.sh pyproject.toml uv.lock`.

The six-file filter this change removes named a strict subset of six entries out of twenty-one
top-level ones. `src/` was the omission that bit; `workflows/`, `tests/`, `openspec/`, `tools/`,
`scripts/`, `backlog/`, `ledger/`, `decisions/`, `questions/`, and every dotfile directory are
*also* uncovered and *also* enter the image. A correct path filter is not "add `src/`" — it is
"list all twenty-one," which is a second, hand-maintained copy of `git ls-files` that silently
drifts every time a new top-level thing is added (a new `workflows/` dir, a new tool directory) —
exactly the failure this change exists to close. **The honest filter is no filter.**

### Cost, measured rather than assumed

**Money: $0.** GitHub Actions minutes on standard GitHub-hosted runners are free for public
repositories on every plan (fetched live from `github.com/pricing`: "2,000 CI/CD minutes/month
Free for public repositories" on the Free plan, larger allowances on paid plans — the only paid
tier is *larger* runners, which this workflow does not use: `runs-on: ubuntu-latest`). This repo
is public (`yoselabs/yosefactory`). There is no per-run charge to weigh against.

**Wall-clock, from the last real push build** (`gh run view 32561173093`, `publish-the-image:
archive`, 2026-08-22T08:01–08:05, cache already warm — "importing cache manifest" logged at
start):

```
checkout + buildx setup + login + metadata           ~20s
apt/uv/curl layers (Dockerfile-unrelated, cached)     ~15s  (unaffected by a src-only push)
COPY . .  ->  uv sync --all-extras                    ~2s   (deps unchanged, near no-op)
patchright install --with-deps chromium               ~25s  (network fetch — re-runs on ANY
                                                                COPY-layer change, already, today,
                                                                on every currently-triggering build)
chown + image export/push                             ~150s (dominated by pushing ~5GB of layers;
                                                                unchanged layers dedupe by digest
                                                                and are not re-uploaded)
total                                                  3m59s
```

The Chromium layer sits *after* `COPY . .` in the current `Dockerfile`, so it is **already**
re-fetched on every build that fires today — ADR-0010's own D3 rationale ("the two most expensive
layers sit before the final `COPY . .`") is not true of the patchright/chromium layer specifically;
only `uv sync`'s dependency-install stage is genuinely upstream of source. Adding `src/` to the
trigger set therefore does not introduce a new expensive re-fetch — that cost is already paid on
every `Dockerfile`/`pyproject.toml`/`uv.lock`-triggered build. The marginal cost of also firing on
a `src/`-only (or any other tracked-file) push is the same ~4 minutes, at $0, run async in the
background, blocking nothing.

**Against this:** a filter that misses a tracked path strands the running machine on stale code
for an unbounded time — tonight, an entire evening of turns against pre-fix behavior, discovered
only because someone went looking. A 90-second-to-4-minute, $0, non-blocking rebuild is not worth
trading against that.

### Chosen

Remove `paths:` from the `push:` trigger entirely. `workflow_dispatch` stays, for a manual
republish with no `main` push (e.g. only a registry-visibility fix).

### Revisit trigger

The build cost stops being negligible — measured wall-clock on a cache-cold run exceeds ~15
minutes, or GitHub changes public-repo Actions pricing — and push frequency to `main` is high
enough that the queue backs up (`workflow_dispatch` runs queuing behind push-triggered ones).

## Decision 2 — Staleness detection: belongs in `factory-state`, not built here

### The problem, stated precisely

Two independent things can go stale:

1. **Does the workflow fire on every commit that should trigger it?** — closed by Decision 1.
2. **Does `factory-state`'s pinned `sha-<sha>` reference stay current with `main`?** — open, and
   is what tonight's incident actually was: the workflow *not firing* (1) caused the pin (2) to
   lag, but even with (1) fixed, nothing stops the pin from lagging again for an unrelated reason
   — a `factory-state` config that is never touched, a runner that never re-pulls.

### Why the check cannot live here

Detecting (2) requires comparing two values: `factory-state`'s currently-pinned `sha-` tag, and
`yosefactory`'s current `main` HEAD. The first value exists only inside `factory-state`, a private
repo this repository must not depend on (K D012 in spirit, and the dispatch's explicit
constraint). A check built in `yosefactory` either fabricates the comparison (reads nothing,
reports nothing real — the disallowed "passes by describing itself" shape) or reaches into
`factory-state` to read the pin, which is the forbidden dependency. Neither is buildable here
without violating a constraint.

### Why nothing new needs to be built anywhere, yet

The dependency direction that *is* allowed — private depends on public — already has what it
needs, at no extra cost:

- **`main`'s HEAD is public**: `git ls-remote https://github.com/yoselabs/yosefactory main`, or
  the GH REST API, from inside `factory-state`'s own tooling, no credential required.
- **The image is already labeled with its source commit**: `docker/metadata-action`'s
  `sha-<full-40-char-sha>` tag (ADR-0010 Decision 2, unchanged by this work) *is* the pin's
  provenance — a `factory-state`-side check needs only to diff its stored pin against `main`'s
  current HEAD, which it can fetch without ever touching this repo's internals.

### Decision

**Not built here.** This repo's contribution to staleness detection is the correct trigger
(Decision 1) plus the primitives it already publishes (immutable `sha-` tags, a public `main`).
The comparison itself — pin vs. HEAD — is `factory-state`'s job, because it is the only party that
holds both numbers, and it is free to depend on this public repo in a way this repo cannot
reciprocate. Naming this here, rather than silently building nothing, is the deliverable: the
alternative (a check that lives in the wrong repo, or a check that cannot see what it claims to
check) is worse than an honest gap with a named owner.

## Superseding ADR-0010

ADR-0010's own `Revisit trigger:` read: *"a `src/`-only change is found to need to reach the
published image before the next `Dockerfile`/lockfile change — the path filter would then be too
narrow."* **This is exactly what happened tonight** (ten `src/`-affecting commits, no intervening
`Dockerfile`/lockfile change, no rebuild). The trigger named the failing case precisely and fired
correctly — worth stating plainly because it is not the usual finding in this program: other
triggers in this corpus have been found to miss the case that actually occurred (Article XVI's
S195/S196 history), and this one did not. ADR-0010's defect was not an unwritten trigger; it was
that Decision 1's *reasoning* argued the wrong direction from a true premise (late `COPY` → cheap
edits) to a false conclusion (therefore exclude from the trigger) without checking what "cheap"
actually meant for the trigger's own purpose (content-completeness, not build latency).

New ADR (`decisions/0013-*`) supersedes ADR-0010 Decision 1 only; Decisions 2–5 (tagging, caching,
provenance, permissions) are untouched and remain in force under ADR-0010.
