# Adapter: Claude Code

You are running inside Claude Code with the following capabilities.

## Skills (Skill tool)

Invoke Superpowers skills when available:

- `brainstorming` — explore requirements and design before implementation
- `writing-plans` — structured planning from requirements
- `subagent-driven-development` — parallel task execution with fresh subagents
- `test-driven-development` — TDD workflow (red-green-refactor)
- `systematic-debugging` — root cause investigation before fixing
- `requesting-code-review` — dispatch code-reviewer subagent for quality checks
- `verification-before-completion` — verify all claims before reporting done

## Subagents (Agent tool)

Spawn subagents for independent parallel work.
Subagents cannot spawn sub-subagents — keep parallelism one level deep.

## Bash

Full shell access: run tests, linters, Docker, git, and any CLI tools.

## File Tools

- **Read** — read file contents
- **Write** — create or overwrite files
- **Edit** — surgical string replacements
- **Glob** — find files by pattern
- **Grep** — search file contents with regex

## Web

- **WebFetch** — fetch a URL
- **WebSearch** — search the web
