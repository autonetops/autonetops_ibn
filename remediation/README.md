# remediation/

The **content library** for closing the loop: what to actively verify, and
what to do when verification or drift detection fails. The engines live
elsewhere — the validator classifies, the orchestrator triggers, the executor
probes — this directory holds the *reviewable knowledge* they act on.

```
remediation/
  verifications/       # ACTIVE checks — probe the network, don't just watch it
    scenarios/         # scenario suites derived from testing scenarios & incidents
    invariants/        # always-true checks derived from intent contracts in SoT
  playbooks/           # what happens on failure, by remediation class
    safe_fixes/        # auto-proposable: re-deploy authoritative artifact, clear session
    quarantines/       # contain, don't touch: isolate + evidence capture + ticket
    escalations/       # human-required: paging rules, context bundles
```

## Active verification vs. passive validation

Two complementary mechanisms, deliberately separate:

| | Passive validation (`validator/`) | Active verification (here) |
|---|---|---|
| Driven by | Telemetry streams (continuous) | Orchestrator flows (triggered) |
| Answers | "Does observed state match expectations?" | "Does the network actually behave as the contract promises?" |
| Examples | BGP session count matches, policy attached | Probe reachability across a contract, verify a route is actually installed and forwarding, assert an invariant end-to-end |
| When | Always on | Post-deploy gates, scheduled audits, on-demand (ibnctl), after incidents |

## Where verifications come from — the derivation chain

Every verification traces to something declared in Infrahub, never invented
here:

1. **Contracts** (routing contracts, tenant intents) → per-contract scenario
   suites in `verifications/scenarios/` ("customer-c CE routes reachable from
   PE canary set", "no leak into forbidden target class").
2. **Invariants** (schema-level rules: redundancy floors, no-leak, prefix
   bounds) → checks in `verifications/invariants/` that hold for *every*
   tenant, always.
3. **Incidents** → new scenario here + a golden topology in `simulations/`
   (the same scenario runs in the lab as a CI gate and in production as a
   verification).

A verification declares: what it probes, which intent object it derives from,
required evidence, pass/fail criteria, and the remediation class on failure.

## Execution model

- The **orchestrator** (`orchestrator/flows/verify/`) runs suites: post-deploy
  (the Plan's stage gates reference suites by name), scheduled (nightly
  invariant sweep), and on-demand.
- Probes reach the network only through **executor** read verbs
  (`get_facts`, telemetry queries) — verifications never write.
- On failure: the matching playbook class fires. `safe_fixes/` may *propose a
  Plan* (never push directly — ADR-0003 applies to remediation too);
  `quarantines/` contain and collect; `escalations/` page with context.

## Status

🚧 Structure + conventions only. First content lands with the first
containerlab scenario (simulations/) so every verification is born testable.
