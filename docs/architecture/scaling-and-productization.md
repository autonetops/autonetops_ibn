# Does this design scale — and can it become a product?

An honest assessment, kept current as the platform evolves. Short version:
**the architecture scales and is product-viable; the current *conveniences*
are not, and they were chosen with their replacements already named.**

## What holds at scale (the load-bearing decisions)

1. **Versioned data contracts between layers** (`contracts/`, pydantic-first).
   Every layer is a pure function over documents — planner, validator, and
   executor can be scaled horizontally, replaced, or exposed as services
   without renegotiating semantics.
2. **The artifact boundary** (ADR-0001). Everything downstream consumes
   checksummed artifacts, not live intent. That gives reproducibility,
   caching, and a natural multi-instance story (N Infrahubs, one platform).
3. **Plan as a first-class document.** Approval, execution, audit and
   rollback all hang off one serializable object. This is the single most
   product-shaped decision in the repo: a UI, an API, and an approval
   workflow are all *views over Plans*.
4. **Policies as data** (planner/policies). Per-customer policy packs are a
   packaging exercise, not a code fork.
5. **Executor with promotion triggers** (ADR-0009). The path from library →
   device gateway service is pre-designed; multi-tenant credential isolation
   has a slot to land in.
6. **Vendor knowledge quarantined** in templates + adapters + rollback.
   Supporting a new NOS is additive; the support matrix can grow per-customer
   without destabilizing the core.

## What does NOT survive productization (by design — replacements named)

| Today's convenience | Fine until | Product replacement |
|---|---|---|
| Plans as Git PRs (ADR-0003) | ~10 plans/day, single org | Plan API + approval UI; storage moves to DB/Infrahub, contract unchanged |
| Webhooks + reconciliation (ADR-0004) | >1 consumer per event | Broker (NATS/Kafka); payloads already reference-only, so transport swap |
| CODEOWNERS as approval engine | Single GitHub org | RBAC in the plan-approval service |
| One shared platform stack | Single tenant | Per-tenant stacks via the Terraform project factory (`for_each` over a tenant map — Stage 4 in infra/terraform/README.md) |
| Monorepo for everything | One team | Platform monorepo stays; per-tenant intent lives in each customer's Infrahub; policy packs versioned as artifacts |

## The genuinely hard product problems (no free lunch)

- **Multi-tenancy model**: dedicated Infrahub per tenant (isolation, simpler
  compliance, higher COGS) vs shared (efficient, hard blast-radius story).
  Start dedicated; revisit only with strong evidence.
- **Support matrix economics**: every (NOS, feature) pair carries golden
  tests + simulation coverage forever. The matrix must be priced, not just
  engineered.
- **Trust bootstrapping**: customers hand over router credentials. The
  executor-as-service chokepoint (ADR-0009 level 3), full evidence trails,
  and read-only/dry-run onboarding modes stop being nice-to-haves.
- **Day-2 of the platform itself**: upgrades of Infrahub/Prefect underneath
  running control loops; the promotion pipeline in infra/ is the rehearsal.
- **Licensing**: verify Infrahub's license/commercial terms for embedding in
  a paid offering before any product commitment (also true for chart
  dependencies). Legal check, not an engineering one — do it early.

## Scaling dimensions checklist

- **Devices**: planner/validator are stateless over documents — scale out.
  Telemetry is the real axis (collector sharding via gnmic clustering,
  storage retention design — ADR backlog).
- **Teams**: domain-split rules/policies + CODEOWNERS already map to
  ownership; intent partitioning is Infrahub-side (branches, permissions).
- **Vendors**: additive by construction (templates/adapters/rollback).
- **Regions/tenants**: Terraform project factory + per-tenant platform
  stacks; plans and telemetry are already tagged with region/tenant fields.
