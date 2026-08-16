"""The turn-record stream: one file per record, and a marker that makes a missing record detectable.

A missing record is only detectable if something knew a record was expected. The supervisor writing
on termination covers the ordinary kill; it does not cover the supervisor's own death, which is the
most complete failure available and would otherwise leave the least evidence. So a run opens with a
marker and the terminal record supersedes it. An orphan marker is the gap.

One file per record rather than one appended file: several sessions share this working tree, and a
single appended file is a merge-conflict generator and a lost-update risk. Append-only is a property
of the directory — files are created, never rewritten.

This stream is not `ledger/*.toml`. Those rows are hand-authored, predate the outcome enum, and are
out of scope by construction rather than by a branch in this reader.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from yosefactory.protocol.turn import Outcome, RecordError, TurnRecord, from_dict

STREAM_DIRNAME = "runs"

_STAMP = "%Y%m%dT%H%M%SZ"
_NAME = re.compile(r"^(?P<stamp>\d{8}T\d{6}Z)-(?P<run_id>[A-Za-z0-9_-]+)$")


class StreamError(RuntimeError):
    """The stream refused a write."""


@dataclass(frozen=True, slots=True)
class Position:
    """One position in the window: either a record, or a gap where a record was expected.

    A gap is `failed`. It is never skipped and never narrows the window — a run whose outcome nobody
    knows is not the same as a run that did not happen, and treating it as no-data is how a broken
    factory reports success.
    """

    slug: str
    record: TurnRecord | None

    @property
    def is_gap(self) -> bool:
        return self.record is None

    @property
    def outcome(self) -> Outcome:
        return Outcome.FAILED if self.record is None else self.record.outcome


def utc_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime(_STAMP)


def slug_for(run_id: str, started: datetime | None = None) -> str:
    if not _NAME.match(f"{utc_stamp(started)}-{run_id}"):
        raise StreamError(f"run_id {run_id!r} must be alphanumeric with - or _ only")
    return f"{utc_stamp(started)}-{run_id}"


def open_run(runs_dir: Path, run_id: str, started: datetime | None = None) -> str:
    """Declare that a record is expected. Returns the slug both files are named for."""
    started = started or datetime.now(UTC)
    slug = slug_for(run_id, started)
    runs_dir.mkdir(parents=True, exist_ok=True)
    marker = runs_dir / f"{slug}.start"
    if marker.exists():
        raise StreamError(f"a run is already open at {marker.name}")
    marker.write_text(json.dumps({"run_id": run_id, "started_at": started.isoformat()}, indent=2) + "\n", encoding="utf-8")
    return slug


def append(runs_dir: Path, slug: str, record: TurnRecord) -> Path:
    """Write the terminal record. Never overwrites — this stream is append-only (D002)."""
    if not _NAME.match(slug):
        raise StreamError(f"malformed slug {slug!r}")
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{slug}.json"
    if path.exists():
        raise StreamError(f"{path.name} already exists; records are never rewritten")
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def read_window(runs_dir: Path, size: int) -> list[Position]:
    """The most recent `size` positions, oldest first. Orphan markers included as gaps."""
    if size < 1:
        raise StreamError("window size must be at least 1")
    if not runs_dir.is_dir():
        return []
    slugs: set[str] = set()
    for path in runs_dir.iterdir():
        if path.suffix in {".json", ".start"} and _NAME.match(path.stem):
            slugs.add(path.stem)
    positions: list[Position] = []
    for slug in sorted(slugs):
        payload_path = runs_dir / f"{slug}.json"
        if not payload_path.exists():
            positions.append(Position(slug=slug, record=None))
            continue
        try:
            record = from_dict(json.loads(payload_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, RecordError) as exc:
            raise StreamError(f"{payload_path.name} is not a readable turn record: {exc}") from exc
        positions.append(Position(slug=slug, record=record))
    return positions[-size:]
