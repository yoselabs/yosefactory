## Why

No K project 160 promotion id — direct dispatch against a measured defect, not a build-what-and-
why decision (`CLAUDE.md`: "a decision about how it got built -> `decisions/` here").

`.github/workflows/publish-image.yml` triggers on push to `main` path-filtered to `Dockerfile`,
`.dockerignore`, `docker-entrypoint.sh`, `pyproject.toml`, `uv.lock`, and itself. `src/` is not
listed. ADR-0010 (Decision 1) argues this deliberately: `src/` is `COPY`'d late so source edits
stay cheap, and a rebuild only matters when the build recipe changes. The conclusion does not
follow from the premise — the image contains `src/` (and everything else `COPY . .` reaches), so
a change to `src/` changes the image regardless of where in the `Dockerfile` the `COPY` sits.

Measured tonight: ten commits of runtime fixes (ADR-0011, ADR-0012) were pushed to `main`;
`gh run list --workflow=publish-image.yml` showed the last build still at 08:01, before any of
them. The private CI factory (`factory-state`) pins `sha-36f5903…` and ran turns all evening
against machine code that predated both fixes. The image was silently stale.

## What Changes

- **`.github/workflows/publish-image.yml`** — drop the `paths:` filter; trigger on every push to
  `main`, unconditionally (`workflow_dispatch` unchanged). Derivation in `design.md`: every one of
  this repo's 451 git-tracked files enters the Docker build context unfiltered — `.dockerignore`
  excludes zero of them — so the honest "files that can change the image" set is the whole tree,
  and a path filter enumerating it is a second copy of `git ls-files` that silently drifts (this
  is exactly how `src/` was missed).
- **`decisions/0010-*.md`** — `Superseded by:` updated to point at the new ADR; Decision 1's text
  annotated in place (not deleted — the reasoning is part of the historical record of why the
  filter existed) with a pointer to the correction.
- **New ADR** (`decisions/0013-*.md`) recording the trigger change, the mechanical derivation, the
  measured cost (cached build wall-clock, GitHub Actions pricing for public repos), and a
  `Revisit trigger:`.
- **Staleness detection — decided, not built here.** See design.md's Decision 2. The pin that can
  fall behind (`factory-state`'s image reference) lives in a private repo this one must not depend
  on; the comparison needs both values, so the check belongs where the pin lives, not here. What
  `factory-state` needs already exists (immutable `sha-<sha>` tags, and `main`'s HEAD is public via
  `git ls-remote`/the GH API) — nothing new to build in this repo.

## Non-goals

- **Not restructuring the `Dockerfile`** — the ordering that puts the ~2.8GB Chromium layer after
  `COPY . .` (so it is *already* invalidated by any tracked-file change today, on every currently-
  triggering build) is a real, separate inefficiency. Out of scope: this change fixes *when* the
  workflow fires, not the layer order inside it.
- **Not building a staleness detector in this repo.** Decided against, with reasoning, in
  design.md — not silently dropped.
- **Not touching `factory-state`** — private repo, not in this worker's scope, referenced only as
  the entity the trigger fix protects.

## Impact

- `.github/workflows/publish-image.yml` — `paths:` filter removed.
- `decisions/0010-image-publish-trigger-tags-and-provenance.md` — `Superseded by:` + Decision 1
  annotation.
- `decisions/0013-*.md` — new.
- No runtime code (`src/`, `workflows/`) touched.
