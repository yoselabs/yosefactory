---
title: "<Eval plan title>"
type: eval
status: Draft
owner: "@<owner>"
created: YYYY-MM-DD
updated: YYYY-MM-DD
spec: null      # the spec this evaluates
baseline_run: null   # MLflow run URL of baseline
---

# Eval: <title>

## Hypothesis

What change are we making, and why do we think it improves outcomes? Phrase as a falsifiable statement.

> "Changing <X> in the <stage> prompt will reduce <metric> by at least <N%> on our fixture set, without degrading <other metric> by more than <M%>."

## Metrics

Primary metrics (must improve or hold):

- **<metric-1>** — definition, measurement source (MLflow tag / derived).
- **<metric-2>** — …

Guard metrics (must not degrade):

- **<metric-3>** — …

## Fixture set

Which tickets / scenarios we run this against. Link to the fixture monorepo (per project plan) or list them inline.

| Fixture | Description | Why included |
|---|---|---|
| F-01 | … | … |

## Baseline

The run to compare against. Link to MLflow URL or run ID. State the baseline metric values here so the plan is self-contained.

## Experimental runs

How we'll run the experiment. Include:
- Number of runs per condition (seed variance).
- Random seed policy.
- Parallelism isolation (per `feedback_parallel_runs`).

## Pass criteria

Concrete thresholds. The hypothesis is accepted if:

- Primary metric(s) improved by at least <N%> with p < 0.05.
- No guard metric degraded by more than <M%>.

## Rollback criteria

If post-merge metrics drift, under what conditions do we revert?

## Analysis

Filled in after runs complete:

- Observed metric deltas.
- Statistical significance.
- Decision: accept / reject / inconclusive.
- Links to MLflow dashboards.

## Links

- Spec being evaluated: …
- Baseline MLflow run: …
- Experiment MLflow runs: …
