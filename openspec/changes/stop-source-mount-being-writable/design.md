## Options weighed

**1. Mount source read-only (`./:/app:ro`) — chosen.**

Measured directly against the built image (`docker build .`, then `docker run -v
"$(pwd)":/app:ro`):

- `python3 -c "import yosefactory"`, `ty check src/` — pass unmodified. `ty` only warns
  (`pyvenv.cfg` `home` field, unrelated to writability).
- `pytest -q` — passes; the only symptom is a `PytestCacheWarning` (`.pytest_cache` write
  refused), tests still run and report results.
- `ruff check src/ tests/` — **fails hard**: `Failed to create temporary file … Read-only file
  system` at `/app/.ruff_cache/...`.
- Both fixed with an env var, no source change: `RUFF_CACHE_DIR=/tmp/ruff-cache` and
  `PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"`. Re-ran `make check` (`lint ty test
  citations`) inside the RO-mounted container with both set — **all four targets pass**,
  including `citations`, which just skips (no K checkout inside the container, expected).

Cost: two env vars, set in `Dockerfile` (not per-compose) so they apply to any container
invocation, `docker compose` or a bare `docker run`, and never touch the host — `RUFF_CACHE_DIR`/
`PYTEST_ADDOPTS` are only read by the tools when set, and they are set only inside the image.

Chosen because it keeps the live-edit dev loop exactly as documented in `docker-compose.yml`'s own
header (a source edit takes effect on the next command, no rebuild) while making the boundary
structural rather than conventional: nothing a turn does inside the container can write to `/app`,
regardless of what the agent decides to plan or build.

**2. Drop the source mount, run the built image as-is — rejected for dev, correct for
production.**

`docker-compose.yml`'s own header already says this is the production posture. Cost: every source
edit needs a rebuild before the next container run, which breaks the fast dev loop this compose
file exists for. Not rejected as wrong — deferred to whoever builds the production topology
(Non-goals), where a rebuild-per-deploy is the normal cost of that posture, not a per-edit tax.

**3. Keep the mount writable, deny the agent's uid write access — rejected, wrong layer.**

ADR-0007 fixes the container's user to uid 1000 so `--permission-mode bypassPermissions` is
accepted by the `claude` binary (it refuses to run as root). That is an *identity* constraint, not
a *filesystem* one — uid 1000 already owns nothing special about `/app`; the bind-mounted host
directory's ownership is whatever the host user's files are (commonly host-uid, which inside the
container reads as an unmapped or arbitrary uid, but that is incidental, not a security boundary).
Denying write via `chmod`/ACL on the host-side directory would require the host repo itself to be
read-only for the operator's own editor, which is unacceptable, or a bind-mount option
(`:ro`) — which is Option 1, arrived at from the other direction. There is no third filesystem
mechanism between "the mount is writable" and "the mount is not" that doesn't route through the
mount flag itself. ADR-0008 (the host-path guard) is unrelated: it blocks *committing* host paths
into tracked content, not writing to the mounted tree.

## The startup assertion

**Decided: yes, add one.** `orchestration.md`'s own accounting of this repository's failures names
the pattern directly — "a declared boundary with no live check is the S195 pattern" — and this
change is exactly a declared boundary (`:ro` in a YAML file) with nothing that notices if a later
edit drops the flag. `docker-entrypoint.sh` already gates the two turn-running commands
(`yosefactory-loop`, `yosefactory-loop-scheduled`) on `CLAUDE_CODE_OAUTH_TOKEN` being present; the
same case block gains a second check: if `$YF_SOURCE_ROOT` (default `/app`) is writable, refuse to
start rather than run the turn.

**Scope: both entrypoints, not just the unattended one.** The interactive path
(`main(unattended=False)`, invoked as `yosefactory-loop`) is a human present at a keyboard, but the
mount itself does not know who is watching — the compose file has one service, one mount, and a
human overriding the command to run `yosefactory-loop` interactively still runs it through the same
container and the same mount. If the boundary is worth having, it is worth having for both
commands this entrypoint recognizes; a human who genuinely needs write access has other ways to get
a shell into the image (`docker compose run --rm factory bash`, which passes through the entrypoint
untouched — `bash` matches neither case arm).

**Not scoped to every command.** `claude --version`, `python -c "import yosefactory"` and similar
diagnostics (already carved out of the existing token check, same case statement) do not touch a
turn and are unaffected.

**Testable without a real container.** The check is `[ -w "$YF_SOURCE_ROOT" ]`, and
`YF_SOURCE_ROOT` is overridable — a test can point it at a `tmp_path` fixture, `chmod` it
read-only or writable, and invoke the real shipped script via `subprocess`, exactly the pattern
`tests/scripts/test_forbid_host_paths.py` already uses for `forbid-host-paths.py`. This is a real
receipt on the guard logic itself; it is not a receipt that the compose file's `:ro` flag is
present or that the real Docker bind-mount enforces it, which unit tests structurally cannot
reach (see Verification below).

## Verification — what a test can prove and what it cannot

Unit tests can prove: the entrypoint script refuses to start when its source root is writable, and
starts (proceeds past the guard) when it is not — this is the actual shipped bash logic, driven as
a subprocess, not a reimplementation.

Unit tests cannot prove: that `docker-compose.yml`'s `:ro` flag actually makes the real Docker bind
mount read-only from inside a real container, or that `make check` still passes under the real
compose-driven container. Those require Docker. Both were verified manually (see Option 1's
measurements above and `tasks.md`'s manual-verification step) but that verification is a one-time
receipt from this session, not a standing check — nothing in `make check` builds a Docker image or
runs a container, and this change does not add that (would require Docker-in-CI, out of scope
here, not requested).

**What a human must run to verify the containment for real**, stated so no stronger claim than this
is made:

```sh
cd ~/Workspaces/yosefactory
docker compose build
docker compose run --rm factory sh -c 'echo hi > /app/PROOF_OF_WRITE 2>&1; echo exit=$?'
# expect: exit=1, "Read-only file system", and no PROOF_OF_WRITE on the host afterward
docker compose run --rm factory yosefactory-loop-scheduled --help
# expect: help text, exit 0 -- the entrypoint's guard passed because /app is genuinely read-only
docker compose run --rm factory make check
# expect: all four targets pass (citations SKIPs, no K checkout in the container)
```
