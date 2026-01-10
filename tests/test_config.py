"""Tests for a2sdlc.config — StageConfig, ProjectConfig, load functions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from a2sdlc.config import (
    STAGE_DEFAULTS,
    ProjectConfig,
    StageConfig,
    load_config,
    load_project,
)


# ── StageConfig defaults ──────────────────────────────────────────────


@pytest.mark.unit
class TestStageDefaults:
    def test_stage_defaults_exist(self) -> None:
        expected = {"prd", "plan", "implement", "review", "ci-assess"}
        assert set(STAGE_DEFAULTS.keys()) == expected
        for cfg in STAGE_DEFAULTS.values():
            assert isinstance(cfg, StageConfig)

    def test_prd_defaults(self) -> None:
        cfg = STAGE_DEFAULTS["prd"]
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.max_turns == 25
        assert cfg.timeout_minutes == 20
        assert "Bash" in cfg.allowed_tools
        assert "Agent" in cfg.allowed_tools


# ── load_config overrides ─────────────────────────────────────────────


@pytest.mark.unit
class TestLoadConfig:
    def test_override_model(self) -> None:
        cfg = load_config("prd", model="claude-opus-4")
        assert cfg.model == "claude-opus-4"
        # Other fields stay at defaults.
        assert cfg.max_turns == 25

    def test_override_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODEL", "claude-haiku-4")
        monkeypatch.setenv("MAX_TURNS", "99")
        cfg = load_config("plan")
        assert cfg.model == "claude-haiku-4"
        assert cfg.max_turns == 99

    def test_cli_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MODEL", "from-env")
        cfg = load_config("prd", model="from-cli")
        assert cfg.model == "from-cli"


# ── ProjectConfig ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestProjectConfig:
    def test_load_project_missing(self, tmp_path: Path) -> None:
        cfg = load_project(tmp_path)
        assert cfg == ProjectConfig()
        assert cfg.tickets_adapter == "github-issues"
        assert cfg.test_command == "make test"

    def test_load_project_with_file(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".a2sdlc"
        config_dir.mkdir()
        config_file = config_dir / "project.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "tickets_adapter": "jira",
                    "code_adapter": "gitlab",
                    "test_command": "pytest -x",
                    "jira_status_map": {"todo": "To Do", "done": "Done"},
                }
            )
        )
        cfg = load_project(tmp_path)
        assert cfg.tickets_adapter == "jira"
        assert cfg.code_adapter == "gitlab"
        assert cfg.test_command == "pytest -x"
        assert cfg.jira_status_map == {"todo": "To Do", "done": "Done"}
