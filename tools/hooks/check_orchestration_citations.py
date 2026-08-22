#!/usr/bin/env python3
"""Drift checker: every `orchestration.md` article id cited in `AGENTS.md` still exists there.

`AGENTS.md` states, in this repo's own words, the parts of K project 160's fleet constitution
(`orchestration.md`, seventeen articles, in a *private* repo this one does not and must not copy
from — see `openspec/changes/write-down-the-operating-model/`) that are a worker's mechanics in
this repo. Each such rule cites the article id it is drawn from, so a reader can go verify it.

This script is the other direction: it checks that the *citation* still resolves, not that the
prose still agrees with K's — an article can be renumbered or retired-by-number-reuse, and nothing
in this repo would notice without this running. It does NOT verify content; a human reviews that
when either side changes, deliberately, because copying K's prose into a public repo on every run
is the leak machine this design explicitly rejected.

**Degrades cleanly when K is absent.** A clone of this repo on another machine, or in CI, has no
`~/Documents/Knowledge` at all — that is the normal case, not an error. This script SKIPS (exit 0)
rather than fails when the K checkout is not found, and says so on stdout.

Exit codes: ``0`` clean or skipped (K absent) · ``1`` a cited article id no longer exists in K.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"

# Default location this repo's own docs already assume (CLAUDE.md's P160 pointer). Overridable so
# a machine with K checked out somewhere else can still run this for real rather than always
# skipping.
DEFAULT_K_ORCHESTRATION = (
    pathlib.Path.home() / "Documents/Knowledge/Projects/160-ai-factory/orchestration.md"
)

# Matches "orchestration.md Article <roman-numeral>" as written in AGENTS.md's citations.
_CITATION_RE = re.compile(r"orchestration\.md`?\s+Article\s+([IVXLC]+)\b")

# Matches K's own article headers, e.g. "**I. A worker never asks..." / "**XIII. — RETIRED, ...".
# Retired articles keep their numeral on purpose (orchestration.md says so explicitly) and this
# regex finds them too -- a citation to a retired-but-still-numbered article is not drift.
_ARTICLE_HEADER_RE = re.compile(r"^\*\*([IVXLC]+)\.", re.MULTILINE)


def _cited_ids(text: str) -> set[str]:
    return set(_CITATION_RE.findall(text))


def _present_ids(text: str) -> set[str]:
    return set(_ARTICLE_HEADER_RE.findall(text))


def main() -> int:
    k_path = DEFAULT_K_ORCHESTRATION
    if not k_path.is_file():
        print(
            f"check_orchestration_citations: SKIP -- K checkout not found at {k_path} "
            "(expected on a clone or in CI; not an error)."
        )
        return 0

    if not AGENTS_MD.is_file():
        print(f"check_orchestration_citations: FAIL -- {AGENTS_MD} not found.", file=sys.stderr)
        return 1

    cited = _cited_ids(AGENTS_MD.read_text(encoding="utf-8"))
    if not cited:
        print("check_orchestration_citations: no orchestration.md citations found in AGENTS.md.")
        return 0

    present = _present_ids(k_path.read_text(encoding="utf-8"))
    missing = sorted(cited - present, key=lambda s: (len(s), s))

    if missing:
        print(
            "check_orchestration_citations: FAIL -- AGENTS.md cites orchestration.md Article "
            f"{', '.join(missing)}, which no longer exists at {k_path}. "
            "Renumbered or removed -- update the citation in AGENTS.md.",
            file=sys.stderr,
        )
        return 1

    print(
        f"check_orchestration_citations: OK -- {len(cited)} cited article id(s) "
        f"({', '.join(sorted(cited))}) all present in {k_path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
