"""Session-wide test plumbing.

The one hook here answers Article XVI's receipt question for `live`-marked tests: after a
`make test-live` run, the session prints what it actually spent, summed from `ledger/spend.jsonl`
(`runtime.spend`) rather than from any test's own assertion -- the subject is the durable file, not
that a recorder function ran.
"""

from __future__ import annotations

from datetime import UTC, datetime

from yosefactory.runtime import spend

_session_start: datetime | None = None


def pytest_sessionstart(session) -> None:
    global _session_start
    _session_start = datetime.now(UTC)


def pytest_sessionfinish(session, exitstatus) -> None:
    if _session_start is None:
        return
    total = spend.total_since(_session_start)
    if total > 0:
        print(f"\nlive spend this session: ${total:.4f} (see ledger/spend.jsonl)")  # noqa: T201
