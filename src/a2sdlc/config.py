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

_DEFAULT_TOOLS: list[str] = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Agent",
]


@dataclass
class StageConfig:
    """Configuration for a single pipeline stage."""

    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 20
    allowed_tools: list[str] = field(default_factory=lambda: list(_DEFAULT_TOOLS))


STAGE_DEFAULTS: dict[str, StageConfig] = {
    "spec": StageConfig(name="spec", max_turns=35, timeout_minutes=30),
    "implement": StageConfig(name="implement", max_turns=120, timeout_minutes=60),
    "review": StageConfig(
        name="review",
        max_turns=25,
        timeout_minutes=20,
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    ),
}

# Env-var name → StageConfig field name + converter
_ENV_MAP: dict[str, tuple[str, type]] = {
    "MODEL": ("model", str),
    "MAX_TURNS": ("max_turns", int),
}


def load_config(stage: str, **overrides: object) -> StageConfig:
    """Build a StageConfig by merging defaults, env vars, and CLI overrides.

    Priority: CLI arg > env var > stage default.
    """
    base = STAGE_DEFAULTS[stage]

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


def get_session_id(ticket_key: str, agent: str) -> str:
    """Deterministic UUID from ticket key + agent name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{agent}"))


# ── Project configuration ─────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Per-repo settings read from .a2sdlc/project.yaml."""

    tickets_adapter: str = "github-issues"
    code_adapter: str = "github"
    test_command: str = "make test"
    auto_merge: bool = False
    jira_status_map: dict[str, str] = field(default_factory=dict)


def load_project(project_root: Path) -> ProjectConfig:
    """Load project config from *project_root*/.a2sdlc/project.yaml.

    Returns defaults when the file is absent.
    """
    config_path = project_root / ".a2sdlc" / "project.yaml"
    if not config_path.exists():
        logger.info("No project config at %s — using defaults", config_path)
        return ProjectConfig()

    with config_path.open() as fh:
        data: dict[str, object] = yaml.safe_load(fh) or {}

    logger.info("Loaded project config from %s: %s", config_path, data)
    adapters = data.get("adapters", {})
    testing = data.get("testing", {})
    pipeline = data.get("pipeline", {})
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    return ProjectConfig(
        tickets_adapter=adapters.get("tickets", "github-issues")
        if isinstance(adapters, dict)
        else "github-issues",
        code_adapter=adapters.get("code", "github")
        if isinstance(adapters, dict)
        else "github",
        test_command=testing.get("command", "make test")
        if isinstance(testing, dict)
        else "make test",
        auto_merge=bool(pipeline.get("auto_merge", False)),
        jira_status_map=data.get("jira_status_map", {}),
    )
