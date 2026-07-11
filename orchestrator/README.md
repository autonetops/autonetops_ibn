# orchestrator/

The **workflow role** (ADR-0010): every long-running, stateful process in the
closed loop lives here as a Prefect flow. Prefect is an implementation detail
— flows consume and emit platform contracts (`contracts/`) only, and call the
executor exclusively through its public API (ADR-0009).

```
orchestrator/
  flows/
    deploy/      # Plan rollout: stage progression, soak timers, validator gates, abort
    verify/      # run verification suites from remediation/verifications/:
                 #   post-deploy (stage gates), scheduled (nightly invariant sweep),
                 #   on-demand (ibnctl). Read-only against the network.
    reconcile/   # "webhooks trigger, reconciliation guarantees" loops (ADR-0004):
                 #   merged-but-unplanned changes, merged-but-unrun plans
    remediate/   # executes remediation/playbooks/ by class: safe fixes propose
                 #   plan PRs (never direct pushes), quarantines contain + collect
    onboard/     # device / control-point / tenant onboarding workflows
```

## Rules

1. Flows never talk to devices — only the executor does (ADR-0010/0011).
2. Flows never decide *what* changes (Infrahub) or *whether it's safe*
   (planner + approved Plan). They decide *sequence and reaction*.
3. Every flow is idempotent and resumable: re-running a partially completed
   rollout must be safe (the executor's evidence tells it where it stopped).
4. Package: `autonetops-orchestrator-flows`, depends on `autonetops-executor`.
