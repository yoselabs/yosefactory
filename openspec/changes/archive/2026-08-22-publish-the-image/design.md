Motivation: see [proposal.md](proposal.md) — Why. No spec-level capability delta (`skip_specs:
true` in `.openspec.yaml`) — this is a publish pipeline, not runtime behavior.

## Context

`Dockerfile` builds locally (dev compose, `run-the-loop-inside-the-container`). Nobody has built
it in a clean CI environment or published it anywhere. `factory-state`'s private runner (next
change, not this one) needs a `docker pull` it can run with no registry credential — GHCR's
anonymous-pull path for public packages.

## Decisions

### D1 — Trigger: push-to-main with a path filter, plus `workflow_dispatch` always

**Chosen:** trigger on `push` to `main`, filtered to
`Dockerfile`, `.dockerignore`, `docker-entrypoint.sh`, `pyproject.toml`, `uv.lock` — every input
that actually invalidates a build layer. `workflow_dispatch` unconditionally, for a manual
republish (e.g. registry visibility fixed, or a rebuild wanted with no source change).

**Why not every push:** the `patchright install --with-deps chromium` layer alone is ~2.8GB
(D023 §4, `ship-a2web-toolchain-as-a-stopgap`'s measured price: 2.16GB → 4.97GB). A full build is
long. A path filter means a README or `workflows/` edit — the overwhelming majority of commits in
this repo's history — does not pay that cost. `src/` is deliberately *not* in the filter: it is
`COPY`'d late (after the dependency-sync layers) specifically so source edits are cheap to layer,
and the image's actual behavior for `src/` changes is exercised by `make check`, not by a
republish; the image only needs rebuilding when its *build recipe* changes.

**Cost of being wrong:** if a `src/` change matters to the image and the filter misses it, the
running image silently lags source until the next filtered commit or a manual dispatch. Mitigated
by `workflow_dispatch` being one click away and by GHCR's caching making a full rebuild non-costly
labor even if slow. Revisit trigger: a src/-only fix needed to reach the image before Dockerfile
next changes.

### D2 — Tagging: `latest` (moving) + `sha-<full-sha>` (immutable, what the runner pins)

**Chosen:** `docker/metadata-action` generates two tags per build:
- `ghcr.io/yoselabs/yosefactory:latest` — default-branch head, human/dev convenience only.
- `ghcr.io/yoselabs/yosefactory:sha-<full 40-char sha>` — one per build, never overwritten.

The private runner in `factory-state` pins the `sha-` tag. A receipt that names `:latest` is not a
receipt — it moves out from under whatever pinned it the next time `main` advances, and a runner
that floats on `latest` cannot tell you which commit's `Dockerfile` it is actually running.
`sha-<sha>` is traceable straight back to the commit that produced it with no side table.

**Not chosen:** a semantic-version tag (no release process exists yet — nothing assigns versions);
a date-based tag (redundant with the sha, and two immutable tags per build is one too many for no
added information the git history doesn't already carry).

### D3 — Caching: GitHub Actions cache via buildx (`type=gha`, `mode=max`)

**Chosen:** `cache-from: type=gha` / `cache-to: type=gha,mode=max` on the `docker/build-push-
action` step. `mode=max` caches every intermediate layer, not just the final image, which matters
here specifically because the two most expensive layers (`uv sync`, the Chromium install) sit
*before* the final `COPY . .` — without `max` mode those layers are not reusable cache-source for
a build that only changed source after them.

**Why it pays for itself here:** this is the one build in the fleet with a multi-gigabyte layer
that changes rarely (the Chromium/patchright pin) sitting behind layers that change often (source,
lockfile). GHA cache is free (bundled with Actions), bounded at 10GB per repo with LRU eviction —
cheap relative to a bare rebuild of a ~5GB image on every triggered run.

**Not chosen:** registry cache (`type=registry`) — an extra image reference to manage in GHCR for
marginal benefit over the bundled GHA cache at this scale; revisit if the GHA cache's 10GB ceiling
starts evicting the Chromium layer before it is reused.

### D4 — Provenance: buildx's built-in SLSA attestation, not `actions/attest-build-provenance`

**Chosen:** `provenance: true` on the `build-push-action` step. BuildKit generates the SLSA
provenance attestation and pushes it to the registry through the same `packages: write` credential
already granted for the image push itself.

**Why not the GitHub-native attestation action:** `actions/attest-build-provenance` needs
`id-token: write` and `attestations: write` — permissions this workflow does not otherwise need,
and the dispatch is explicit that `permissions:` stays at exactly `contents: read` +
`packages: write`. The buildx-embedded form gets a real, checkable provenance attestation attached
to the manifest for zero permission cost, so it clears the "cheap, take it" bar; the GitHub-native
form does not, at this scope.

### D5 — Visibility: cannot be forced from the workflow; verified manually, named as Denis's item

GHCR packages published via a repo's automatic `GITHUB_TOKEN` are created **private** on first
push regardless of the source repo's own visibility — this is a package-registry-level default,
not a workflow setting, and no `permissions:` grant changes it. Nothing in `docker/build-push-
action` or `docker/login-action` can set it public; there is no `visibility:` input for the
`GITHUB_TOKEN` push path. Confirmed against GitHub's own docs for GHCR + `GITHUB_TOKEN` (container
registry default visibility) rather than assumed.

**Consequence:** the first successful run of this workflow creates the package, but it publishes
*private*. Making it public is one manual step in the repo's Package settings (`ghcr.io/yoselabs/
yosefactory` → Package settings → Danger Zone → Change visibility → Public), a one-time action for
whoever holds admin on the `yoselabs` org/repo. This is not faked here — it is named as the open
item in the closing report, and the private runner's `docker pull` with no credential (this
change's actual deliverable requirement) does not work until that toggle happens.

## Non-Goals

See proposal.md — Non-goals.
