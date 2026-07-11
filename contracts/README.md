# contracts/

Generated JSON Schemas for the cross-layer contracts described in
`docs/architecture/component-contracts.md`.

**Do not edit these by hand.** The canonical definitions are pydantic models
in the owning component (ADR-0007); schemas here are exported and CI-checked
for drift.

| Contract | Version | Source of truth | Export command |
|---|---|---|---|
| Plan | v1 | `planner/src/autonetops_planner/models.py` | `autonetops-planner export-schema` |

Upcoming: expectation artifact (infrahub transform), execution report
(executor), compliance report (validator).
