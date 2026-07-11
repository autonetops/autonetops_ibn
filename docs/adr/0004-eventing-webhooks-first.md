# 0004 — Inter-layer eventing: webhooks first, broker later

- Status: accepted
- Date: 2026-07-09

## Context

The layers need triggers: intent merged → run planner; plan merged → run
deployer; deployment finished → run validator. Options were direct webhooks
vs. a message broker (NATS/Kafka) from day one.

## Decision

**Webhooks first.**

- Infrahub webhooks (proposed change merged / artifacts regenerated) →
  trigger a planner run.
- Git webhooks (plan PR merged) → trigger the Prefect deployment flow.
- Prefect flow completion → trigger validator evaluation (in-flow task or
  webhook).

With one hard rule that keeps this honest:

> **Webhooks trigger; reconciliation guarantees.**

Every consumer must also run a periodic reconciliation loop (e.g. planner
scans for merged-but-unplanned changes; deployer scans for merged-but-unrun
plans). A missed webhook may delay the loop, never break it.

## Revisit trigger (move to a broker, likely NATS)

- More than one consumer needs the same event (fan-out), or
- We need replay/event history, or
- Telemetry pipelines need a streaming bus anyway (likely — at that point
  reuse it for control events too).

## Consequences

- Zero new infrastructure now; Prefect's API is the only webhook target
  besides the planner's.
- Reconciliation intervals become part of each component's config and
  their runbooks.
- Event payloads must carry only references (branch names, plan IDs,
  checksums) — never content — so the switch to a broker later is a
  transport change, not a contract change.
