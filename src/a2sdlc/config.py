"""Configuration for a2sdlc stages and projects."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from a2sdlc.models import GateConfig, GateMode

logger = logging.getLogger("a2sdlc.config")

# ── Stage configuration ───────────────────────────────────────────────


@dataclass
class StageConfig:
    """Configuration for a single pipeline stage."""

    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 60
    allowed_tools: list[str] = field(default_factory=list)
    code_reviews: int = 0
    max_review_cycles: int = 2


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, stage: str, review_cycles: int = 0) -> str:
    """Deterministic UUID from ticket key + stage name + review_cycles."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{stage}:{review_cycles}")
    )


# ── Project configuration ─────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Per-repo settings read from ``a2sdlc.yaml`` at the project root."""

    adapter: str = "github"
    auto_spec: bool = False
    default_base: str = "main"
    test_command: str = "make test"
    stage_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    _gates: GateConfig = field(default_factory=GateConfig, repr=False, compare=False)

    def gate_config(self) -> GateConfig:
        """Return the gate configuration."""
        return self._gates


def load_config_file(project_root: Path) -> ProjectConfig:
    """Load project config from ``project_root/a2sdlc.yaml``.

    Returns defaults when the file is absent.
    """
    config_path = project_root / "a2sdlc.yaml"
    if not config_path.exists():
        logger.info("No config at %s — using defaults", config_path)
        return ProjectConfig()

    with config_path.open() as fh:
        data: dict[str, object] = yaml.safe_load(fh) or {}

    logger.info("Loaded config from %s", config_path)

    pipeline = data.get("pipeline", {})
    pipeline = pipeline if isinstance(pipeline, dict) else {}

    gates_raw = pipeline.get("gates", {})
    gates_raw = gates_raw if isinstance(gates_raw, dict) else {}

    merge_mode = (
        GateMode(str(gates_raw["merge"])) if "merge" in gates_raw else GateMode.HUMAN
    )
    review_mode = (
        GateMode(str(gates_raw["review"])) if "review" in gates_raw else GateMode.AUTO
    )
    gates = GateConfig(merge=merge_mode, review=review_mode)

    stages_raw = data.get("stages", {})
    stage_overrides: dict[str, dict[str, object]] = {}
    if isinstance(stages_raw, dict):
        for stage_name, stage_data in stages_raw.items():
            if isinstance(stage_data, dict):
                stage_overrides[str(stage_name)] = stage_data

    config = ProjectConfig(
        adapter=str(data.get("adapter", "github")),
        auto_spec=bool(pipeline.get("auto_spec", False)),
        default_base=str(pipeline.get("default_base", "main")),
        test_command=str(data.get("test_command", "make test")),
        stage_overrides=stage_overrides,
    )
    config._gates = gates  # noqa: SLF001
    return config


def load_stage_config(stage_name: str, project: ProjectConfig) -> StageConfig:
    """Return a StageConfig for ``stage_name``, merged with project overrides.

    Base config comes from the stage class; project ``stage_overrides`` are
    applied on top using ``dataclasses.replace``.
    """
    from a2sdlc.stages import get_stage  # noqa: PLC0415

    stage_obj = get_stage(stage_name)
    base = stage_obj.config

    overrides = project.stage_overrides.get(stage_name, {})
    if not overrides:
        return base

    # Only pass fields that actually exist on StageConfig.
    import dataclasses  # noqa: PLC0415

    valid_fields = {f.name for f in dataclasses.fields(StageConfig)}
    patches = {k: v for k, v in overrides.items() if k in valid_fields}
    return replace(base, **patches)
