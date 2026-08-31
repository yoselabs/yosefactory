"""A trace line per tool call, live -- and reproducible from a saved stream, per event `timestamp`.

Fixture events are trimmed copies of shapes measured off the real binary (`tests/executor/test_stream.py`'s
own convention): `assistant`/`user`/`result`, never invented keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from yosefactory.executor.stream import StreamReader
from yosefactory.executor.trace import Tracer

READ_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:03.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "src/x.py"}}]},
}
CONTAINER_PATH_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:03.000Z",
    "message": {
        "content": [
            {
                "type": "tool_use",
                "id": "t1c",
                "name": "Read",
                "input": {"file_path": "/data/workspace/src/yosefactory/executor/stream.py"},
            }
        ]
    },
}
APP_PATH_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:03.000Z",
    "message": {
        "content": [
            {
                "type": "tool_use",
                "id": "t1a",
                "name": "Read",
                "input": {"file_path": "/app/openspec/specs/backlog-item-format/spec.md"},
            }
        ]
    },
}
SED_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:07.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t4", "name": "Bash", "input": {"command": "sed -n '1,400p' src/x.py"}}]},
}
SED_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T00:00:09.000Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t4", "content": "..."}]},
    "tool_use_result": {"stdout": "\n".join(f"line {i}" for i in range(312)), "stderr": ""},
}
WRITE_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T05:26:00.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t5", "name": "Write", "input": {"file_path": "out/scratch.json", "content": "x"}}]},
}
WRITE_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T05:26:01.000Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t5", "content": "written"}]},
    "tool_use_result": {
        "type": "create",
        "filePath": "out/scratch.json",
        "content": "line one\nline two\nline three\n",
        "structuredPatch": [],
    },
}
READ_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T00:00:04.000Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "1\tprint()"}]},
    "tool_use_result": {"type": "file"},
}
BASH_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:24.000Z",
    "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "make check"}}]},
}
BASH_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T00:00:31.000Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "495 passed"}]},
    "tool_use_result": {"stdout": "495 passed", "stderr": ""},
}
EDIT_CALL = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:00:11.000Z",
    "message": {
        "content": [
            {
                "type": "tool_use",
                "id": "t3",
                "name": "Edit",
                "input": {"file_path": "src/x.py", "old_string": "a", "new_string": "b"},
            }
        ]
    },
}
EDIT_RESULT = {
    "type": "user",
    "timestamp": "2026-08-31T00:00:11.500Z",
    "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": "edited"}]},
    "tool_use_result": {"structuredPatch": [{"lines": ["-old one", "-old two", "+new one", " context", "+new two", "+new three"]}]},
}
TEXT_EVENT = {
    "type": "assistant",
    "timestamp": "2026-08-31T00:01:02.000Z",
    "message": {"content": [{"type": "text", "text": "the marker is written before the body"}]},
}
RESULT_EVENT = {
    "type": "result",
    "duration_ms": 298000,
    "subtype": "success",
    "is_error": False,
    "num_turns": 12,
    "total_cost_usd": 0.42,
}


def test_read_call_shows_path_not_tool_name() -> None:
    lines = Tracer().render(READ_CALL)
    assert len(lines) == 1
    assert "src/x.py" in lines[0]
    assert "Read" not in lines[0]


def test_a_path_inside_the_workspace_mount_prints_repo_relative() -> None:
    lines = Tracer().render(CONTAINER_PATH_CALL)
    assert lines == [" 0:00  \U0001f4d6 read  src/yosefactory/executor/stream.py"]


def test_a_path_outside_the_repo_root_is_left_alone() -> None:
    lines = Tracer().render(APP_PATH_CALL)
    assert lines == [" 0:00  \U0001f4d6 read  /app/openspec/specs/backlog-item-format/spec.md"]


def test_a_sed_dump_result_reports_its_line_count_not_its_last_line() -> None:
    tracer = Tracer()
    tracer.render(SED_CALL)
    lines = tracer.render(SED_RESULT)
    assert lines == [" 0:02        → 312 lines"]


def test_a_whole_file_write_reports_its_size_never_plus_zero_minus_zero() -> None:
    tracer = Tracer()
    tracer.render(WRITE_CALL)
    lines = tracer.render(WRITE_RESULT)
    assert len(lines) == 1
    assert "(+0 -0)" not in lines[0]
    assert "3 lines" in lines[0]


def test_bash_shows_the_command_and_a_result_line() -> None:
    tracer = Tracer()
    call_line = tracer.render(BASH_CALL)[0]
    assert "make check" in call_line
    result_lines = tracer.render(BASH_RESULT)
    assert result_lines == [" 0:07        → 495 passed"]


def test_edit_result_reports_a_diff_size() -> None:
    tracer = Tracer()
    tracer.render(EDIT_CALL)
    lines = tracer.render(EDIT_RESULT)
    assert lines[0].endswith("→ (+3 -2)")


def test_text_is_truncated_to_one_line_and_quoted() -> None:
    lines = Tracer().render(TEXT_EVENT)
    assert lines == [' 0:00  \U0001f4ac "the marker is written before the body"']


def test_result_line_carries_turns_cost_and_its_own_duration() -> None:
    """`result` carries no `timestamp` of its own (measured); `duration_ms` is the wall clock instead."""
    lines = Tracer().render(RESULT_EVENT)
    assert lines == [" 4:58  ✅ result success · 12 turns · $0.42"]


def test_elapsed_offset_is_anchored_to_the_first_timestamp_seen() -> None:
    tracer = Tracer()
    first = tracer.render(READ_CALL)[0]
    assert first.startswith(" 0:00")
    later = tracer.render(BASH_CALL)[0]
    assert later.startswith(" 0:21")


def test_a_tool_result_with_no_matching_pending_call_is_silent() -> None:
    """A `user` event whose `tool_use_id` was never seen as a `tool_use` (e.g. mid-stream start)."""
    orphan = {**READ_RESULT, "message": {"content": [{"type": "tool_result", "tool_use_id": "unknown"}]}}
    assert Tracer().render(orphan) == []


def test_replaying_a_saved_stream_reproduces_the_same_lines(tmp_path: Path) -> None:
    """The done-when criterion: a trace derived twice from one saved file is byte-identical."""
    events = [READ_CALL, READ_RESULT, EDIT_CALL, EDIT_RESULT, BASH_CALL, BASH_RESULT, TEXT_EVENT, RESULT_EVENT]
    path = tmp_path / "s.stream.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def replay() -> list[str]:
        sunk: list[str] = []
        reader = StreamReader(path, sink=sunk.append)
        reader.poll()
        return sunk

    assert replay() == replay()


def test_stream_reader_sink_is_none_by_default_and_verdict_logic_is_unaffected(tmp_path: Path) -> None:
    """`consume()` retains tool events for the trace without changing what it already returned."""
    path = tmp_path / "s.jsonl"
    events = [
        {
            "type": "system",
            "subtype": "init",
            "memory_paths": [],
            "mcp_servers": [],
            "skills": [],
            "plugins": [],
            "permissionMode": "manual",
        },
        {"type": "system", "subtype": "post_turn_summary"},
        READ_CALL,
        READ_RESULT,
        RESULT_EVENT,
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    silent = StreamReader(path)
    assert silent.turns_taken() == 1
    assert silent.terminal is not None

    sunk: list[str] = []
    traced = StreamReader(path, sink=sunk.append)
    assert traced.turns_taken() == 1
    assert traced.terminal is not None
    assert any("src/x.py" in line for line in sunk)


def test_sink_is_called_live_as_lines_are_written(tmp_path: Path) -> None:
    """Streamed, not batched: a second `poll()` after more lines land emits only the new ones."""
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(READ_CALL) + "\n", encoding="utf-8")
    sunk: list[str] = []
    reader = StreamReader(path, sink=sunk.append)
    reader.poll()
    assert len(sunk) == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(RESULT_EVENT) + "\n")
    reader.poll()
    assert len(sunk) == 2
