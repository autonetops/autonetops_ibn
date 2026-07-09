# 0002 — Schema and artifact versioning policy

- Status: proposed
- Date: 2026-07-09

## Context

Intent evolves, vendors appear, compliance tightens. Without versioning we get
either a frozen model (nobody dares change it) or a chaotic one (consumers
break constantly). Infrahub versions schema state internally, but the
*contracts* consumed outside Infrahub — expectation artifacts, plan documents,
observed-state records — need explicit versions too.

## Decision (proposed)

1. Infrahub schemas in `infrahub/schemas/` carry a `version` and follow
   additive-first evolution; breaking changes require a migration note in
   `docs/runbooks/schema-migrations.md`.
2. Every cross-layer contract (see `docs/architecture/component-contracts.md`)
   embeds a `contract_version` field; consumers validate and declare accepted
   ranges.
3. Expectation artifacts are versioned independently of config artifacts —
   the validator must be able to evaluate expectations rendered by an older
   transform against current observed state during rollouts.

## Consequences

- Migration tooling becomes explicit (`tools/migration/`).
- CI must test the compatibility matrix, not just latest-on-latest.
