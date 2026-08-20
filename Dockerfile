# yosefactory -- the loop, containerized. See
# openspec/changes/run-the-factory-in-a-container/design.md for why each decision here was made
# (D2/D2b: auth; D3: base image + pinned claude binary; D1: the mount race, handled in compose and
# in runtime/loop.py's own _refuse_if_dirty guard, not here).
#
# python:3.12-slim matches this repo's own `requires-python = ">=3.11"` and the CPython version the
# dev host's .venv already builds under.
FROM python:3.12-slim

# git: yosefactory's own runtime shells out to it (runtime/loop.py, runtime/turn.py -- every
# ledger commit and every wake-condition check is a real `git` subprocess call, not a library).
# curl/ca-certificates: needed once, to fetch the uv and claude installers below. make: a foreign
# workspace's own `test_command` (runtime/verify.py) is whatever that repository defines as
# passing -- a2web's is `make check`, and nothing before this line ever needed `make` because
# every prior receipt used yosefactory's own `pytest -q` default. Found running the first real
# cross-repo turn (run-a-turn-against-a2web): `verify._run` raised `'make' is not on PATH`
# before the gate could even attempt a2web's own checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates make \
    && rm -rf /var/lib/apt/lists/*

# uv, via its own installer -- the same mechanism this repo's uv.lock already assumes exists on a
# dev machine, not a package-manager build of it.
ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# claude, pinned to the EXACT version executor/claude.py::PINNED_VERSION names. Behaviour is a
# property of the binary and moves on point releases (that module's own docstring); shipping a
# different version here would silently invalidate every capability claim the code makes about it.
ARG CLAUDE_VERSION=2.1.225
ENV CLAUDE_INSTALL_ALLOW_SUDO=1
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- "${CLAUDE_VERSION}" \
    && ln -s /root/.local/bin/claude /usr/local/bin/claude  # hostpath-allow

# A bind-mounted repo owned by a different UID than the container process trips git's ownership
# check (`fatal: detected dubious ownership`) the first time any git command runs against it.
# `--system` (not `--global`) so this and the two settings below apply regardless of which user
# ends up running the container (see the non-root user below) -- one file, /etc/gitconfig, not one
# per HOME.
RUN git config --system --add safe.directory '*'

# runtime/turn.py::commit() shells out to `git commit` with no explicit author -- git falls back to
# guessing one from the OS user and hostname, and the container's own guess is not a valid email
# (`fatal: unable to auto-detect email address`), so every turn's own commit refuses before it
# starts. Found running the first real in-container turn (run-the-loop-inside-the-container).
# The same identity `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` already names
# (turn.py::PLATFORM_CO_AUTHOR) is used as the actual author here too, so a container-authored
# commit is identifiable as the platform's own rather than guessed from the container runtime.
RUN git config --system user.name "yosefactory" \
    && git config --system user.email "yosefactory@yoselabs.dev"

# The executor's own permission-bypass mode (build_argv's workspace_scoped branch,
# run-the-loop-inside-the-container D2) refuses outright when the process runs as root/sudo --
# a real, measured constraint, not a defect in this repo's own code. Found running the first real
# in-container turn. A fixed, non-root, non-host-matching uid is enough to satisfy it: this is not
# the UID/GID-matches-the-host-mount concern the prior change's Non-goals deferred to production,
# it is only "not root" -- the container never claims to reconcile with any host uid.
RUN useradd --create-home --uid 1000 --shell /bin/bash factory \
    && chmod -R o+rX /root  # hostpath-allow

# The venv lives OUTSIDE /app on purpose (design.md D3): the dev compose file bind-mounts the
# source tree onto /app, which would otherwise shadow whatever `uv sync` builds here at image-build
# time, forcing a silent resync (or failure) on every `uv run` inside the running container.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# Dependency layers first, so an edit to source (which the dev compose mount handles live anyway)
# never invalidates the dependency-install layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv sync --all-extras --no-install-project

COPY . .
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv sync --all-extras

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# The venv is built as root above (uv sync's own dependency-cache layering wants that); hand it to
# the non-root user the container actually runs as before the switch below.
RUN chown -R factory:factory /opt/venv
USER factory
# HOME is not this Dockerfile's literal to own -- docker-entrypoint.sh derives it at runtime from
# whichever user is actually running (`getent passwd`), robust to a uid change here without a
# second place to edit.

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["yosefactory-loop-scheduled", "--help"]
