# a2factory

Process workflows for my own software work, driven from Claude Code / Claude Desktop over MCP.

**Status: pre-alpha, scaffold only.** No workflows written yet.

## What it is

A personal workflow platform. Not a product, not a framework — one user, one purpose: to be the thing I actually reach for when writing software, instead of raw Claude Code.

Two concrete demands motivate it:

1. Translating inputs into a scientific format.
2. Enforcing skills.

Everything else is speculative until a third demand shows up.

## How it will be built

Two workflows, written **deliberately duplicated** and run on real work. Whatever turns out identical between them becomes the substrate. The substrate is extracted, not designed — the duplication is the measuring instrument.

## Whether it works

One measure, fixed in advance:

> A commit to `a2web` produced through this platform. Seven consecutive days without one is a failure of the platform, and the response is a root-cause analysis — not a patch, and not abandonment.

The clock starts at the first such commit.

## Layout

```
src/a2factory/
  protocol/    rigid and small — units of work, states, ledger row, typed questions
  runtime/     the Claude Agent SDK harness
  server/      the MCP surface
  workflows/   workflow implementations
workflows/     workflow definitions, as data
ledger/        append-only run records
decisions/     build-time ADRs
```

The rule that decides where something goes: *if this changed next month, would existing ledger rows still be readable and comparable?* Yes → soft layer. No → protocol, and keep it small.

## Development

```sh
make bootstrap   # uv sync --all-extras
make check       # lint + types + tests
```

Python ≥3.11, `uv`, `ruff`, `ty`, `pytest`.

## Design

The design record lives in the knowledge base, not here: `~/Documents/Knowledge/Projects/160-ai-factory/`. Start from `handover-2026-08-03-build.md`. See `CLAUDE.md` for the working contract.

## License

Apache-2.0
