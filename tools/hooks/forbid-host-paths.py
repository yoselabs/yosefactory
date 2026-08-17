#!/usr/bin/env python3
"""Guard: refuse a commit that publishes an absolute host path.

This repository is public. `openspec/changes/archive/2026-08-17-wire-the-board-into-the-turn-cycle`
committed two raw agent transcripts (`ledger/runs/*.stream.jsonl`) that carried 53 occurrences of
the operator's home directory before anyone noticed, because the transcript is the executor's raw
stdout — it never passes through `protocol.turn.TurnRecord`, the one place this repo already
refuses a home-rooted path (`_HOME_ROOTED`, `protocol/turn.py`). This guard is the same idea moved
to the git boundary, so it catches an absolute host path in *any* staged file, not only a
`TurnRecord`.

**Two independent checks, either one enough to refuse:**

1. **Path-based.** No staged path may match `ledger/runs/*.stream.jsonl`. The raw transcript is
   never committed at all (see the accompanying `.gitignore` entry and this guard's own change,
   `stop-publishing-host-paths`, Decision 1) — this is the belt to that gitignore's suspenders,
   for a `git add -f` that bypasses it.
2. **Content-based.** No staged file's *text* content may contain a literal path rooted at
   `/Users/`, `/home/`, or `/root` — the same pattern `protocol/turn.py::_HOME_ROOTED` already
   enforces for turn records, applied here to everything, checked line by line. A line ending in
   the literal marker ``hostpath-allow`` is exempt — the sanctioned way to write a pattern example
   (this script's own `_HOME_ROOTED` line, its tests' fixture strings, a design doc naming the
   syntax) without either tripping the guard on itself or silently blessing every line in the file.
   The marker is per-line and has to be typed deliberately; it is not a path allowlist.

**What this does NOT catch, stated so a later reader does not assume otherwise:**

- Tilde-shorthand paths (`~/Documents/...`). No username in a tilde path, but a private repo or
  project name after it still publishes something real. Enumerating those names in this script
  would put them in the one place this guard exists to keep them out of — the public repo — so the
  primary defense for that class is check 1 above (never commit the transcript), not this scan.
- Windows-style paths (``C:\\Users\\...``) — single-operator macOS machine, out of scope by D005.
- Binary files — best-effort text decode; anything that doesn't decode as UTF-8 is skipped.
- History already committed before this guard existed — see the accompanying change's history
  rewrite for that.
- In ``--committed`` mode, anything outside the *last* commit's own diff. A full-tree scan of
  everything ever committed would also flag this script's own `_HOME_ROOTED` pattern, the
  Dockerfile's `/root/.local/bin`, and the test fixtures below — places this repo legitimately
  *talks about* a host path — with no way to tell those from a real leak short of an allowlist
  this guard deliberately does not carry. See `_committed_paths` for the full argument.

Two modes, same shape as `forbid-local-shelf-source.py` in the shelf:

``--staged`` (default) reads the index — what is about to be committed. The pre-commit hook's
question.

``--committed`` reads the tip commit's own diff against `HEAD`'s parent. `make guard`'s question,
because a hook is per-clone and can be silently disabled — this is the check that still runs even
if `--no-verify` skipped the hook, so long as something re-runs `make guard` after the commit
lands (see this change's tasks.md for how that's wired here).

Exit codes: ``0`` clean · ``1`` offenders found · ``2`` could not check (not a git repository).
A check that cannot run is never reported as a pass.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys

COULD_NOT_CHECK = 2

# Mirrors protocol/turn.py::_HOME_ROOTED. Kept as a separate literal, not an import, because this
# script runs standalone (system python, no project venv guaranteed) — see forbid-local-shelf-
# source.py in the shelf for the same tradeoff. If one changes, check the other.
_HOME_ROOTED = re.compile(r"(?:^|[\s\"'=(,:])(/Users/|/home/|/root(?:/|\b))")  # hostpath-allow: the pattern itself

_FORBIDDEN_PATH_GLOB = "ledger/runs/*.stream.jsonl"

# Per-line escape hatch for a genuine pattern example (this file's own regex, a test fixture, a
# design doc naming the syntax) -- see module docstring, check 2. Deliberately per-line, not
# per-file: a file earns the exemption one line at a time, so an unrelated real leak added later in
# the same file is still caught.
_ALLOW_MARKER = "hostpath-allow"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607


def _staged_paths() -> list[str]:
    result = _git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [line for line in result.stdout.splitlines() if line]


def _committed_paths() -> list[str]:
    """Paths touched by the commit at HEAD -- deliberately the last commit's diff, not a full-tree
    audit of everything ever committed. A full-tree scan would also flag every place this repo
    legitimately *talks about* a host path (this script's own `_HOME_ROOTED` pattern, the
    Dockerfile's `/root/.local/bin`, the parametrized test fixtures below) with no way to tell
    those apart from a real leak short of an allowlist this guard deliberately does not carry. The
    guard this change adds is for the failure named in its own proposal -- *a future change
    commits* a host path -- not a historical audit; the two already-known pre-existing leaks are
    handled once, by hand, in this same change (design.md, history rewrite)."""
    if _git("rev-parse", "HEAD").returncode != 0:
        return []
    result = _git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "--diff-filter=ACM", "HEAD")
    return [line for line in result.stdout.splitlines() if line]


def _content(path: str, *, committed: bool) -> str | None:
    """The file's text content as it would be committed (staged) or as it is at HEAD.

    None means "nothing to scan" -- either the read failed (path gone from the ref) or the blob
    is not valid UTF-8 text (a binary file), per the module docstring's stated limitation.
    """
    ref = f"HEAD:{path}" if committed else f":{path}"
    result = subprocess.run(["git", "show", ref], capture_output=True, text=False, check=False)  # noqa: S603, S607
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _path_offenders(paths: list[str]) -> list[str]:
    return [path for path in paths if fnmatch.fnmatch(path, _FORBIDDEN_PATH_GLOB)]


def _leaks(content: str) -> bool:
    """True if some line matches _HOME_ROOTED and is not marked `hostpath-allow`."""
    return any(_HOME_ROOTED.search(line) for line in content.splitlines() if _ALLOW_MARKER not in line)


def _content_offenders(paths: list[str], *, committed: bool) -> list[str]:
    offenders = []
    for path in paths:
        content = _content(path, committed=committed)
        if content is not None and _leaks(content):
            offenders.append(path)
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="check the index (default; the hook's question)")
    mode.add_argument("--committed", action="store_true", help="check HEAD (the gate's question)")
    args = parser.parse_args(argv)

    if _git("rev-parse", "--git-dir").returncode != 0:
        print("✖ cannot check for a published host path: not a git repository.", file=sys.stderr)
        print("  This is NOT a pass — the guard could not run at all.", file=sys.stderr)
        return COULD_NOT_CHECK

    committed = args.committed
    paths = _committed_paths() if committed else _staged_paths()
    if not paths:
        return 0

    path_offenders = _path_offenders(paths)
    content_offenders = _content_offenders(paths, committed=committed)

    if not path_offenders and not content_offenders:
        return 0

    where = "HEAD carries" if committed else "refusing to commit"
    if path_offenders:
        print(f"✖ {where} a raw agent transcript ({_FORBIDDEN_PATH_GLOB} is never committed):", file=sys.stderr)
        for path in path_offenders:
            print(f"    {path}", file=sys.stderr)
    if content_offenders:
        msg = f"✖ {where} a file containing an absolute host path (/Users/, /home/, or /root):"  # hostpath-allow
        print(msg, file=sys.stderr)
        for path in content_offenders:
            print(f"    {path}", file=sys.stderr)
    if committed:
        print("  This repository is public — a committed host path stays public once pushed.", file=sys.stderr)
        print("  Rewrite the offending commit(s) before pushing.", file=sys.stderr)
    else:
        print("  This repository is public. Remove the path or gitignore the file before committing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
