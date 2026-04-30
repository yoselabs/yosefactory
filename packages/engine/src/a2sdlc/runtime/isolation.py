"""Agent-process isolation. Spec §Agent isolation.

The engine pins what reaches the Claude Agent SDK so the operator's
shell environment, ``~/.claude/CLAUDE.md`` auto-memory, MCP servers,
and plugins do not bleed into agent behaviour.

Two surfaces:

* :func:`build_sdk_env` — returns a curated env dict (baseline POSIX
  vars + explicitly-required names). ``CLAUDE_CONFIG_DIR`` and
  ``CLAUDE_HOME`` are stripped with a warning so an operator cannot
  redirect the SDK at a custom config tree.
* :func:`build_sdk_options_overrides` — returns the
  ``ClaudeAgentOptions`` kwargs the engine forces regardless of what
  the call site set: ``setting_sources=["project", "local"]`` and
  ``mcp_servers=[]``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2sdlc.runtime.isolation")

_BASELINE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ")
_FORBIDDEN_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_HOME")


def build_sdk_env(
    source_env: dict[str, str],
    *,
    required_env_names: set[str],
) -> dict[str, str]:
    """Return a curated env for SDK / agent subprocesses.

    Only baseline POSIX vars and explicitly-required names pass
    through. ``CLAUDE_CONFIG_DIR`` / ``CLAUDE_HOME`` are dropped with
    a warning — the engine controls SDK config location.
    """
    out: dict[str, str] = {}
    for name in _BASELINE_ENV:
        if name in source_env:
            out[name] = source_env[name]
    for name in required_env_names:
        if name in source_env:
            out[name] = source_env[name]
    for name in _FORBIDDEN_ENV:
        if name in source_env:
            logger.warning(
                "ignoring %s=%s; engine controls SDK config",
                name,
                source_env[name],
            )
    return out


def build_sdk_options_overrides() -> dict[str, Any]:
    """Return ``ClaudeAgentOptions`` kwargs the engine forces.

    Applied *after* call-site kwargs so the engine wins.
    """
    return {
        "setting_sources": ["project", "local"],
        "mcp_servers": [],
    }
