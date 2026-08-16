"""I9: a `done` transition is written only after an independent check confirms the claimed effect.

The independence here is *actor*-independence — the entity writing the transition is not the entity
that did the work. It is not foreign evidence: these checks inspect the same repository the agent
just edited. That distinction is kept explicit because the measurement motivating I9 (defects found
by internal checks 0, by foreign evidence 5) favours foreign evidence specifically, and a remote
check is strictly stronger. What actor-independence buys is the failure actually observed here — an
agent asserting an effect that does not exist — which is caught by looking, from any actor.

An exit code is never the verdict. Executors are documented to print in-run failures, missing
authentication included, as ordinary output while exiting zero.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from yosefactory.protocol.turn import CheckResult

DEFAULT_TEST_COMMAND: tuple[str, ...] = ("pytest", "-q")


class VerificationError(RuntimeError):
    """The gate could not be run at all, which is not the same as failing it."""


@dataclass(frozen=True, slots=True)
class Claim:
    """What a run says it did. Every field here is an assertion to be checked, never evidence."""

    run_id: str
    commit: str | None = None
    terminal_verdict: str | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    results: tuple[CheckResult, ...]

    def report(self) -> str:
        if self.passed:
            return "verified: " + ", ".join(f"{r.name} ok" for r in self.results)
        failures = [r for r in self.results if not r.passed]
        return "VERIFICATION FAILED: " + "; ".join(f"{r.name}: {r.detail}" for r in failures)


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(argv[0])
    if executable is None:
        raise VerificationError(f"{argv[0]!r} is not on PATH; the gate cannot run")
    return subprocess.run([executable, *argv[1:]], cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603


def tests_pass(repo: Path, command: tuple[str, ...] = DEFAULT_TEST_COMMAND) -> CheckResult:
    completed = _run(list(command), repo)
    if completed.returncode == 0:
        return CheckResult(name="tests", passed=True, detail="")
    tail = (completed.stdout or completed.stderr or "").strip().splitlines()[-1:] or ["no output"]
    return CheckResult(name="tests", passed=False, detail=f"{' '.join(command)} exited {completed.returncode}: {tail[0]}")


def commit_present(repo: Path, commit: str) -> CheckResult:
    completed = _run(["git", "cat-file", "-t", commit], repo)
    kind = completed.stdout.strip()
    if completed.returncode == 0 and kind == "commit":
        return CheckResult(name="commit", passed=True, detail="")
    return CheckResult(name="commit", passed=False, detail=f"claimed commit {commit} is not in the repository history")


def tree_clean(repo: Path) -> CheckResult:
    completed = _run(["git", "status", "--porcelain"], repo)
    if completed.returncode != 0:
        raise VerificationError(f"git status failed in {repo.name}: {completed.stderr.strip()}")
    dirt = [line for line in completed.stdout.splitlines() if line.strip()]
    if not dirt:
        return CheckResult(name="tree", passed=True, detail="")
    return CheckResult(name="tree", passed=False, detail=f"working tree has {len(dirt)} uncommitted change(s)")


def terminal_verdict_present(claim: Claim) -> CheckResult:
    if claim.terminal_verdict:
        return CheckResult(name="verdict", passed=True, detail="")
    return CheckResult(name="verdict", passed=False, detail="run produced no terminal structured verdict; exit status is not the verdict")


def gate(repo: Path, claim: Claim, *, test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND) -> GateResult:
    """Run every check independently, so the report names which one failed and what it saw."""
    results = [terminal_verdict_present(claim), tests_pass(repo, test_command), tree_clean(repo)]
    if claim.commit:
        results.append(commit_present(repo, claim.commit))
    return GateResult(passed=all(result.passed for result in results), results=tuple(results))


def may_write_done(repo: Path, claim: Claim, *, test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND) -> GateResult:
    """The only door to `done`. There is deliberately no path from a self-report to this answer."""
    return gate(repo, claim, test_command=test_command)
