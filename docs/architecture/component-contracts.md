# Component Contracts

Each layer communicates through explicit, versioned data contracts — never by
reaching into another layer's internals. This file is the index of those
contracts; each contract gets its own schema once implementation starts.

## Contract map

```
Infrahub ──(config artifacts)──────────▶ planner ──(Plan)──▶ deployer
Infrahub ──(expectation artifacts)─────▶ validator
telemetry ──(normalized observed state)▶ validator
validator ──(compliance / drift report)▶ Infrahub, planner
deployer ──(execution report)──────────▶ validator, Infrahub
```

## 1. Config artifact (Infrahub → planner/deployer)

Produced by Infrahub artifact definitions (transform + template).

- Identity: device, artifact definition, Infrahub branch, storage checksum.
- Content: full rendered config (declarative, replace-style preferred).
- Guarantee: reproducible from (schema version, intent graph, SoT, transform
  version) — never hand-edited downstream.

## 2. Expectation artifact (Infrahub → validator)

Produced alongside config artifacts by a dedicated transform.

- Per device and/or per contract.
- Declares: expected sessions, expected routes/policies, required telemetry
  signals + freshness, forwarding constraints.
- Versioned with the same schema-versioning discipline as intent.

## 3. Plan (planner → deployer)

A declarative, reviewable document. Nothing executes without one.

- Ordered steps grouped into canary stages.
- Per-step: target device, artifact reference (checksum), transport, rollback
  strategy, validation checkpoint, abort criteria.
- Metadata: blast radius summary, policy evaluations, approvals required.

## 4. Execution report (deployer → validator/Infrahub)

- Per-step outcome: applied / rolled-back / aborted, timestamps, diffs actually
  committed, transport evidence.

## 5. Observed state (telemetry → validator)

- Normalized, vendor-neutral event/metric streams, enriched with SoT metadata
  (device role, region, tenant, contract).
- Freshness is part of the contract: stale data is itself a validation failure.

## 6. Compliance / drift report (validator → Infrahub/planner)

- Per expectation: pass / fail / stale, evidence pointers, drift class
  (benign / dangerous), remediation class (auto / quarantine / human).

## Rules

1. Contracts are versioned; consumers declare which versions they accept.
2. A contract change requires updating this doc + an ADR if breaking.
3. No layer bypasses a contract "temporarily". That's how warehouses start.
