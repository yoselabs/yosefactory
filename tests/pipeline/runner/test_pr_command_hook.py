"""PreToolUse hook tests — engine-owned PR commands are denied at the SDK level."""

from __future__ import annotations

from typing import Any, cast

import pytest

from a2sdlc.pipeline.runner import (
    _BLOCKED_PR_SUBSTRINGS,
    _deny_engine_owned_pr_commands,
)


def _bash_input(command: str) -> dict[str, Any]:
    return {
        "session_id": "s",
        "transcript_path": "/tmp/t",
        "cwd": "/tmp",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "u",
    }


@pytest.mark.unit
@pytest.mark.asyncio
class TestDenyEngineOwnedPrCommands:
    async def test_non_bash_tool_passes_through(self) -> None:
        inp = {
            "session_id": "s",
            "transcript_path": "/tmp/t",
            "cwd": "/tmp",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
            "tool_use_id": "u",
        }
        out = await _deny_engine_owned_pr_commands(
            cast(Any, inp), None, cast(Any, object())
        )
        assert out == {}

    async def test_benign_bash_passes_through(self) -> None:
        out = await _deny_engine_owned_pr_commands(
            cast(Any, _bash_input("git status")), None, cast(Any, object())
        )
        assert out == {}

    async def test_gh_pr_create_blocked(self) -> None:
        out = await _deny_engine_owned_pr_commands(
            cast(Any, _bash_input("gh pr create --base develop --title foo")),
            None,
            cast(Any, object()),
        )
        specific = out.get("hookSpecificOutput", {})
        assert specific.get("permissionDecision") == "deny"
        reason = specific.get("permissionDecisionReason", "")
        assert "gh pr create" in reason
        assert "engine-owned" in reason

    async def test_gh_pr_merge_blocked(self) -> None:
        out = await _deny_engine_owned_pr_commands(
            cast(Any, _bash_input("gh pr merge 42 --squash")),
            None,
            cast(Any, object()),
        )
        specific = out.get("hookSpecificOutput", {})
        assert specific.get("permissionDecision") == "deny"

    async def test_case_insensitive_match(self) -> None:
        out = await _deny_engine_owned_pr_commands(
            cast(Any, _bash_input("GH PR CREATE --title x")),
            None,
            cast(Any, object()),
        )
        assert out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    async def test_all_blocked_patterns_trigger_deny(self) -> None:
        """Every substring in the deny-list should block when present."""
        for pattern in _BLOCKED_PR_SUBSTRINGS:
            out = await _deny_engine_owned_pr_commands(
                cast(Any, _bash_input(f"{pattern} foo bar")),
                None,
                cast(Any, object()),
            )
            assert (
                out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            ), f"expected {pattern!r} to be blocked"

    async def test_non_string_command_is_passthrough(self) -> None:
        inp = {
            "session_id": "s",
            "transcript_path": "/tmp/t",
            "cwd": "/tmp",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 42},
            "tool_use_id": "u",
        }
        out = await _deny_engine_owned_pr_commands(
            cast(Any, inp), None, cast(Any, object())
        )
        assert out == {}
