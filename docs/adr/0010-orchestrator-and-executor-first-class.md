# 0010 — Orchestrator and executor are first-class components, not deployer internals

- Status: accepted
- Date: 2026-07-11
- Refines: ADR-0005, ADR-0009 (decisions stand; component placement changes)

## Context

The NAF-style reference architecture treats **workflow orchestration** and the
**automation/execution engine** as two distinct roles. Our layout agreed in
substance (ADR-0005/0009: Prefect flows vs. executor library, two packages)
but bundled both under `deployer/`, implying execution is a detail of
deployment. Two observations broke that framing:

1. **Orchestration is not deploy-specific.** The reconciliation loops
   (ADR-0004), drift remediation (validator → re-deploy), simulation gates,
   and tenant onboarding are all workflows. Hiding the workflow engine inside
   `deployer/` guarantees a second, ad-hoc orchestration pattern grows
   elsewhere.
2. **Execution is not deploy-specific either.** The same southbound layer
   that pushes config also takes snapshots, runs dry-runs for the planner,
   and fetches operational facts for the validator. And it is the hardest
   asset to build (the driver matrix) — burying it undersells it.

## Which architecture is easier to implement / to sell / to scale?

| | Bundled ("deployer owns both") | Separated (orchestrator + executor) |
|---|---|---|
| Fastest first demo | ✅ Marginally — one package, one deploy | ⚠️ Two components to wire |
| Second workflow (remediation, onboarding) | ❌ Duplicated orchestration or awkward imports | ✅ New flow, same engine |
| Sellability | ❌ Monolith: buyer takes all or nothing | ✅ Executor = the moat (driver matrix + evidence); orchestrator = commodity, even swappable for the customer's own |
| Scaling teams | ❌ One codebase, all concerns | ✅ Driver contributors never touch workflow code |
| Cost of separating **today** | — | ✅ ~Zero: no executor code exists yet |

Bundling is only cheaper on day one, and day one is now — so we pay the
(near-zero) separation cost now rather than a migration later.

## Decision

`deployer/` is dissolved into two top-level components:

```
orchestrator/          # the workflow role (Prefect = implementation detail)
  flows/
    deploy/            # plan rollout: stages, soak, gates, abort
    reconcile/         # the "reconciliation guarantees" loops (ADR-0004)
    remediate/         # validator-proposed safe fixes -> new plan proposals
    onboard/           # device/tenant onboarding workflows

executor/              # the execution-layer role (southbound)
  drivers/             # platform drivers implementing the executor verbs (ADR-0011)
  transports/          # gnmi / netconf / ssh / http primitives drivers compose
  tests/
```

Rules carried over unchanged: flows consume the executor **only through its
public API** (ADR-0009); the executor has no orchestrator imports; service
promotion triggers from ADR-0009 still apply — and in product mode the
executor-as-gateway promotion is expected to fire early (credential
isolation).

## Consequences

- All prose that said "deployer" now means "orchestrator (deploy flow) +
  executor". The Plan contract is unchanged by *this* ADR (ADR-0011 changes
  it for target modeling).
- Vendor transactional semantics (`rollback/`) move inside each driver —
  rollback is a driver capability, not a shared directory (see ADR-0011).
- `docs/runbooks/deployer.md` (planned) splits into `orchestrator.md` and
  `executor.md`.
