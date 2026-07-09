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

## Backlog (decisions we know we owe)

- Plan document schema and storage/approval workflow
- Inter-layer eventing: Infrahub webhooks vs. message broker (NATS/Kafka)
- Telemetry storage backend (Prometheus/Mimir vs. ClickHouse vs. TSDB mix)
- Platform deployment target and promotion path (compose → k8s)
- Secrets management for device credentials (deployer + collectors)
- Monorepo vs. split-out intent repos (revisit when >1 team owns intent)
