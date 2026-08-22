## 1. Workflow

- [x] 1.1 `.github/workflows/publish-image.yml` — push-to-`main` (path-filtered) + `workflow_dispatch`,
      `docker/build-push-action@v6` to `ghcr.io/yoselabs/yosefactory`.
- [x] 1.2 Tags: `latest` (default-branch moving) + `sha-<full-sha>` (immutable, runner-pinned) via
      `docker/metadata-action@v5`.
- [x] 1.3 `permissions:` exactly `contents: read`, `packages: write` — no other scope.
- [x] 1.4 Cache: `type=gha`, `mode=max`.
- [x] 1.5 Provenance: `provenance: true` (buildx built-in, no extra permission).

## 2. Reproducibility

- [x] 2.1 Build the image locally from a clean context (`docker build --no-cache`) and confirm it
      completes and produces a runnable image.
- [x] 2.2 Reason about anything the local build cannot prove for CI (architecture, GHCR-specific
      auth/visibility, GHA cache behavior) and state it as unproven.
- [x] 2.3 If the build surfaces a genuine reproducibility defect (host-dependent path, file outside
      build context, `.dockerignore` gap) — fix only that, in its own commit, with its own ADR.
      **Not triggered**: clean-context `docker build --no-cache` succeeded end to end
      (`claude --version` → `2.1.225`, matches the pinned `ARG`; `python3 -c "import yosefactory"`
      ok; entrypoint's token guard fires correctly with no token set; image ~4.98GB, matching the
      Dockerfile's own documented estimate). No `Dockerfile`/`.dockerignore` edit made.

## 3. Visibility

- [x] 3.1 Determine whether GHCR packages pushed via `GITHUB_TOKEN` are public by default or need
      a manual toggle — from GitHub's own documentation, not assumption.
- [x] 3.2 State the finding plainly in the closing report; if manual, name it as Denis's item.

## 4. ADR + validation

- [x] 4.1 Write `decisions/000N-*.md` for the non-obvious calls (tagging scheme, path-filtered
      trigger) with a `Revisit trigger:` line.
- [x] 4.2 `python3 tools/hooks/forbid-host-paths.py` clean over new/changed files (public repo).
- [x] 4.3 Lint the workflow YAML with whatever is available (actionlint / yamllint / `python3 -c
      "import yaml"` at minimum).
- [x] 4.4 `openspec validate publish-the-image --strict` passes.
