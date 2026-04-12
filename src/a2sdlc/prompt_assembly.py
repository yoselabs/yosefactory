"""Prompt assembly — loads and concatenates stage prompt files."""

from __future__ import annotations

from importlib.resources import files as pkg_files
from pathlib import Path


def _read_if_exists(path: Path) -> str:
    """Read file contents if it exists, else return empty string."""
    if path.is_file():
        return path.read_text()
    return ""


def _sorted_md_files(directory: Path) -> list[Path]:
    """Return sorted list of .md files in directory."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def assemble_system_prompt(stage: str, a2sdlc_dir: Path) -> str:
    """Load and concatenate prompt files for a stage.

    Check project dir first (overrides), fall back to package-bundled prompts.
    """
    parts: list[str] = []

    project_prompts = a2sdlc_dir / "prompts"

    # Try to resolve package prompts directory.
    try:
        pkg_prompts_base = pkg_files("a2sdlc.prompts")
        pkg_prompts = Path(str(pkg_prompts_base))
    except (ModuleNotFoundError, TypeError):
        pkg_prompts = None

    # 1. system.md
    system_text = _read_if_exists(project_prompts / "system.md")
    if not system_text and pkg_prompts:
        system_text = _read_if_exists(pkg_prompts / "system.md")
    if system_text:
        parts.append(system_text)

    # 2. adapters/*.md (sorted)
    adapter_files = _sorted_md_files(project_prompts / "adapters")
    if not adapter_files and pkg_prompts:
        adapter_files = _sorted_md_files(pkg_prompts / "adapters")
    for f in adapter_files:
        content = f.read_text()
        if content:
            parts.append(content)

    # 3. stages/{stage}.md
    stage_text = _read_if_exists(project_prompts / "stages" / f"{stage}.md")
    if not stage_text and pkg_prompts:
        stage_text = _read_if_exists(pkg_prompts / "stages" / f"{stage}.md")
    if stage_text:
        parts.append(stage_text)

    return "\n\n".join(parts)
