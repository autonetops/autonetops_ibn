# deployer/

The deployer **executes a Plan and nothing else**. It never decides *what*
to change (Infrahub) or *whether/when* it is safe (planner). Input: a Plan
document. Output: an execution report.

Orchestration and execution are **separate by decision** (ADR-0005), and
separated as **two Python packages** (ADR-0009): `autonetops-deployer-flows`
depends on `autonetops-executor` only through its public API. The executor is
promotable to a standalone device-gateway service later (credential isolation,
session brokering) without moving anything else. Transport libraries:
pygnmi / ncclient / scrapli, vendor SDKs inside rollback modules (ADR-0008).

```
deployer/
  flows/             # pkg autonetops-deployer-flows: Prefect flows — stages, soak, gates, abort
  executor/          # pkg autonetops-executor (no Prefect imports): apply/confirm/rollback/diff
  adapters/          # transport isolation — one directory per protocol
    gnmi/
    netconf/
    ssh/
    vendor_api/
  rollback/          # vendor transactional semantics, isolated and tested
    # junos: commit confirmed
    # iosxr: commit confirm / commit replace caveats
    # eos:   checkpoints
  tests/
```

Input: a merged Plan (`contracts/plan/v1`). Trigger: plan-PR merge webhook →
Prefect deployment (ADR-0004). The executor is also callable from `ibnctl`
for the documented break-glass path — same code, no orchestrator required.

## Design rules

1. **Rollback is a first-class concept**, not an afterthought. Vendor commit
   semantics live in `rollback/`, tested independently — never sprinkled
   through workflow code.
2. **Adapters isolate transports.** Workflow logic must not know whether a
   device speaks gNMI or NETCONF.
3. **Every step is gated.** The deployer halts a canary stage when the Plan's
   validation checkpoint fails, and executes the step's rollback strategy.
4. **Evidence out.** Every step emits what was actually committed (diffs,
   timestamps, transport-level proof) for the validator and audit trail.
5. Device write credentials exist **only** here (secrets design: ADR backlog).
