"""I9. The acceptance test for the whole change lives here: a run that claims work it did not do fails."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yosefactory.runtime.verify import Claim, may_write_done, tree_clean
from yosefactory.runtime.verify import tests_pass as run_test_check

TRUE_COMMAND = ("true",)
FALSE_COMMAND = ("false",)


def git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_a_run_claiming_a_commit_that_does_not_exist_fails(repo: Path) -> None:
    """The acceptance test. A branch that was never a commit is exactly the failure I9 was written for."""
    claim = Claim(run_id="r1", commit="0" * 40, terminal_verdict="advanced")

    result = may_write_done(repo, claim, test_command=TRUE_COMMAND)

    assert not result.passed
    assert "not in the repository history" in result.report()


def test_a_claimed_commit_that_exists_passes(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    result = may_write_done(repo, Claim(run_id="r1", commit=head, terminal_verdict="advanced"), test_command=TRUE_COMMAND)
    assert result.passed, result.report()


def test_a_dirty_tree_fails(repo: Path) -> None:
    (repo / "b.txt").write_text("uncommitted\n", encoding="utf-8")

    result = may_write_done(repo, Claim(run_id="r1", terminal_verdict="advanced"), test_command=TRUE_COMMAND)

    assert not result.passed
    assert "uncommitted" in result.report()


def test_a_failing_test_suite_fails(repo: Path) -> None:
    result = may_write_done(repo, Claim(run_id="r1", terminal_verdict="advanced"), test_command=FALSE_COMMAND)

    assert not result.passed
    assert "tests" in result.report()


def test_no_terminal_verdict_fails_even_when_everything_else_is_green(repo: Path) -> None:
    result = may_write_done(repo, Claim(run_id="r1", terminal_verdict=None), test_command=TRUE_COMMAND)

    assert not result.passed
    assert "exit status is not the verdict" in result.report()


def test_the_report_names_which_check_failed(repo: Path) -> None:
    (repo / "b.txt").write_text("x\n", encoding="utf-8")

    report = may_write_done(repo, Claim(run_id="r1", terminal_verdict="advanced"), test_command=FALSE_COMMAND).report()

    assert "tests:" in report
    assert "tree:" in report


def test_each_check_is_evaluated_independently(repo: Path) -> None:
    assert tree_clean(repo).passed
    assert run_test_check(repo, TRUE_COMMAND).passed
    assert not run_test_check(repo, FALSE_COMMAND).passed


def test_there_is_no_path_from_a_self_report_to_done(repo: Path) -> None:
    """A claim is an assertion, not evidence: a maximally confident claim on a broken repo still fails."""
    (repo / "b.txt").write_text("x\n", encoding="utf-8")
    confident = Claim(run_id="r1", commit=git(repo, "rev-parse", "HEAD"), terminal_verdict="advanced")

    assert not may_write_done(repo, confident, test_command=TRUE_COMMAND).passed
