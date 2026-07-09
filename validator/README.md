# validator/

Where intent becomes **enforceable**. The validator compares expectation
artifacts (from Infrahub) against observed state (from telemetry) and produces
compliance/drift reports that feed back into Infrahub and the planner.

```
validator/
  src/
  rules/             # domain-oriented compliance rules
    routing/
    security/
    reachability/
    reliability/
  drift/             # drift classification (benign vs dangerous) + diff engine
  remediation/       # what may be auto-fixed vs quarantined vs escalated
    safe_fixes/
    quarantines/
    playbooks/
  tests/
```

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
3. Stale telemetry ⇒ "unknown", never silently "pass".
