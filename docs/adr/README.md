# Architecture Decision Records

Every non-obvious, hard-to-reverse decision gets an ADR. Future maintainers
will see something weird, be tempted to "clean it up", and need the incident
history / reasoning that shaped it.

## Format

```
# NNNN — Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
```

## Index

| # | Title | Status |
|---|-------|--------|
| 0001 | Infrahub owns schema, intent, SoT, compiler and renderer | accepted |
| 0002 | Schema and artifact versioning policy | proposed |
| 0003 | Plan storage and approval: Git PRs under `plans/` | accepted |
| 0004 | Eventing: webhooks first, broker later (reconciliation guarantees) | accepted |
| 0005 | Prefect for orchestration; executor kept separate | accepted |
| 0006 | Telemetry collection: gnmic primary, telegraf for legacy gaps | accepted |
| 0007 | Python as the platform implementation language | accepted |
| 0008 | Device interaction: typed per-transport libraries, not a runner framework | accepted |
| 0009 | Deployer split: two packages now, executor service later if needed | accepted, refined by 0010 |
| 0010 | Orchestrator and executor are first-class components (NAF alignment) | accepted |
| 0011 | Southbound target model: control points and driver capabilities | accepted |
| 0012 | Protocol preference order for delivery strategy selection | accepted |
| 0013 | Orchestrator flow: SoT change windows, timeline evaluation, dispatch decision | accepted |
| 0014 | Pre-approved plan classes: auto-approval as reviewed policy | proposed |

## Backlog (decisions we know we owe)

- Telemetry storage backend (Prometheus/Mimir vs. ClickHouse vs. TSDB mix)
- Platform deployment target and promotion path (compose → k8s) — confirm prod target
- Secrets management for device credentials (deployer + collectors)
- Monorepo vs. split-out intent repos (revisit when >1 team owns intent)
- Plan-PR automation details (bot identity; auto-approve rules decided in ADR-0014)
