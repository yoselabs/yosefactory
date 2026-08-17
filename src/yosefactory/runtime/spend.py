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

**Second instance of a known limitation.** The `Path(__file__).resolve().parents[N]` walk is the same
pattern `protocol/backlog.py`'s `VOCABULARY_SPEC` already uses, and for the same reason: it assumes
this package runs from its own checkout, which is this repo's only deployment model today. It
resolves correctly in a dev checkout and breaks silently (writes into a nonexistent or wrong tree) if
yosefactory is ever installed apart from its own source tree. Not fixed here — there are now two call
sites with this limitation, so whoever addresses it should fix both rather than finding the second one
by surprise.

Every real invocation records here — test and production alike — because "what did today cost" does
not distinguish who paid for the call. Each row carries `run_id` so it joins to the matching record
in `ledger/runs/`: a spend row without that join is an orphan number, not evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

# Same depth-3 walk as `protocol/backlog.py::VOCABULARY_SPEC` — see the module docstring's
# "second instance" note.
SPEND_LOG = Path(__file__).resolve().parents[3] / "ledger" / "spend.jsonl"


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
