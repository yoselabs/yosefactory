# 0003 — Name the measurement package `evaluation/`, not `telemetry/`

- **Status:** Accepted
- **Date:** 2026-04-18

## Context

The codebase had two modules measuring run outcomes: `progress.py` (live run
tracking, formatting for stage comments) and `stats.py` (cost/tokens/duration
accumulation per run). Both were flat at `src/a2sdlc/` root.

During reorganization we grouped them into one package. Natural candidate names:
`telemetry/`, `metrics/`, `observability/`, `evaluation/`.

## Decision

Name the package **`evaluation/`**.

## Consequences

- `src/a2sdlc/evaluation/` holds `progress.py` and `stats.py` today.
- Future scorers, run comparisons, A/B-test harnesses, and MLflow integration
  land here without rename. These are planned capabilities central to the
  product's value proposition ("measurable prompt iteration on real tickets").
- `telemetry/` would imply passive ops observability (metrics exported to
  Prometheus, logs shipped to ELK) and mis-signal the package's purpose to
  anyone arriving from an SRE/ops background.
- `evaluation/` signals judgment: "did this run do better than the last?" —
  which is what the product is for.

## Alternatives considered

- **`telemetry/`.** Rejected: connotes ops observability. Wrong product framing.
- **`metrics/`.** Rejected: too generic; same framing problem as telemetry.
- **`observability/`.** Rejected: neutral but imports an SRE ontology (logs,
  metrics, traces) that doesn't fit agent-run scoring.
- **Split into `progress/` + `stats/`.** Rejected: two tiny packages where one
  does the job.

## Related

- `docs/architecture.md §3` — the naming rule (folders name product concerns,
  not technical concerns).
