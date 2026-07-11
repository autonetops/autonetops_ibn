# verifications/

Active checks, declared as data (YAML) + probe implementations where needed.

- `scenarios/` — suites derived from testing scenarios, per contract or per
  incident. Naming: `<domain>-<subject>.yaml` (e.g. `routing-custc-no-leak.yaml`).
- `invariants/` — global always-true checks derived from intent/SoT schema
  rules (redundancy floors, no-leak classes, prefix bounds, telemetry
  freshness).

Declaration shape (schema TBD with the first implementation — will live in
`contracts/verification/v1/`):

```yaml
# sketch, not final
name: custc-no-leak
derives_from: infrahub://RoutingContract/custc-ce-to-pe   # traceability is mandatory
triggers: [post_deploy, nightly]
probes:
  - kind: route_absent
    where: { role: pe, region: any }
    prefix_set: custc-prefixes
    table: internet
evidence: [rib_snapshot, probe_log]
on_fail:
  remediation_class: quarantine     # safe_fix | quarantine | escalate
```

Rules:

1. Every verification names the intent object it derives from — no orphan
   checks.
2. Verifications only read (executor read verbs / telemetry queries).
3. A verification that cannot run in a simulations/ topology needs a
   documented reason.
