"""Configuration for a2sdlc stages and projects."""

from __future__ import annotations

import dataclasses
import logging
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from a2sdlc.domain.models import GateConfig, GateMode

logger = logging.getLogger("a2sdlc.config")

# ── Errors ────────────────────────────────────────────────────────────


class ConfigError(ValueError):
    """Raised when the config file is malformed or contains unknown keys."""


# Strict allowlist for the top-level keys in ``.a2sdlc/config.yaml``.
# Only keys that the loader actually parses appear here — YAGNI. Reserved
# names (e.g. ``max_turns_per_stage``, ``resume``, ``timeouts``) will be
# added back when a later task implements their parsing.
_ALLOWED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "adapters",
        "stages",
        "spec",
        "quality",
        "model",
        "default_base",
        "gates",
        "self_answer",
        "effort",
    }
)


# Valid values for the top-level ``effort`` config field. Maps to the SDK's
# ``ClaudeAgentOptions.effort`` — note ``xhigh`` → ``max`` at the runner
# boundary (see ``pipeline/runner.py``).
_ALLOWED_EFFORT_VALUES: frozenset[str] = frozenset({"low", "medium", "high", "xhigh"})


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


# ── Adapter / quality blocks ──────────────────────────────────────────


@dataclass(frozen=True)
class AdaptersConfig:
    """Names of the adapters to wire for a run.

    Values are short identifiers resolved by the adapter factory at
    composition time (e.g. ``"jira"``, ``"github"``, ``"local_file"``).
    """

    work: str = "jira"
    review: str = "github"
    git: str = "github"
    progress: str = "gh_actions"


@dataclass(frozen=True)
class QualityConfig:
    """Deterministic quality gate configuration."""

    check_command: str = "make check"


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, stage: str, review_cycles: int = 0) -> str:
    """Deterministic UUID from ticket key + stage name + review_cycles."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{stage}:{review_cycles}")
    )


# ── Project configuration ─────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Per-repo settings read from ``.a2sdlc/config.yaml``."""

    self_answer: bool = False
    default_base: str = "main"
    model: str = "claude-sonnet-4-6"
    effort: str | None = None
    stage_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    adapters: AdaptersConfig = field(default_factory=AdaptersConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    _gates: GateConfig = field(default_factory=GateConfig, repr=False, compare=False)

    def gate_config(self) -> GateConfig:
        """Return the gate configuration."""
        return self._gates


def _validate_keys(data: dict[str, object]) -> None:
    """Raise ``ConfigError`` if ``data`` has any top-level keys outside the allowlist."""
    unknown = sorted(set(data.keys()) - _ALLOWED_TOP_LEVEL_KEYS)
    if unknown:
        allowed = sorted(_ALLOWED_TOP_LEVEL_KEYS)
        raise ConfigError(
            f"Unknown config keys: {unknown}. Allowed top-level keys: {allowed}."
        )


def load_config_file(project_root: Path) -> ProjectConfig:
    """Load project config from ``project_root/.a2sdlc/config.yaml``.

    Raises ``FileNotFoundError`` if the file is missing, and ``ConfigError``
    if any top-level key is not in the allowlist.
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
        data: dict[str, object] = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ConfigError(
            f"Config at {config_path} must be a YAML mapping at the top level."
        )

    _validate_keys(data)

    logger.info("Loaded config from %s", config_path)

    gates_raw = data.get("gates", {})
    gates_raw = gates_raw if isinstance(gates_raw, dict) else {}
    merge_mode = (
        GateMode(str(gates_raw["merge"])) if "merge" in gates_raw else GateMode.HUMAN
    )
    spec_mode = (
        GateMode(str(gates_raw["spec"])) if "spec" in gates_raw else GateMode.AUTO
    )
    gates = GateConfig(merge=merge_mode, spec=spec_mode)

    stages_raw = data.get("stages", {})
    stage_overrides: dict[str, dict[str, object]] = {}
    if isinstance(stages_raw, dict):
        for stage_name, stage_data in stages_raw.items():
            if isinstance(stage_data, dict):
                stage_overrides[str(stage_name)] = stage_data

    spec_raw = data.get("spec", {})
    spec_raw = spec_raw if isinstance(spec_raw, dict) else {}
    # ``self_answer`` may be set either at the top level or inside ``spec:``.
    self_answer = bool(spec_raw.get("self_answer", data.get("self_answer", False)))

    adapters_raw = data.get("adapters", {})
    adapters_raw = adapters_raw if isinstance(adapters_raw, dict) else {}
    try:
        adapters = AdaptersConfig(**adapters_raw)
    except TypeError as e:
        valid = {f.name for f in dataclasses.fields(AdaptersConfig)}
        raise ConfigError(
            f"Unknown keys in 'adapters' block: {e}. Allowed: {sorted(valid)}"
        ) from e

    quality_raw = data.get("quality", {})
    quality_raw = quality_raw if isinstance(quality_raw, dict) else {}
    try:
        quality = QualityConfig(**quality_raw)
    except TypeError as e:
        valid = {f.name for f in dataclasses.fields(QualityConfig)}
        raise ConfigError(
            f"Unknown keys in 'quality' block: {e}. Allowed: {sorted(valid)}"
        ) from e

    effort_raw = data.get("effort")
    if effort_raw is None:
        effort: str | None = None
    else:
        effort_str = str(effort_raw)
        if effort_str not in _ALLOWED_EFFORT_VALUES:
            allowed = sorted(_ALLOWED_EFFORT_VALUES)
            raise ConfigError(
                f"Invalid value for 'effort': {effort_str!r}. Allowed: {allowed}."
            )
        effort = effort_str

    config = ProjectConfig(
        self_answer=self_answer,
        default_base=str(data.get("default_base", "main")),
        model=str(data.get("model", "claude-sonnet-4-6")),
        effort=effort,
        stage_overrides=stage_overrides,
        adapters=adapters,
        quality=quality,
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
    valid_fields = {f.name for f in dataclasses.fields(StageConfig)}
    patches = {k: v for k, v in overrides.items() if k in valid_fields}
    return replace(base, **patches)
