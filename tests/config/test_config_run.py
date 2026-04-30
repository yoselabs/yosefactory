"""RunConfig loader. Spec §Composition."""

from __future__ import annotations

import textwrap

import pytest

from a2sdlc.config_run import RunConfig, load_run_config, RunConfigError


def test_minimal_local_config_loads(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        textwrap.dedent("""\
        mode: local
        adapters:
          work: local-file
          review: local
        subscribers:
          - console
          - mlflow
        required_env:
          - ANTHROPIC_API_KEY
        pipeline:
          max_review_cycles: 3
          protected_bases:
            - main
            - master
    """)
    )
    cfg = load_run_config(p)
    assert isinstance(cfg, RunConfig)
    assert cfg.mode == "local"
    assert cfg.adapters.work == "local-file"
    assert cfg.adapters.review == "local"
    assert cfg.subscribers == ["console", "mlflow"]
    assert cfg.required_env == ["ANTHROPIC_API_KEY"]
    assert cfg.pipeline.max_review_cycles == 3
    assert "main" in cfg.pipeline.protected_bases


def test_unknown_mode_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("mode: nope\nadapters: {work: x, review: y}\nsubscribers: []\n")
    with pytest.raises(RunConfigError):
        load_run_config(p)


def test_defaults_applied_when_pipeline_block_missing(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        textwrap.dedent("""\
        mode: local
        adapters:
          work: local-file
          review: local
        subscribers: []
        required_env: []
    """)
    )
    cfg = load_run_config(p)
    assert cfg.pipeline.max_review_cycles == 3
    assert cfg.pipeline.protected_bases == ["main", "master"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(RunConfigError):
        load_run_config(tmp_path / "no.yaml")


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("mode: local\nadapters: [bad yaml")
    with pytest.raises(RunConfigError):
        load_run_config(p)
