"""Configuration for a2sdlc stages and projects."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from a2sdlc.domain.models import GateConfig

logger = logging.getLogger("a2sdlc.config")


# ── Errors ────────────────────────────────────────────────────────────


class ConfigError(ValueError):
    """Raised when the config file is malformed or contains unknown keys."""


# Maps to the SDK's ``ClaudeAgentOptions.effort`` — note ``xhigh`` → ``max``
# at the runner boundary (see ``pipeline/runner.py``).
EffortLevel = Literal["low", "medium", "high", "xhigh"]


# ── Stage configuration ───────────────────────────────────────────────


class StageConfig(BaseModel):
    """Configuration for a single pipeline stage."""

    model_config = ConfigDict(extra="forbid")

    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 60
    allowed_tools: list[str] = Field(default_factory=list)
    code_reviews: int = 0
    max_review_cycles: int = 2


# ── Adapter / quality blocks ──────────────────────────────────────────


class AdaptersConfig(BaseModel):
    """Names of the adapters to wire for a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    work: str = "jira"
    review: str = "github"
    git: str = "github"
    progress: str = "gh_actions"


class QualityConfig(BaseModel):
    """Deterministic quality gate configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_command: str = "make check"


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, stage: str) -> str:
    """Deterministic UUID from ticket key + stage name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{stage}"))


# ── Project configuration ─────────────────────────────────────────────


class ProjectConfig(BaseModel):
    """Per-repo settings read from ``.a2sdlc/config.yaml``."""

    model_config = ConfigDict(extra="forbid")

    self_answer: bool = False
    default_base: str = "main"
    model: str = "claude-sonnet-4-6"
    effort: EffortLevel | None = None
    stage_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    gates: GateConfig = Field(default_factory=GateConfig)
    # Hard ceiling on accumulated spend per ticket. The review-cycle
    # breaker only catches REVIEW loops; a chatty SPEC could burn
    # unbounded cost through QUESTIONS → proceed → QUESTIONS cycles.
    # Default ~5× a typical end-to-end ticket cost (~$2-3).
    max_cost_usd_per_ticket: float = 15.0

    @model_validator(mode="before")
    @classmethod
    def _normalize_yaml_shape(cls, data: Any) -> Any:
        """Fold YAML-specific keys into their in-memory equivalents.

        - ``stages:`` block becomes ``stage_overrides``.
        - ``spec: {self_answer: ...}`` folds into top-level ``self_answer``
          (top-level wins if both are set).
        """
        if not isinstance(data, dict):
            return data

        if "stages" in data and "stage_overrides" not in data:
            data["stage_overrides"] = data.pop("stages")

        spec = data.pop("spec", None)
        if isinstance(spec, dict):
            extra = set(spec) - {"self_answer"}
            if extra:
                raise ValueError(
                    f"Unknown keys in 'spec' block: {sorted(extra)}. "
                    "Only 'self_answer' is accepted."
                )
            if "self_answer" in spec and "self_answer" not in data:
                data["self_answer"] = spec["self_answer"]
        return data

    def gate_config(self) -> GateConfig:
        """Return the gate configuration."""
        return self.gates


def load_config_file(project_root: Path) -> ProjectConfig:
    """Load project config from ``project_root/.a2sdlc/config.yaml``.

    Raises ``FileNotFoundError`` if the file is missing and ``ConfigError``
    if the YAML is malformed or contains unknown keys.
    """
    config_path = project_root / ".a2sdlc" / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config not found at {config_path}. "
            f"Create .a2sdlc/config.yaml — see "
            f"docs/superpowers/specs/2026-04-18-a2sdlc-local-runner-design.md "
            f"for the schema."
        )

    with config_path.open() as fh:
        data: Any = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ConfigError(
            f"Config at {config_path} must be a YAML mapping at the top level."
        )

    try:
        config = ProjectConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_pydantic_error(exc)) from exc

    logger.info("Loaded config from %s", config_path)
    return config


def _format_pydantic_error(exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into a single-line config message."""
    lines: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"{loc}: {err['msg']}")
    return "; ".join(lines)


def load_stage_config(stage_name: str, project: ProjectConfig) -> StageConfig:
    """Return a StageConfig for ``stage_name``, merged with project overrides."""
    from a2sdlc.stages import get_stage  # noqa: PLC0415

    stage_obj = get_stage(stage_name)
    base = stage_obj.config

    overrides = project.stage_overrides.get(stage_name, {})
    if not overrides:
        return base

    return base.model_copy(update=overrides)
