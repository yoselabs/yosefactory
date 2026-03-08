"""Configuration for a2sdlc stages and projects."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

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


# Env-var name → StageConfig field name + converter
_ENV_MAP: dict[str, tuple[str, type]] = {
    "MODEL": ("model", str),
    "MAX_TURNS": ("max_turns", int),
}


def load_config(stage: str, **overrides: object) -> StageConfig:
    """Build a StageConfig by merging stage defaults, env vars, and CLI overrides.

    Stage defaults come from the stage module (e.g., stages/spec.py).
    Priority: CLI arg > env var > stage default.

    .. deprecated::
        Use ``load_stage_config`` with a ``ProjectConfig`` instead.
        This function is kept for backward compatibility with the CLI.
    """
    from a2sdlc.stages import get_stage  # noqa: PLC0415

    stage_obj = get_stage(stage)
    base = stage_obj.config

    # Layer env vars on top of defaults.
    env_patches: dict[str, object] = {}
    for env_key, (field_name, conv) in _ENV_MAP.items():
        val = os.environ.get(env_key)
        if val is not None:
            env_patches[field_name] = conv(val)

    # Layer CLI overrides on top of env.
    merged = {**env_patches, **{k: v for k, v in overrides.items() if v is not None}}
    return replace(base, **merged)


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, stage: str) -> str:
    """Deterministic UUID from ticket key + stage name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{stage}"))


# ── Pipeline flags ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineFlags:
    """Boolean flags controlling pipeline autonomy.

    Set via project config defaults, overridden by issue labels or CLI flags.
    """

    auto_spec: bool = False  # true = skip Q&A, agent self-answers
    auto_proceed: bool = True  # true = spec→implement without approval
    auto_merge: bool = False  # true = merge after review passes


# Label → (flag_name, value) mapping
_LABEL_FLAG_MAP: dict[str, tuple[str, bool]] = {
    "auto-spec": ("auto_spec", True),
    "auto-merge": ("auto_merge", True),
    "spec-only": ("auto_proceed", False),
}


def resolve_flags(defaults: PipelineFlags, labels: list[str]) -> PipelineFlags:
    """Build a new PipelineFlags from defaults + label overrides.

    Labels matching ``_LABEL_FLAG_MAP`` set the corresponding flag value.
    Unknown labels are silently ignored.
    """
    patches: dict[str, bool] = {}
    for label in labels:
        if label in _LABEL_FLAG_MAP:
            flag_name, value = _LABEL_FLAG_MAP[label]
            patches[flag_name] = value
    if not patches:
        return defaults
    return replace(defaults, **patches)


# ── Project configuration ─────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Per-repo settings read from ``a2sdlc.yaml`` at the project root."""

    adapter: str = "github"
    auto_spec: bool = False
    auto_proceed: bool = True
    auto_merge: bool = False
    default_base: str = "main"
    test_command: str = "make test"
    stage_overrides: dict[str, dict[str, object]] = field(default_factory=dict)

    def pipeline_flags(self) -> PipelineFlags:
        """Build PipelineFlags from project config."""
        return PipelineFlags(
            auto_spec=self.auto_spec,
            auto_proceed=self.auto_proceed,
            auto_merge=self.auto_merge,
        )


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

    stages_raw = data.get("stages", {})
    stage_overrides: dict[str, dict[str, object]] = {}
    if isinstance(stages_raw, dict):
        for stage_name, stage_data in stages_raw.items():
            if isinstance(stage_data, dict):
                stage_overrides[str(stage_name)] = stage_data

    return ProjectConfig(
        adapter=str(data.get("adapter", "github")),
        auto_spec=bool(pipeline.get("auto_spec", False)),
        auto_proceed=bool(pipeline.get("auto_proceed", True)),
        auto_merge=bool(pipeline.get("auto_merge", False)),
        default_base=str(pipeline.get("default_base", "main")),
        test_command=str(data.get("test_command", "make test")),
        stage_overrides=stage_overrides,
    )


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


# ── Backward-compat shim ──────────────────────────────────────────────


def load_project(project_root: Path) -> ProjectConfig:
    """Backward-compatible shim: delegates to ``load_config_file``.

    .. deprecated::
        Use ``load_config_file`` directly.
    """
    return load_config_file(project_root)
