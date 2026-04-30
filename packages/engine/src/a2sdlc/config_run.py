"""RunConfig — `.a2sdlc/config.yaml`. Spec §Composition."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

EcosystemMode = Literal["local", "github", "jira-github"]


class RunConfigError(ValueError):
    pass


class AdaptersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work: str
    review: str


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_review_cycles: int = 3
    protected_bases: list[str] = Field(default_factory=lambda: ["main", "master"])


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: EcosystemMode
    adapters: AdaptersConfig
    subscribers: list[str] = Field(default_factory=list)
    required_env: list[str] = Field(default_factory=list)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


def load_run_config(path: Path) -> RunConfig:
    if not path.exists():
        raise RunConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise RunConfigError(f"invalid YAML in {path}: {exc}") from exc
    try:
        return RunConfig.model_validate(raw)
    except ValidationError as exc:
        raise RunConfigError(f"invalid config in {path}:\n{exc}") from exc
