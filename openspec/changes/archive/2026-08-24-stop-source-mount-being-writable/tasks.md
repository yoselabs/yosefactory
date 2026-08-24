## 1. Compose and image

- [x] 1.1 `docker-compose.yml`: source mount `./:/app` → `./:/app:ro`.
- [x] 1.2 `Dockerfile`: add `ENV RUFF_CACHE_DIR=/tmp/ruff-cache` and
      `ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"`.
- [x] 1.3 Rebuild the image and re-run `make check` inside it with the source bind-mounted `:ro`,
      confirm all four targets pass (manual, not part of `make check` itself — see design.md).

## 2. The startup assertion

- [x] 2.1 `docker-entrypoint.sh`: before the existing token check, for the same two commands
      (`yosefactory-loop`, `yosefactory-loop-scheduled`), refuse to start if
      `${YF_SOURCE_ROOT:-/app}` is writable; message names the path, never silent.
- [x] 2.2 `tests/scripts/test_entrypoint_write_guard.py`: drives the real script via subprocess
      against a `tmp_path` with `YF_SOURCE_ROOT` overridden, read-only and writable cases.

## 3. Record

- [x] 3.1 `decisions/0017-*.md` — ADR for the read-only mount + startup assertion, referencing S245
      and the three options weighed in `design.md`.

## 4. Verify

- [x] 4.1 `make check` (host) green.
- [x] 4.2 `openspec validate stop-source-mount-being-writable --strict` passes.
