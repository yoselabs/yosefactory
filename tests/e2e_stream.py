"""E2E test: verify SDK streaming produces tool calls and rich output.

Run manually: .venv/bin/python tests/e2e_stream.py
Requires CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in env.
"""

import asyncio
import sys

from a2sdlc.config import StageConfig
from a2sdlc.runner import run_stage


async def main():
    progress_calls: list[str] = []

    def on_progress(text: str) -> None:
        progress_calls.append(text)
        print(f"\n📊 Progress update #{len(progress_calls)}:")
        print(text)
        print()

    config = StageConfig(name="spec", max_turns=5, timeout_minutes=2)

    result = await run_stage(
        user_prompt="List the Python files in the src/ directory and count them.",
        system_prompt=(
            "You are a test agent. Use tools to complete the task. "
            'End with:\n```a2sdlc\n{"status": "complete"}\n```'
        ),
        config=config,
        ticket_key="TEST-1",
        stage="spec",
        project_root=".",
        on_progress=on_progress,
    )

    print("\n" + "=" * 60)
    print("RESULT:")
    print(f"  success:    {result.success}")
    print(f"  error:      {result.error}")
    print(f"  cost:       ${result.total_cost_usd:.4f}")
    print(f"  tokens in:  {result.input_tokens}")
    print(f"  tokens out: {result.output_tokens}")
    print(f"  turns:      {result.num_turns}")
    print(f"  tools:      {len(result.tool_log)}")
    print(f"  tool log:   {result.tool_log}")
    print(f"  output:     {result.output[:300]}")
    print(f"  progress:   {len(progress_calls)} updates")

    # Assertions
    ok = True
    if not result.success:
        print("\n❌ FAIL: result.success is False")
        ok = False
    if result.total_cost_usd == 0:
        print("\n❌ FAIL: cost is 0")
        ok = False
    if result.input_tokens == 0:
        print("\n❌ FAIL: input_tokens is 0")
        ok = False
    if len(result.tool_log) == 0:
        print("\n❌ FAIL: no tool calls detected")
        ok = False
    else:
        print(f"\n✅ PASS: {len(result.tool_log)} tool calls detected")

    if ok:
        print("\n✅ ALL CHECKS PASSED")
    else:
        sys.exit(1)


asyncio.run(main())
