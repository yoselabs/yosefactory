"""Durable, append-only record of real dollars spent against the pinned binary.

`executor.claude.run()`'s caller supplies `runs_dir`, and that directory is routinely a `tmp_path`
fixture pytest deletes at teardown, or a foreign workspace this platform does not own. A cost figure
written only there evaporates with it. This module writes it somewhere neither can reach: this
repository's own `ledger/`, resolved from this file's own location rather than from any
caller-supplied directory.

**Whose ledger this is.** Under cross-repo operation `run()` executes against a foreign workspace
(e.g. `a2web`) while this file resolves into yosefactory's own checkout regardless. That is
deliberate: spend belongs to the platform that paid for the call, not to the repository the call
happened to be working on.

**How that location is found.** `paths.repo_root` walks up from the package to the nearest
`pyproject.toml` or `.git`, the same way `protocol/backlog.py`'s `VOCABULARY_SPEC` does. Spend rows
are the one record that must not be lost, so the failure mode matters: installed apart from its own
source tree there is no `ledger/` to write to, and that raises at import instead of appending real
dollars into a directory nothing will ever read.

Every real invocation records here — test and production alike — because "what did today cost" does
not distinguish who paid for the call. Each row carries `run_id` so it joins to the matching record
in `ledger/runs/`: a spend row without that join is an orphan number, not evidence.

**`SPEND_LOG` is the default for a caller with no queue of its own** — a direct import, a REPL, this
package's own `make test-live` session, where the platform's own checkout is the only repository in
play and "resolved from this file's own location" and "the repository being worked" are the same
directory. `runtime.turn` and `runtime.loop`, which run turns against a real `Places`, do not use
this default: they pass `log_path=turn.spend_log_for(places)` explicitly, because under
`run-the-loop-inside-the-container`'s topology (and any other split-queue deployment) `places.queue`
is a different directory from wherever this package happens to be installed, and only `places.queue`
is a repository `turn.commit()` can stage a row into (see `spend_log_for`'s own docstring for why
that split makes `SPEND_LOG` the wrong default there, not merely an inconvenient one).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from yosefactory.paths import repo_root

SPEND_LOG = repo_root() / "ledger" / "spend.jsonl"


def record(total_cost_usd: float, *, run_id: str, log_path: Path = SPEND_LOG) -> None:
    """Append one row. Zero cost is a real value and still gets a row -- absence must not read as
    "this run never happened", the same principle `run-guardrails/turn-record` applies to `outcome`.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "total_cost_usd": total_cost_usd,
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def total_since(moment: datetime, log_path: Path = SPEND_LOG) -> float:
    """Sum of `total_cost_usd` for rows at or after `moment`. Answers "what did today cost" from the
    file's own contents alone -- no other module required to interpret it.
    """
    if not log_path.is_file():
        return 0.0
    total = 0.0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        ts = datetime.fromisoformat(row["ts"])
        if ts >= moment:
            total += float(row["total_cost_usd"])
    return total
