"""``a2sdlc run`` orchestration — the post-prelude part.

This module owns steps 7-11 from spec §CLI surface: create the run
branch, build a :class:`RunContext`, drive ``dispatch``, handle
commit+push per stage, and emit the final stdout (``done. / branch:
<run-branch>``) on success.

**Task 18 status — what is wired and what is stubbed.** The prelude
(:mod:`a2sdlc.cli.run`) is the scope-locked deliverable for Task 18.
This driver intentionally lands as a *minimum-viable* stub that:

* creates and checks out the run branch off ``base``;
* builds a thin :class:`RunContext` and invokes
  :func:`a2sdlc.pipeline.dispatch.dispatch`;
* prints ``done.\\nbranch: <run-branch>`` on success and returns;
* on any unhandled exception, prints the spec's "internal failure"
  message and re-raises a :class:`typer.Exit` with code 1 — the
  prelude's lockfile-release ``finally`` still runs.

The full handover loop (commit per stage, push, ``max_review_cycles``
breaker, exit codes 8 / 9 / 10) is exercised by the smoke harness in
**Task 19**. That harness drives a real run end-to-end and is allowed
to extend this driver as needed; until then the wiring here is the
smallest surface that lets the prelude's exit-code contract be
asserted under integration tests.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

import typer

from a2sdlc.config_run import RunConfig


def _checkout_run_branch(repo: Path, base: str, run_branch: str) -> None:
    """Create the run branch off ``base`` and switch to it."""
    subprocess.run(
        ["git", "checkout", "-b", run_branch, base],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def drive_pipeline(  # pragma: no cover - exercised end-to-end by Task 19 smoke harness
    *,
    repo: Path,
    config: RunConfig,
    base: str,
    input_md: bytes,  # noqa: ARG001 — surfaced for the smoke harness
    run_branch: str,
    label: str | None,  # noqa: ARG001 — surfaced for the smoke harness
) -> None:
    """Run the workflow on the freshly-prepared run branch.

    Stubbed for Task 18; finished out by Task 19's smoke harness. See
    the module docstring for the deliberate-scope rationale.
    """
    logger = logging.getLogger("a2sdlc.cli.run")

    try:
        _checkout_run_branch(repo, base, run_branch)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"error: failed to create run branch '{run_branch}': {exc.stderr or exc}\n"
        )
        raise typer.Exit(code=1) from exc

    # Minimal RunContext wiring. The full composition root lives in
    # ``cli/dispatch.py`` for the GH path; here we mirror the shape as
    # narrowly as possible. Adapter handles default to ``None`` — the
    # smoke harness (Task 19) wires real adapters before this driver
    # actually executes a stage.
    from a2sdlc.config import load_config_file  # noqa: PLC0415
    from a2sdlc.domain.run_context import RunContext  # noqa: PLC0415
    from a2sdlc.observability.wire import build_progress_state  # noqa: PLC0415
    from a2sdlc.pipeline.dispatch import dispatch  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    project_config = load_config_file(repo)
    progress_state = build_progress_state(
        repo,
        project_config.adapters.progress,
        with_mlflow_trace=False,
    )

    ctx = RunContext(
        work=None,
        git=None,
        review=None,
        runner=SdkStageRunner(effort=project_config.effort),
        progress_state=progress_state,
        config=project_config,
        project_root=repo,
        logger=logger,
        run_id=run_branch,
    )

    try:
        asyncio.run(dispatch(ctx))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"error: internal failure: {type(exc).__name__}: {exc}\n"
            f"lockfile released; partial state on local branch "
            f"'{run_branch}'.\n"
        )
        raise typer.Exit(code=1) from exc

    sys.stdout.write(f"done.\nbranch: {run_branch}\n")


__all__ = ["drive_pipeline"]
