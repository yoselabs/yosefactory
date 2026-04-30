"""Agent-process isolation. Spec §Agent isolation."""

from __future__ import annotations

import logging

from a2sdlc.runtime.isolation import build_sdk_env, build_sdk_options_overrides


def test_curated_env_drops_extra_keys():
    src = {
        "ANTHROPIC_API_KEY": "k",
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "LANG": "en_US.UTF-8",
        "RANDOM_OPERATOR_VAR": "leak",
        "CLAUDE_CONFIG_DIR": "/tmp/should-not",
        "CLAUDE_HOME": "/tmp/should-not",
    }
    env = build_sdk_env(src, required_env_names={"ANTHROPIC_API_KEY"})
    assert env["ANTHROPIC_API_KEY"] == "k"
    assert env["PATH"] == "/usr/bin"
    assert "RANDOM_OPERATOR_VAR" not in env
    assert "CLAUDE_CONFIG_DIR" not in env
    assert "CLAUDE_HOME" not in env


def test_options_overrides_pin_setting_sources_and_empty_mcp():
    overrides = build_sdk_options_overrides()
    assert overrides["setting_sources"] == ["project", "local"]
    assert overrides["mcp_servers"] == []


def test_forbidden_env_logged_when_present(caplog):
    caplog.set_level(logging.WARNING, logger="a2sdlc.runtime.isolation")
    build_sdk_env({"CLAUDE_CONFIG_DIR": "/tmp/x"}, required_env_names=set())
    assert any("CLAUDE_CONFIG_DIR" in r.message for r in caplog.records)


def test_baseline_passes_posix_identity_and_cache_dirs():
    """USER/LOGNAME/SHELL + TMPDIR + XDG_* must reach the SDK subprocess.

    Without these, the agent's Bash tool falls back to ``/bin/sh``
    instead of the operator's shell, and node/npm (under the Claude
    CLI) miss their cache dirs — observed as cycle-2 SDK
    ``ProcessError`` failures on long smoke runs.
    """
    src = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "USER": "denis",
        "LOGNAME": "denis",
        "SHELL": "/bin/zsh",
        "TMPDIR": "/var/folders/tmp",
        "XDG_CACHE_HOME": "/home/x/.cache",
        "XDG_CONFIG_HOME": "/home/x/.config",
        "XDG_DATA_HOME": "/home/x/.local/share",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }
    env = build_sdk_env(src, required_env_names=set())
    for k in (
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    ):
        assert env[k] == src[k], k
