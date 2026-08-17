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
# curl/ca-certificates: needed once, to fetch the uv and claude installers below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
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
    && ln -s /root/.local/bin/claude /usr/local/bin/claude
ENV PATH="/root/.local/bin:${PATH}"

# A bind-mounted repo owned by a different UID than the container process trips git's ownership
# check (`fatal: detected dubious ownership`) the first time any git command runs against it.
# Configured here rather than discovered later, once, for every path this image might be asked to
# operate on.
RUN git config --global --add safe.directory '*'

# The venv lives OUTSIDE /app on purpose (design.md D3): the dev compose file bind-mounts the
# source tree onto /app, which would otherwise shadow whatever `uv sync` builds here at image-build
# time, forcing a silent resync (or failure) on every `uv run` inside the running container.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# Dependency layers first, so an edit to source (which the dev compose mount handles live anyway)
# never invalidates the dependency-install layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-extras --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-extras

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["yosefactory-loop-scheduled", "--help"]
