# 0005 — Prefect for orchestration; executor kept separate

- Status: accepted
- Date: 2026-07-09

## Context

Deployments are long-running, stateful workflows: canary stages, soak timers,
validation gates, commit-confirmed windows, rollback on failure. That is an
orchestration problem, and building retry/state machinery by hand is how
deployers become unmaintainable.

## Decision

- **Prefect** is the orchestrator. Rollout workflows are Prefect flows in
  `deployer/flows/`: stage progression, soak timers, validator gates,
  retries, human-in-the-loop pauses, abort handling.
- The **executor** is a pure Python library in `deployer/executor/`
  (transport adapters + vendor rollback semantics). It contains **no Prefect
  imports** and is fully testable against a containerlab device without any
  orchestrator running.
- The boundary: flows decide *sequence and reaction*; the executor performs
  *one device-level operation* (apply artifact, confirm commit, rollback,
  fetch diff) and returns evidence.

## Why the split matters

- Executor logic is reusable from `ibnctl` (manual, break-glass) and from
  tests, without standing up Prefect.
- Prefect can be swapped or upgraded without touching device-facing code.
- Vendor commit semantics get unit/integration tests independent of workflow
  timing.

## Consequences

- `deployer/` restructures to `flows/` (orchestration) + `executor/`
  (library) — replacing the earlier `workflows/` placeholder.
- Prefect server joins the platform stack in `infra/` (compose for lab;
  deployment target for prod tracked in the ADR backlog).
- Planner and validator invocations may also become Prefect flows later, but
  each remains an independently runnable Python package first.
