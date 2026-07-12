# validator/

Where intent becomes **enforceable**. The validator compares expectation
artifacts (from Infrahub) against observed state and produces verdicts that
gate rollouts and feed back into Infrahub and the planner.

```
validator/
  src/autonetops_validator/
    models.py        # ExpectationSet (parses ContractExpectations), verdicts
    gate.py          # evaluate_sessions: the runtime half of
                     #   validator.expectations_pass (ADR-0013)
  rules/             # domain-oriented compliance rules (passive, telemetry-driven)
    routing/
    security/
    reachability/
    reliability/
  drift/             # drift classification (benign vs dangerous) + diff engine
  tests/
```

The first shipped gate is BGP-session expectations: the orchestrator's
dispatch collects `bgp_neighbors` facts through the executor verb contract
and this package turns them into pass / fail / **unverifiable** verdicts per
stage. Telemetry-driven continuous evaluation (Prometheus evidence) extends
the same models.

The validator is the passive half of proving intent: continuous evaluation of
expectations against telemetry. Its complement is **active verification** —
probe-based suites in `remediation/verifications/`, triggered by
`orchestrator/flows/verify/`. On failure, both select a remediation class
whose playbooks live in `remediation/playbooks/` (the content moved there so
verification and remediation knowledge has one home).

## A good finding is not "non-compliant"

Every validator result must state:

- **What invariant failed** (which expectation, which contract)
- **What evidence supports it** (telemetry pointers, freshness)
- **What the blast radius is**
- **What remediation class applies** (auto / quarantine / human)

That's how we prevent alert fatigue and earn trust.

## Design rules

1. Rules are organized by **domain** (routing/security/…), mirroring intent
   ownership — domain owners review their rules.
2. Auto-remediation never bypasses the planner: a safe fix *proposes a Plan*
   (typically re-deploying the authoritative artifact), it does not push.
   Remediation classes and playbooks are defined in `remediation/playbooks/`.
3. Stale telemetry ⇒ "unknown", never silently "pass".
