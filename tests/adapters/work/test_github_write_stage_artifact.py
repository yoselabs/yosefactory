"""Unit tests for GitHubWorkAdapter.write_stage_artifact stub."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter
from a2sdlc.domain.models import StageName


def _make_work_adapter() -> GitHubWorkAdapter:
    return GitHubWorkAdapter(repo=MagicMock(), trigger_mention="@a2sdlc")


@pytest.mark.unit
class TestWriteStageArtifact:
    def test_write_stage_artifact_writes_under_local_state(
        self, tmp_path, monkeypatch
    ) -> None:
        """GH adapter stub writes to a local path; tracker-side push is a future spec."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_work_adapter()
        p = adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="x")
        assert p.exists()
        assert p.read_text() == "x"

    def test_write_stage_artifact_implement_filename_uses_cycle(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        adapter = _make_work_adapter()
        p = adapter.write_stage_artifact(StageName.IMPLEMENT, cycle=2, content="y")
        assert p.name == "implement-cycle-2.md"
        assert p.read_text() == "y"

    def test_write_stage_artifact_rejects_review(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        adapter = _make_work_adapter()
        with pytest.raises(ValueError):
            adapter.write_stage_artifact(StageName.REVIEW, cycle=1, content="z")
