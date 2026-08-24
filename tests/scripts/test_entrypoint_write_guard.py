"""`docker-entrypoint.sh`'s write-guard check -- refuses to start a turn if the source root is
writable ([[S245]]: a writable `/app` mount let an unattended turn commit into the platform's own
repository). Drives the real shipped script via subprocess, exactly the pattern
`test_forbid_host_paths.py` uses for `forbid-host-paths.py`, with `YF_SOURCE_ROOT` overridden to a
scratch directory so no real container or Docker bind mount is needed.

The script's own `HOME` derivation shells out to `getent`, which is Linux-only and does not exist
on a macOS dev host; a fake `getent` is put on `PATH` so this test is portable rather than
Linux-only, without touching the script itself.

What this proves: the guard logic itself, against the real script. What it does NOT prove: that
`docker-compose.yml`'s `:ro` flag makes a real Docker bind mount read-only, or that `make check`
passes inside a real container -- see design.md's Verification section for what a human runs to
check those."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "docker-entrypoint.sh"

_FAKE_GETENT = """#!/bin/sh
# Minimal stand-in for Linux's getent, just enough for
# `getent passwd "$(id -u)" | cut -d: -f6` to resolve a HOME.
echo "fakeuser:x:$2:$2:fake:/tmp:/bin/sh"
"""


@pytest.fixture
def fake_path(tmp_path: Path) -> str:
    """PATH with a fake `getent` ahead of the real one, so the script's HOME derivation resolves
    on any host, then falls through to the real PATH for everything else (bash, cut, ...)."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    getent = bin_dir / "getent"
    getent.write_text(_FAKE_GETENT)
    getent.chmod(0o755)
    # Deliberately excludes the real PATH: this repo's own venv installs `yosefactory-loop` /
    # `yosefactory-loop-scheduled` as real scripts, and if they were reachable here the
    # "guard passed" tests below would actually run the real loop instead of proving the guard
    # let a not-found command through.
    return f"{bin_dir}:/usr/bin:/bin"


def _run(
    source_root: Path, fake_path: str, *command: str, token: str | None = "x"  # noqa: S107
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": fake_path, "YF_SOURCE_ROOT": str(source_root)}
    if token is not None:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return subprocess.run(  # noqa: S603
        ["bash", str(_SCRIPT), *command],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def writable_root(tmp_path: Path) -> Path:
    root = tmp_path / "writable"
    root.mkdir()
    return root


@pytest.fixture
def readonly_root(tmp_path: Path) -> Path:
    root = tmp_path / "readonly"
    root.mkdir()
    root.chmod(stat.S_IRUSR | stat.S_IXUSR)
    yield root
    root.chmod(stat.S_IRWXU)  # restore so tmp_path cleanup can remove it


@pytest.mark.parametrize("command", ["yosefactory-loop", "yosefactory-loop-scheduled"])
def test_writable_source_root_refuses_to_start(
    writable_root: Path, fake_path: str, command: str
) -> None:
    result = _run(writable_root, fake_path, command, "--help")

    assert result.returncode == 1
    assert str(writable_root) in result.stderr
    assert "writable" in result.stderr


@pytest.mark.parametrize("command", ["yosefactory-loop", "yosefactory-loop-scheduled"])
def test_readonly_source_root_passes_the_guard(
    readonly_root: Path, fake_path: str, command: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores the read-only permission bit; guard cannot be exercised as root")

    result = _run(readonly_root, fake_path, command, "--help")

    # Passes the write-guard (no "writable" refusal). It still fails, because `command` itself is
    # not on the fake PATH -- that failure is `exec`'s, not the guard's, and proves the guard let
    # it through rather than that the real loop entrypoint ran.
    assert "writable" not in result.stderr
    assert result.returncode != 0


def test_readonly_source_root_still_enforces_missing_token(
    readonly_root: Path, fake_path: str
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores the read-only permission bit; guard cannot be exercised as root")

    result = _run(readonly_root, fake_path, "yosefactory-loop-scheduled", "--help", token=None)

    assert result.returncode == 1
    assert "CLAUDE_CODE_OAUTH_TOKEN" in result.stderr
    assert "writable" not in result.stderr


def test_diagnostic_command_is_unaffected_by_a_writable_source_root(
    writable_root: Path, fake_path: str
) -> None:
    result = _run(writable_root, fake_path, "echo", "hi", token=None)

    assert result.returncode == 0
    assert result.stdout.strip() == "hi"
    assert "writable" not in result.stderr
