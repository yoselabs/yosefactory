"""Runner — Claude CLI wrapper with session management."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from a2sdlc.config import StageConfig

logger = logging.getLogger("a2sdlc.runner")


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, agent: str) -> str:
    """Deterministic UUID from ticket key + agent name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{agent}"))


def get_session_path(session_id: str, cwd: str) -> Path:
    """Where Claude stores session JSONL."""
    escaped = cwd.replace("/", "-").lstrip("-")
    return Path.home() / ".claude" / "projects" / escaped / f"{session_id}.jsonl"


def _project_session_dir(ticket_key: str, agent: str, project_root: str) -> Path:
    return Path(project_root) / ".a2sdlc" / "sessions" / ticket_key / agent


def save_session(ticket_key: str, agent: str, cwd: str, project_root: str) -> None:
    """Copy session JSONL from Claude's storage to project sessions dir."""
    session_id = get_session_id(ticket_key, agent)
    src = get_session_path(session_id, cwd)
    if not src.exists():
        logger.debug("No session file to save at %s", src)
        return

    dest_dir = _project_session_dir(ticket_key, agent, project_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.jsonl"
    shutil.copy2(str(src), str(dest))
    logger.info("Saved session %s → %s", src, dest)


def restore_session(ticket_key: str, agent: str, cwd: str, project_root: str) -> bool:
    """Copy session from project sessions dir to Claude's storage.

    Returns True if restored, False if no session found.
    """
    session_id = get_session_id(ticket_key, agent)
    src_dir = _project_session_dir(ticket_key, agent, project_root)
    src = src_dir / f"{session_id}.jsonl"
    if not src.exists():
        logger.debug("No saved session at %s", src)
        return False

    dest = get_session_path(session_id, cwd)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest))
    logger.info("Restored session %s → %s", src, dest)
    return True


# ── Command building ─────────────────────────────────────────────────


def build_claude_cmd(
    ticket_key: str,
    agent: str,
    config: StageConfig,
    system_prompt_file: str,
    is_resume: bool = False,
) -> list[str]:
    """Build the ``claude -p`` command list."""
    sid = get_session_id(ticket_key, agent)
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        config.model,
        "--max-turns",
        str(config.max_turns),
        "--permission-mode",
        "bypassPermissions",
        "--append-system-prompt-file",
        system_prompt_file,
        "--allowedTools",
        ",".join(config.allowed_tools),
    ]
    if is_resume:
        cmd.extend(["--resume", sid])
    else:
        cmd.extend(["--session-id", sid])
    return cmd


# ── Result parsing ───────────────────────────────────────────────────

_SUBTYPE_ERROR_MAP: dict[str, str] = {
    "error_max_turns": "max_turns",
    "error_max_budget_usd": "budget",
}


def parse_result(raw_stdout: str) -> dict[str, object]:
    """Parse Claude's JSON output into a normalized result dict."""
    try:
        data = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        logger.error("Failed to parse Claude output as JSON: %.200s", raw_stdout)
        return {
            "success": False,
            "output": "",
            "error": "json_parse",
            "session_id": "",
            "raw": {},
        }

    subtype = data.get("subtype", "")
    result_text = data.get("result")
    session_id = data.get("session_id", "")

    error = _SUBTYPE_ERROR_MAP.get(subtype)
    success = subtype == "success" and result_text is not None

    return {
        "success": success,
        "output": result_text or "",
        "error": error,
        "session_id": session_id,
        "raw": data,
    }


# ── Main orchestrator ────────────────────────────────────────────────


def run_claude(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    agent: str,
    project_root: str,
) -> dict[str, object]:
    """Run Claude CLI with session management.

    1. Restore session (if exists)
    2. Write system prompt to temp file
    3. Build command
    4. Run subprocess with stdin=user_prompt, cwd=project_root
    5. Parse result
    6. Save session (always, even on failure)
    7. Clean up temp file
    8. Return parsed result
    """
    cwd = project_root
    is_resume = restore_session(ticket_key, agent, cwd, project_root)

    sid = get_session_id(ticket_key, agent)
    logger.info(
        "Running Claude: ticket=%s agent=%s session=%s resume=%s",
        ticket_key,
        agent,
        sid,
        is_resume,
    )

    # Write system prompt to a temp file.
    result: dict[str, object] = {}
    tmp_file = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix="a2sdlc-sysprompt-",
            delete=False,
        )
        tmp_file.write(system_prompt)
        tmp_file.close()

        cmd = build_claude_cmd(
            ticket_key, agent, config, tmp_file.name, is_resume=is_resume
        )
        logger.info("Command: %s", _redact_cmd(cmd))

        timeout_seconds = config.timeout_minutes * 60

        try:
            proc = subprocess.run(
                cmd,
                input=user_prompt,
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=timeout_seconds,
            )
            result = parse_result(proc.stdout)
            logger.info(
                "Claude finished: success=%s error=%s output_len=%d",
                result["success"],
                result["error"],
                len(str(result["output"])),
            )
        except subprocess.TimeoutExpired:
            logger.error("Claude timed out after %d minutes", config.timeout_minutes)
            result = {
                "success": False,
                "output": "",
                "error": "timeout",
                "session_id": sid,
                "raw": {},
            }
    finally:
        # Always save session (partial sessions are valuable).
        save_session(ticket_key, agent, cwd, project_root)

        # Clean up temp file.
        if tmp_file is not None:
            Path(tmp_file.name).unlink(missing_ok=True)

    return result


def _redact_cmd(cmd: list[str]) -> list[str]:
    """Return a copy of the command with sensitive values redacted."""
    # Currently nothing to redact, but future-proofed for tokens/keys.
    return list(cmd)
