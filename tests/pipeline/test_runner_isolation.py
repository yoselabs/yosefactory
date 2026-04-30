"""Tests that the runner wires ``build_sdk_env`` into ``ClaudeAgentOptions``.

Spec §Agent isolation guarantees the SDK subprocess never inherits the
operator's full environment — ``CLAUDE_CONFIG_DIR`` / ``CLAUDE_HOME``
must be stripped, while engine-baseline credentials
(``ANTHROPIC_API_KEY`` / ``CLAUDE_CODE_OAUTH_TOKEN``) and any
adapter-required vars must pass through.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.config import StageConfig
from a2sdlc.domain.progress import ProgressState
from a2sdlc.pipeline.runner import run_stage


def _make_config() -> StageConfig:
    return StageConfig(
        name="spec",
        model="claude-sonnet-4-6",
        max_turns=5,
        timeout_minutes=1,
        allowed_tools=[],
    )


def _make_result_message() -> MagicMock:
    from claude_agent_sdk.types import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.subtype = "success"
    msg.result = "Done"
    msg.total_cost_usd = 0.0
    msg.duration_ms = 0
    msg.num_turns = 0
    msg.session_id = "sess-iso"
    msg.usage = {"input_tokens": 0, "output_tokens": 0}
    return msg


@pytest.mark.unit
class TestRunnerIsolation:
    @pytest.mark.asyncio
    async def test_env_strips_claude_config_dir_and_passes_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pollute the operator env with both forbidden vars and the
        # engine baseline credentials.
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/should-not-leak")
        monkeypatch.setenv("CLAUDE_HOME", "/tmp/should-not-leak-home")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "ghs-oauth-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghs-github-test")

        result_msg = _make_result_message()
        captured: dict[str, object] = {}

        def mock_options_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            obj = MagicMock()
            for k, v in kwargs.items():
                setattr(obj, k, v)
            return obj

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
        ):
            await run_stage(
                user_prompt="hi",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/iso",
                progress_state=ProgressState(project_root="/tmp/iso"),
                required_env_names=frozenset({"GITHUB_TOKEN"}),
            )

        env_obj = captured.get("env")
        assert isinstance(env_obj, dict)
        env = cast("dict[str, str]", env_obj)
        # Forbidden — engine controls SDK config tree.
        assert "CLAUDE_CONFIG_DIR" not in env
        assert "CLAUDE_HOME" not in env
        # Engine baseline credentials always pass through.
        assert env.get("ANTHROPIC_API_KEY") == "sk-test"
        assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "ghs-oauth-test"
        # Adapter-required var threaded via ``required_env_names``.
        assert env.get("GITHUB_TOKEN") == "ghs-github-test"

    @pytest.mark.asyncio
    async def test_env_baseline_credentials_pass_without_explicit_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Even without explicit ``required_env_names``, the engine baseline
        # is always honoured.
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/x")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-baseline")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "ghs-baseline")

        result_msg = _make_result_message()
        captured: dict[str, object] = {}

        def mock_options_cls(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        async def mock_query(prompt: str, options: object):  # noqa: ANN201, ARG001
            yield result_msg

        with (
            patch("claude_agent_sdk.query", side_effect=mock_query),
            patch("claude_agent_sdk.ClaudeAgentOptions", side_effect=mock_options_cls),
        ):
            await run_stage(
                user_prompt="hi",
                system_prompt="sys",
                config=_make_config(),
                ticket_key="PROJ-1",
                stage="spec",
                project_root="/tmp/iso",
                progress_state=ProgressState(project_root="/tmp/iso"),
            )

        env_obj = captured["env"]
        assert isinstance(env_obj, dict)
        env = cast("dict[str, str]", env_obj)
        assert "CLAUDE_CONFIG_DIR" not in env
        assert env.get("ANTHROPIC_API_KEY") == "sk-baseline"
        assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "ghs-baseline"
