## Why

K decision **D024** (2026-08-22) puts the factory in CI: one turn per job, the CI trigger is the
wake, and the host contract is three lines — run our image, inject the token, hand it a writable
remote. K decision **D025** (2026-08-22, `decided_by: denis`, unconditional) says no credential
and no private corpus may enter a public execution context. That forced the topology now being
built:

```
yoselabs/yosefactory     PUBLIC    the machine -- code + image
yoselabs/factory-state   PRIVATE   queue, ledger, receipts, the token   (created, empty)
yoselabs/factory-sandbox PUBLIC    a throwaway workspace                (created, empty)
```

The private runner pulls the image; it cannot build it, because the build belongs with the code.
**Nothing downstream can start until a pullable image exists.** That is this change and nothing
else — no queue, no runner workflow, no `factory-state`/`factory-sandbox` content.

## What Changes

- **`.github/workflows/publish-image.yml`** — builds `Dockerfile` and pushes it to GHCR as
  `ghcr.io/yoselabs/yosefactory`, on push to `main` (path-filtered to build-relevant files) and on
  `workflow_dispatch`.
- **Tagging**: a moving `latest` (default-branch head, human/dev convenience) plus an immutable
  `sha-<full-sha>` per build. The runner pins the immutable tag; `latest` is not a receipt.
- **Caching**: GitHub Actions cache (`type=gha`, `mode=max`) via buildx, so the ~2.8GB Chromium
  layer (D023 §4 stopgap) is not rebuilt from scratch on every push that touches an unrelated
  layer.
- **Provenance**: buildx's built-in SLSA provenance attestation (`provenance: true`), pushed to
  the registry alongside the image using the same `packages: write` credential already granted —
  no extra permission scope, no OIDC.
- **`permissions:` minimal** — `contents: read`, `packages: write`. No secret beyond the automatic
  `GITHUB_TOKEN`.
- Possibly a `Dockerfile`/`.dockerignore` fix, **in its own commit with its own ADR**, if the local
  clean-context build surfaces a reproducibility problem (a host-dependent path, a file the build
  context cannot see). Reported as a finding either way.

## Non-goals

- **`factory-state`, `factory-sandbox`** — untouched. Next changes, not this one.
- **The runner workflow that pulls and runs the image** — not built here. This change ends at "a
  pullable image exists."
- **Making the package public** — attempted via workflow config where GHCR permits it, but GHCR's
  default-private-package behavior may require a one-time manual toggle in the repo's package
  settings; if so, that is named as an item for Denis, not faked.
- **Changing what the image build does.** The `Dockerfile`'s actual build steps are not touched
  unless the clean-context build proves they cannot run reproducibly in CI, per the dispatch's
  constraint.
- **Multi-arch builds.** `linux/amd64` only — the private runner's own architecture is not yet a
  stated requirement, and multi-arch approximately doubles the build cost of an already-long
  build.

## Impact

- `.github/workflows/publish-image.yml` — new.
- `decisions/000N-*.md` — new ADR(s) for the tagging scheme and trigger/path-filter choice
  (non-obvious build-time calls per `openspec/config.yaml`'s archive guidance).
- `Dockerfile`/`.dockerignore` — touched only if the clean-context build finds a reproducibility
  defect; reported either way.
- No runtime code (`src/`, `workflows/`) touched.
