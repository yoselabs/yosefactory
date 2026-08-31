"""The milestone-comment renderer: one pure read of a finished stream plus an item's own log.

No `gh`, no network -- `trace_comment.render()` only ever opens local files. Fixtures build a
minimal item log with `protocol.backlog.load` (the same reader the real platform uses) and a
`*.stream.jsonl` with the same event shapes `tests/executor/test_trace.py` already measured.
"""

from __future__ import annotations

import json
from pathlib import Path

from yosefactory.board import trace_comment
from yosefactory.protocol import backlog
from yosefactory.protocol.eventlog import FoldedLog

READ_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:03.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "src/x.py"}}]},
}
BASH_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:11.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "make check"}}]},
}
BASH_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T00:00:20.000Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "3 failed"}]},
    "tool_use_result": {"stdout": "3 failed", "stderr": ""},
}
INIT_EVENT = {
    "type": "system",
    "subtype": "init",
    "model": "claude-sonnet-5",
    "memory_paths": [],
    "mcp_servers": [],
    "skills": [],
    "plugins": [],
    "permissionMode": "manual",
}
TURN_EVENT = {"type": "system", "subtype": "post_turn_summary"}
RESULT_EVENT = {
    "type": "result",
    "duration_ms": 301000,
    "subtype": "success",
    "is_error": False,
    "num_turns": 12,
    "total_cost_usd": 0.42,
    "usage": {"input_tokens": 85_000, "output_tokens": 23_000},
}


def _write_stream(path: Path, events: list[dict]) -> Path:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    return path


def _write_item(path: Path, records: list[dict]) -> FoldedLog:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return backlog.load(path)


def _created(event_id: str = "e0") -> dict:
    return {
        "event_id": event_id,
        "ts": "2026-08-31T00:00:00+00:00",
        "actor": "board",
        "event": "created",
        "loop": "board-intake",
        "frame": {"goal": "render a trace", "method": "…", "assumptions": []},
    }


def _claimed(attempt: int, ts: str, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "ts": ts,
        "actor": "ci",
        "event": "claimed",
        "owner": "ci",
        "expires_at": "2026-08-31T01:00:00+00:00",
        "attempt": attempt,
    }


def _started(ts: str, event_id: str) -> dict:
    return {"event_id": event_id, "ts": ts, "actor": "ci", "event": "started"}


def _gate_rejected(attempt: int, report: str, ts: str, event_id: str) -> dict:
    return {"event_id": event_id, "ts": ts, "actor": "ci", "event": "gate_rejected", "attempt": attempt, "report": report}


def _reclaimed(ts: str, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "ts": ts,
        "actor": "sweeper",
        "event": "reclaimed",
        "reason": "lease expired",
        "expired_owner": "ci",
        "expired_attempt": 1,
    }


def _done(ts: str, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "ts": ts,
        "actor": "ci",
        "event": "done",
        "effects": ["src/x.py"],
        "verified_by": "make check",
    }


def test_renders_a_real_stream_and_ledger_under_the_cap(tmp_path: Path) -> None:
    stream = _write_stream(
        tmp_path / "s.stream.jsonl",
        [INIT_EVENT, TURN_EVENT, READ_CALL, BASH_CALL, BASH_RESULT, RESULT_EVENT],
    )
    item = _write_item(
        tmp_path / "itm.jsonl",
        [
            _created(),
            _claimed(1, "2026-08-31T00:00:01+00:00", "e1"),
            _started("2026-08-31T00:00:01+00:00", "e2"),
            _gate_rejected(1, "3 tests failed", "2026-08-31T00:05:00+00:00", "e3"),
        ],
    )

    body = trace_comment.render(stream, item)

    assert len(body.encode("utf-8")) <= trace_comment.BODY_LIMIT
    assert "attempt 1 of 3" in body
    assert "gate rejected" in body
    assert "src/x.py" in body
    assert "make check" in body
    assert "claude-sonnet-5" in body
    assert "12 turns" in body
    assert "$0.42" in body
    assert "85K in / 23K out" in body


def test_completed_attempt_collapsed_current_attempt_open(tmp_path: Path) -> None:
    stream = _write_stream(tmp_path / "s.stream.jsonl", [INIT_EVENT, READ_CALL, RESULT_EVENT])
    item = _write_item(
        tmp_path / "itm.jsonl",
        [
            _created(),
            _claimed(1, "2026-08-31T00:00:01+00:00", "e1"),
            _started("2026-08-31T00:00:01+00:00", "e2"),
            _gate_rejected(1, "first attempt broke the build", "2026-08-31T00:05:00+00:00", "e3"),
            _reclaimed("2026-08-31T00:06:00+00:00", "e4"),
            _claimed(2, "2026-08-31T00:07:00+00:00", "e5"),
            _started("2026-08-31T00:07:00+00:00", "e6"),
        ],
    )

    body = trace_comment.render(stream, item)

    assert "<details><summary>\U0001f4e6 Attempt 1" in body
    assert "first attempt broke the build" in body
    assert "<details open><summary>\U0001f528 Attempt 2" in body
    assert "attempt 2 of 3" in body


def test_5000_tool_calls_still_renders_under_the_cap_and_states_the_elision(tmp_path: Path) -> None:
    events = [INIT_EVENT]
    for i in range(5000):
        events.append(
            {
                "type": "assistant",
                "timestamp": f"2026-08-31T00:{i % 60:02d}:{i % 60:02d}.000Z",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": f"echo {i}" * 5}}
                    ]
                },
            }
        )
    events.append(RESULT_EVENT)
    stream = _write_stream(tmp_path / "big.stream.jsonl", events)

    body = trace_comment.render(stream, None)

    assert len(body.encode("utf-8")) <= trace_comment.BODY_LIMIT
    assert "elided" in body
    assert "(5000 tools)" in body


def test_no_ledger_records_still_renders_trace_and_status_bar(tmp_path: Path) -> None:
    stream = _write_stream(tmp_path / "s.stream.jsonl", [INIT_EVENT, READ_CALL, RESULT_EVENT])

    body = trace_comment.render(stream, None)

    assert len(body.encode("utf-8")) <= trace_comment.BODY_LIMIT
    assert "src/x.py" in body
    assert "claude-sonnet-5" in body
    assert "$0.42" in body


def test_missing_stream_does_not_raise(tmp_path: Path) -> None:
    body = trace_comment.render(tmp_path / "absent.stream.jsonl", None)

    assert "unknown model" in body
    assert "(no tool calls)" in body


def test_done_item_renders_a_closed_banner(tmp_path: Path) -> None:
    stream = _write_stream(tmp_path / "s.stream.jsonl", [INIT_EVENT, READ_CALL, RESULT_EVENT])
    item = _write_item(
        tmp_path / "itm.jsonl",
        [
            _created(),
            _claimed(1, "2026-08-31T00:00:01+00:00", "e1"),
            _started("2026-08-31T00:00:01+00:00", "e2"),
            _done("2026-08-31T00:05:00+00:00", "e3"),
        ],
    )

    body = trace_comment.render(stream, item)

    assert body.startswith("### ✅ done")
