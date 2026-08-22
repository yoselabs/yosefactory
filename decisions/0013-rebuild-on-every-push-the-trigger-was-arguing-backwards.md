# ADR-0013 — Image publish trigger: every push to `main`, no path filter

**Status:** Accepted
**Date:** 2026-08-22
**Supersedes:** `decisions/0010-image-publish-trigger-tags-and-provenance.md` Decision 1 only
  (Decisions 2–5 — tagging, caching, provenance, permissions — remain in force, unchanged)
**Superseded by:** —
**Revisit trigger:** a cache-cold build's measured wall-clock exceeds ~15 minutes, or GitHub
changes public-repository Actions pricing, or push frequency to `main` backs up the queue against
`workflow_dispatch` runs.

## Context

ADR-0010 Decision 1 path-filtered the publish trigger to `Dockerfile`, `.dockerignore`,
`docker-entrypoint.sh`, `pyproject.toml`, `uv.lock`, and the workflow file itself, deliberately
excluding `src/`. Measured 2026-08-22: ten commits carrying real runtime fixes (the spend row
moving inside the turn's transaction, ADR-0011; the backlog liveness fix, ADR-0012) reached `main`
with no rebuild — `gh run list --workflow=publish-image.yml` showed the most recent build still at
08:01, the original. The private CI factory (`factory-state`) pins a `sha-` tag and ran turns all
evening against machine code that predated both fixes, with nothing surfacing the staleness.

ADR-0010's own `Revisit trigger:` named exactly this case (*"a `src/`-only change is found to need
to reach the published image before the next `Dockerfile`/lockfile change"*) and it fired the same
day it was written — worth stating because a trigger naming the actual failure and firing on it is
not the usual outcome in this program; other revisit triggers in this corpus have been found to
miss the case that occurred. ADR-0010's defect was in Decision 1's *reasoning*, not in an
unwritten or badly-aimed trigger.

## Decision

**Trigger:** `push` to `main`, unconditional — no `paths:` filter. `workflow_dispatch` unchanged,
for a manual republish with no accompanying `main` push.

## Why, with the derivation

**The premise ADR-0010 used was true and irrelevant to the trigger question.** `src/` *is* `COPY`'d
late in the `Dockerfile`, and that ordering *does* keep the dependency-install (`uv sync
--no-install-project`) layer reusable across source edits. But the property the trigger needs to
hold is not "keep expensive layers cached" — it is **"anything that changes what is inside the
image causes a rebuild."** Those are different properties, and satisfying the first does not
satisfy the second: the image's *content* changes on any `COPY`'d file, cache-hit or not.

**Mechanical check, not a guess.** Every one of this repo's 451 `git ls-files` entries was matched
against every `.dockerignore` pattern:

```
tracked files:                    451
excluded by .dockerignore:          0
enter the build context, subject to COPY . .:   451
```

`.dockerignore` excludes only `.venv/ .git/ __pycache__/ *.pyc .pytest_cache/ .ruff_cache/
.ty_cache/ .coverage coverage.xml .env .dev-workspace/` — paths git does not track anyway. There is
no tracked file that is safely excludable from "things that can change the image." Twenty-one
top-level tracked entries exist (`.agents/ .beads/ .claude/ .codex/ .opencode/ backlog/ decisions/
ledger/ openspec/ questions/ scripts/ src/ tests/ tools/ workflows/`, plus root dotfiles and
`pyproject.toml`/`uv.lock`/`Dockerfile`/`README.md`/etc.); the six-file filter named a third of
one of them. A correct filter would need to enumerate all twenty-one and stay current as new ones
appear — a second, hand-maintained copy of `git ls-files` that drifts on exactly the cadence this
incident demonstrated. **The honest filter is no filter.**

**Cost, measured rather than assumed.**

- *Money:* $0. GitHub Actions on standard (`ubuntu-latest`) runners is free for public
  repositories on every plan — confirmed live against `github.com/pricing` ("2,000 CI/CD
  minutes/month Free for public repositories" on Free, more on paid tiers; the only paid-for tier
  is *larger* runners, unused here). This repo, `yoselabs/yosefactory`, is public.
- *Wall-clock:* the last real push build (`gh run view 32561173093`, warm cache) took 3m59s
  end-to-end. Of that, the `patchright install --with-deps chromium` layer — the ~2.8GB layer
  ADR-0010 was trying to protect — sits **after** `COPY . .` in the current `Dockerfile`, so it is
  **already** re-fetched (~25s, confirmed in the run log — real network downloads, not a cache
  hit) on every build that fires *today*, regardless of this change. Only the `uv sync
  --no-install-project` dependency layer is genuinely upstream of `COPY . .` and stays cached. The
  dominant cost (~150s of the 4 minutes) is exporting/pushing the image, which does not grow for a
  source-only change — unchanged layers dedupe by digest and are not re-uploaded.
- *Net:* firing on a `src/`-only push costs the same ~4 minutes it already costs on every
  currently-triggering build, at $0, asynchronously, blocking nothing downstream.

**Against this:** a filter that misses a tracked path strands `factory-state` on stale code for an
unbounded time, discoverable only by someone going and looking — which is what happened. A
few-minutes, $0, non-blocking rebuild is not a cost worth trading against that.

## Consequences

- Every push to `main` — including a docs-only or `openspec/`-only change — now triggers a full
  publish run. This is intentional: the property held is content-completeness of the published
  image, not "only rebuild when it would plausibly matter," which is the judgment call that
  already failed once.
- The `Dockerfile`'s own layer ordering (Chromium install after `COPY . .`) is a separate,
  pre-existing inefficiency this change does not touch — see `openspec/changes/rebuild-the-image-
  when-the-machine-changes/proposal.md` Non-goals.
- Staleness detection for `factory-state`'s pin against `main`'s current HEAD was considered and
  explicitly **not** built in this repo — see the same change's `design.md` Decision 2. This repo
  must not depend on `factory-state` (private); the comparison needs both values, so it belongs
  where the pin lives, using primitives this repo already publishes (`sha-<sha>` tags, a public
  `main`).

## References

- `openspec/changes/rebuild-the-image-when-the-machine-changes/proposal.md`, `design.md`.
- `decisions/0010-image-publish-trigger-tags-and-provenance.md` — superseded Decision 1; Decisions
  2–5 unchanged.
- `decisions/0011-*.md`, `decisions/0012-*.md` — the two commits that were silently stale tonight.
- `.github/workflows/publish-image.yml`.
