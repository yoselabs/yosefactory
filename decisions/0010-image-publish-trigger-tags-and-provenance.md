# ADR-0010 — Image publish workflow: path-filtered trigger, dual tags, buildx-native provenance

**Status:** Accepted (Decision 1 superseded — see below)
**Date:** 2026-08-22
**Supersedes:** —
**Superseded by:** `decisions/0013-rebuild-on-every-push-the-trigger-was-arguing-backwards.md`
(Decision 1 only — Decisions 2–5 below remain in force)
**Revisit trigger:** a `src/`-only change is found to need to reach the published image before the
next `Dockerfile`/lockfile change — the path filter (Decision 1) would then be too narrow.
**This fired the same day it was written.** Ten `src/`-affecting commits reached `main` with no
intervening `Dockerfile`/lockfile change and no rebuild — see `decisions/0013-*.md`.

## Context

K decision D024 puts the factory in CI; D025 forbids the credential and the corpus from entering a
public execution context. That forced a split-repo topology — this public repo builds the image,
a private repo (`factory-state`, not yet built) pulls and runs it with no registry secret. Nothing
downstream can start until a pullable image exists.
`openspec/changes/publish-the-image/design.md` has the full reasoning; this ADR is the durable
build-time record of what a future worker would otherwise plausibly change back without knowing
why.

## Decision

`.github/workflows/publish-image.yml`:

1. **Trigger — SUPERSEDED, see `decisions/0013-*.md`.** Originally: push to `main`, path-filtered
   to `Dockerfile`, `.dockerignore`, `docker-entrypoint.sh`, `pyproject.toml`, `uv.lock`, and the
   workflow file itself; plus `workflow_dispatch` unconditionally. Reasoning at the time: not every
   push, because the Chromium/patchright layer (D023 §4) alone is ~2.8GB and `src/` is `COPY`'d
   late in the `Dockerfile` deliberately so source edits never invalidate the expensive layers — a
   rebuild the image doesn't need is a real, avoidable cost on every commit that never touches the
   build recipe. **The conclusion did not follow from the premise**: the image contains `src/`
   regardless of where in the `Dockerfile` its `COPY` sits, so a source change is a content change
   whether or not it invalidates any particular cache layer — cheap-to-*build* and safe-to-*skip*
   are different properties, and this decision conflated them. `decisions/0013-*.md` corrects it
   with a mechanical derivation and a measured cost; kept here verbatim as the historical record of
   why the filter existed and what was wrong with the reasoning, not deleted.
2. **Tagging** — `latest` (moving, default-branch head) plus `sha-<full 40-char sha>`
   (immutable, one per build). The runner in `factory-state` pins the `sha-` tag; `:latest` is
   convenience, never what anything downstream trusts.
3. **Caching** — GitHub Actions cache via buildx, `type=gha` / `cache-to: type=gha,mode=max`.
   `mode=max` specifically, because the two expensive layers (`uv sync`, Chromium install) sit
   before the final `COPY . .` and are otherwise not reusable cache source across builds.
4. **Provenance** — buildx's built-in SLSA attestation (`provenance: true`), not
   `actions/attest-build-provenance`. The GitHub-native action needs `id-token: write` +
   `attestations: write`; this workflow's `permissions:` is exactly `contents: read` +
   `packages: write`, per the dispatch. The buildx form gets a real attestation on the manifest at
   zero extra permission cost.
5. **`permissions:`** — exactly `contents: read`, `packages: write`. No other scope, no secret
   beyond the automatic `GITHUB_TOKEN`.

## Consequences

- **Visibility is out of this workflow's reach.** GHCR packages pushed via `GITHUB_TOKEN` are
  created private on first publish regardless of the source repo's visibility — confirmed against
  GitHub's own docs, not assumed. No `permissions:` grant or action input changes this. The first
  successful run therefore creates the package **private**; making it public is a one-time manual
  step (repo → Packages → `yosefactory` → Package settings → Danger Zone → Change visibility →
  Public) for whoever holds admin on `yoselabs`. Until that toggle happens, an anonymous
  `docker pull` of the published image fails — this is this change's one open item, not something
  this ADR or the workflow can close.
- ~~A `src/`-only change does not trigger a republish.~~ **No longer true — Decision 1 superseded
  by `decisions/0013-*.md`.** Every push to `main` now triggers a republish.
- `linux/amd64` only — no multi-arch build. GitHub-hosted runners are amd64; a private runner's
  own architecture is not yet a stated requirement, and multi-arch roughly doubles an already-long
  build for no known consumer.

## References

- `openspec/changes/publish-the-image/proposal.md`, `design.md`.
- `.github/workflows/publish-image.yml`.
- `decisions/0007-container-runs-as-uid-1000-not-root.md`, `decisions/0006-executor-pinned-to-
  sonnet-5-medium.md` — the image this workflow publishes.
- K project 160, D024, D025.
