"""Run-branch generator + parser. Spec §Run-branch suffix."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone


_BRANCH_PREFIX = "a2sdlc/auto"
_TS_FMT = "%Y%m%d-%H%M%S"
_HASH_LEN = 6
_RUN_BRANCH_RE = re.compile(
    r"^a2sdlc/auto/(?P<base_slug>[^/]+)/(?P<ts>\d{8}-\d{6})-(?P<input_hash>[0-9a-f]{6})$"
)


@dataclass(frozen=True)
class ParsedRunBranch:
    base_slug: str
    ts: datetime
    input_hash: str


def _slugify_base(base: str) -> str:
    return base.replace("/", "-")


def format_run_branch(base: str, ts: datetime, input_hash: str) -> str:
    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware (use UTC)")
    ts_utc = ts.astimezone(timezone.utc)
    return (
        f"{_BRANCH_PREFIX}/"
        f"{_slugify_base(base)}/"
        f"{ts_utc.strftime(_TS_FMT)}-{input_hash}"
    )


def parse_run_branch(branch: str) -> ParsedRunBranch | None:
    m = _RUN_BRANCH_RE.match(branch)
    if not m:
        return None
    ts = datetime.strptime(m["ts"], _TS_FMT).replace(tzinfo=timezone.utc)
    return ParsedRunBranch(
        base_slug=m["base_slug"],
        ts=ts,
        input_hash=m["input_hash"],
    )


def compute_input_hash(input_bytes: bytes) -> str:
    """SHA-256 of INPUT.md content, first 6 hex chars."""
    return hashlib.sha256(input_bytes).hexdigest()[:_HASH_LEN]
