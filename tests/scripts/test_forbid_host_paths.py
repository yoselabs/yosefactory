"""`tools/hooks/forbid-host-paths.py` against a real scratch git repo — the script drives real
`git` subprocesses (index reads, `HEAD` reads), so a fake filesystem would test nothing the real
hook does. See the script's own docstring for what it does and does not catch."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "hooks" / "forbid-host-paths.py"

# Scratch-repo fixture data, not this repo's own content -- see the strings' own use below.
_LEAKS = ["/Users/someone/Workspaces/x", "wrote /home/op/.claude", "/root/.codex"]  # hostpath-allow


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    return tmp_path


def test_not_a_git_repo_is_could_not_check(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 2


def test_nothing_staged_passes(repo: Path) -> None:
    result = _run(repo)
    assert result.returncode == 0


def test_a_clean_staged_file_passes(repo: Path) -> None:
    (repo / "notes.md").write_text("a relative path: ledger/runs/x.json\n")
    _git(repo, "add", "notes.md")
    result = _run(repo)
    assert result.returncode == 0


@pytest.mark.parametrize("leak", _LEAKS)
def test_a_staged_home_rooted_path_is_refused(repo: Path, leak: str) -> None:
    (repo / "notes.md").write_text(f"{leak}\n")
    _git(repo, "add", "notes.md")
    result = _run(repo)
    assert result.returncode == 1
    assert "notes.md" in result.stderr


def test_a_marked_line_is_exempt(repo: Path) -> None:
    (repo / "notes.md").write_text("/Users/someone/x  # hostpath-allow: pattern example\n")
    _git(repo, "add", "notes.md")
    result = _run(repo)
    assert result.returncode == 0


def test_the_marker_does_not_exempt_other_lines_in_the_same_file(repo: Path) -> None:
    (repo / "notes.md").write_text("/Users/someone/x  # hostpath-allow: pattern example\n/root/.codex\n")
    _git(repo, "add", "notes.md")
    result = _run(repo)
    assert result.returncode == 1
    assert "notes.md" in result.stderr


def test_a_relative_users_path_is_fine(repo: Path) -> None:
    # No leading slash -- not the pattern this guard exists to catch (see script docstring).
    (repo / "notes.md").write_text("see Users/x for the fixture\n")
    _git(repo, "add", "notes.md")
    result = _run(repo)
    assert result.returncode == 0


def test_a_staged_stream_transcript_path_is_refused_even_with_clean_content(repo: Path) -> None:
    run_dir = repo / "ledger" / "runs"
    run_dir.mkdir(parents=True)
    (run_dir / "turn-x.stream.jsonl").write_text('{"type": "system"}\n')
    _git(repo, "add", "-f", "ledger/runs/turn-x.stream.jsonl")
    result = _run(repo)
    assert result.returncode == 1
    assert "ledger/runs/turn-x.stream.jsonl" in result.stderr


def test_committed_mode_reads_head_not_the_index(repo: Path) -> None:
    (repo / "notes.md").write_text("/Users/someone/x\n")  # hostpath-allow: fixture data for a scratch repo
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-q", "-m", "add notes")

    # Nothing staged now (the commit cleared the index) -- --staged sees a clean tree.
    assert _run(repo, "--staged").returncode == 0
    # --committed reads HEAD, where the offending commit already landed.
    result = _run(repo, "--committed")
    assert result.returncode == 1
    assert "notes.md" in result.stderr


def test_committed_mode_on_a_repo_with_no_commits_yet_is_clean(repo: Path) -> None:
    result = _run(repo, "--committed")
    assert result.returncode == 0


def test_a_non_utf8_file_is_skipped_not_crashed(repo: Path) -> None:
    (repo / "blob.bin").write_bytes(b"\xff\xfe\x00\x01/Users/should-not-decode")
    _git(repo, "add", "blob.bin")
    result = _run(repo)
    assert result.returncode == 0
    assert result.stderr == ""
