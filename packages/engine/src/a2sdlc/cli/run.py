"""``a2sdlc run`` — universal verb that drives one workflow start-to-finish.

Implements the 11-step prelude from spec §CLI surface. Steps 1-6 are
exit-code-precise guards (env / lock / base / dirty / input / branch);
once they pass we hand off to :mod:`a2sdlc.cli.run_pipeline` which
creates the run branch, builds the :class:`RunContext`, and drives
``dispatch``.

Exit-code contract (single source of truth: spec §Failure modes):

* ``0`` — success
* ``1`` — internal/unhandled
* ``2`` — required env var missing
* ``3`` — lockfile already held
* ``4`` — protected base
* ``5`` — dirty working tree
* ``6`` — ``INPUT.md`` missing on base HEAD
* ``7`` — run branch already exists
* ``8`` — stage commit failure (run_pipeline)
* ``9`` — push failure (run_pipeline)
* ``10`` — ``max_review_cycles`` exceeded (run_pipeline)
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from a2sdlc.config_run import RunConfigError, load_run_config
from a2sdlc.runtime.branch import compute_input_hash, format_run_branch
from a2sdlc.runtime.dirty_tree import (
    BaseProtectedError,
    DirtyTreeError,
    ensure_base_not_protected,
    ensure_clean_tree,
)
from a2sdlc.runtime.env_check import (
    check_required_env,
    format_missing_message,
)
from a2sdlc.runtime.lockfile import LockfileBusy, acquire_lock


# Adapter id → REQUIRED_ENV. v1 has only the local ecosystem; the
# table stays small and explicit, matching spec §Composition where
# adapter wiring is config-driven, not magic. Future ecosystems add
# rows here without touching call sites.
_ADAPTER_ENV: dict[str, tuple[str, ...]] = {
    "local-file": (),
    "local": (),
    "local-noop": (),
    "github": ("GITHUB_TOKEN",),
}


def _resolve_base(base_override: str | None, repo: Path) -> str:
    if base_override:
        return base_override
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _read_input_md(base: str, repo: Path) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{base}:INPUT.md"],
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(
            f"INPUT.md not found on '{base}' HEAD. "
            "commit it on the base branch and try again."
        )
    return proc.stdout


def _branch_exists(branch: str, repo: Path) -> bool:
    local = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=repo,
        capture_output=True,
    )
    if local.returncode == 0:
        return True
    remote = subprocess.run(
        ["git", "ls-remote", "origin", branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    # ls-remote exits 0 even on no-match — non-empty stdout means the ref exists.
    return remote.returncode == 0 and bool(remote.stdout.strip())


def _required_env_for(config) -> list[tuple[str, list[str]]]:
    """Aggregate REQUIRED_ENV across config + the wired adapters."""
    reqs: list[tuple[str, list[str]]] = []
    if config.required_env:
        reqs.append(("engine", list(config.required_env)))
    for role in ("work", "review"):
        adapter_id = getattr(config.adapters, role)
        names = _ADAPTER_ENV.get(adapter_id, ())
        if names:
            reqs.append((f"adapter:{adapter_id}", list(names)))
    return reqs


def run_command(
    base: Annotated[
        str | None,
        typer.Option("--base", help="Override auto-detected base branch."),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Override config-file location (default .a2sdlc/config.yaml).",
        ),
    ] = None,
    label: Annotated[
        str | None,
        typer.Option("--label", help="Set ticket_key explicitly."),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option("--mode", help="Override ecosystem mode from config."),
    ] = None,
    allow_protected_base: Annotated[
        bool,
        typer.Option(
            "--allow-protected-base",
            help="Permit running on a protected base (e.g. main).",
        ),
    ] = False,
    project_root: Annotated[
        Path | None,
        typer.Option("--project-root", help="Path to repo root (defaults to cwd)."),
    ] = None,
) -> None:
    """Run one workflow attempt end-to-end (spec §CLI surface)."""
    repo = project_root or Path.cwd()
    cfg_path = config_path or (repo / ".a2sdlc" / "config.yaml")

    # ── Step 1: Validate environment first. ──────────────────────────
    try:
        config = load_run_config(cfg_path)
    except RunConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(code=1) from exc

    if mode is not None:
        # Mode override — pydantic validates the literal at assignment.
        config = config.model_copy(update={"mode": mode})  # type: ignore[arg-type]

    reqs = _required_env_for(config)
    missing = check_required_env(reqs)
    if missing:
        print(format_missing_message(missing), file=sys.stderr)
        raise typer.Exit(code=2)

    # ── Step 2: Acquire VM lockfile. ─────────────────────────────────
    lock_path = repo / ".a2sdlc" / "run.lock"
    try:
        lock_cm = acquire_lock(lock_path)
        lock_cm.__enter__()
    except LockfileBusy as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(code=3) from exc

    # The lockfile context-manager owns cleanup; we hold a reference
    # and exit it once the run finishes (or fails). try/finally below.
    try:
        # ── Step 3: Resolve base + protected-base guard. ─────────────
        try:
            resolved_base = _resolve_base(base, repo)
        except subprocess.CalledProcessError as exc:
            print(
                f"error: failed to read current branch: {exc.stderr or exc}",
                file=sys.stderr,
            )
            raise typer.Exit(code=1) from exc

        try:
            ensure_base_not_protected(
                resolved_base,
                protected=set(config.pipeline.protected_bases),
                allow=allow_protected_base,
            )
        except BaseProtectedError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise typer.Exit(code=4) from exc

        # ── Step 4: Reject dirty working tree. ───────────────────────
        try:
            ensure_clean_tree(repo)
        except DirtyTreeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise typer.Exit(code=5) from exc

        # ── Step 5: Read INPUT.md from base HEAD. ────────────────────
        try:
            input_md = _read_input_md(resolved_base, repo)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise typer.Exit(code=6) from exc

        # ── Step 6: Generate run-branch name and refuse if it exists. ─
        run_branch = format_run_branch(
            resolved_base,
            datetime.now(timezone.utc),
            compute_input_hash(input_md),
        )
        if _branch_exists(run_branch, repo):
            print(
                f"error: branch '{run_branch}' already exists "
                "(local or origin). a duplicate run with the same "
                "INPUT.md within the same second is unsupported.",
                file=sys.stderr,
            )
            raise typer.Exit(code=7)

        # ── Steps 7-10: hand off to the pipeline driver. ─────────────
        from a2sdlc.cli.run_pipeline import drive_pipeline  # noqa: PLC0415

        drive_pipeline(
            repo=repo,
            config=config,
            base=resolved_base,
            input_md=input_md,
            run_branch=run_branch,
            label=label,
        )
    finally:
        # ── Step 11: Always release the lockfile. ────────────────────
        try:
            lock_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 — cleanup must never mask errors
            pass


def main(argv: list[str] | None = None) -> None:
    """Standalone entry — used when invoking ``a2sdlc.cli.run`` directly."""
    app = typer.Typer(add_completion=False)
    app.command()(run_command)
    app(args=argv, prog_name="a2sdlc run", standalone_mode=True)


__all__ = ["main", "run_command"]
