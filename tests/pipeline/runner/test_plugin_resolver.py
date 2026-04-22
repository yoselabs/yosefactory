"""Unit tests for _resolve_plugins — env-var → SdkPluginConfig resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.pipeline.runner import _resolve_plugins


@pytest.mark.unit
class TestResolvePlugins:
    def test_empty_env_returns_no_plugins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("A2SDLC_PLUGIN_PATHS", raising=False)
        assert _resolve_plugins() == []

    def test_blank_env_returns_no_plugins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("A2SDLC_PLUGIN_PATHS", "  ")
        assert _resolve_plugins() == []

    def test_valid_plugin_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin = tmp_path / "superpowers"
        manifest_dir = plugin / ".claude-plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text('{"name": "superpowers"}')
        monkeypatch.setenv("A2SDLC_PLUGIN_PATHS", str(plugin))

        plugins = _resolve_plugins()

        assert plugins == [{"type": "local", "path": str(plugin)}]

    def test_missing_manifest_skips_plugin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plugin = tmp_path / "bogus"
        plugin.mkdir()
        monkeypatch.setenv("A2SDLC_PLUGIN_PATHS", str(plugin))

        assert _resolve_plugins() == []

    def test_nonexistent_path_skips_plugin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("A2SDLC_PLUGIN_PATHS", "/nonexistent/path")
        assert _resolve_plugins() == []

    def test_colon_separated_multiple(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paths = []
        for name in ("a", "b"):
            p = tmp_path / name
            manifest = p / ".claude-plugin"
            manifest.mkdir(parents=True)
            (manifest / "plugin.json").write_text("{}")
            paths.append(str(p))
        monkeypatch.setenv("A2SDLC_PLUGIN_PATHS", ":".join(paths))

        plugins = _resolve_plugins()

        assert plugins == [
            {"type": "local", "path": paths[0]},
            {"type": "local", "path": paths[1]},
        ]
