# Model vs code: what is built, what is owed

Checked 2026-11-21 against `IBN` 0384be2 and `IH` 2e16a3b. Every line names the file to look
at, so re-verify before relying on it. Where code or seed data disagrees with the model, the
model is the convention and the code is unfinished. Don't copy the existing pattern.

Per-kind state (which kinds compile, which invariants have a projection) is in
[primitives.md](primitives.md). Names that disagree with the conventions are in
[naming.md](naming.md).

Contents: 1. built end to end · 2. owed, by layer · 3. docs that lag · 4. suggested build order

## 1. Built end to end

- Routing contract → device config (five platform renderers) + `ContractExpectations` → stage
  gate on BGP session state, with baseline.
- Observability contract + signals → telegraf inputs, Prometheus rules, Grafana dashboard.
- Security contract → ACL config.
- Merge projections for `no_leak`, `prefix_authorization`, `capability_present`.
- Change windows in the SoT; the policy pack (blast radius, canary strategies, change classes
  with golden fixtures, approvals, rollback); dispatch re-verification; emergency override;
  `OpsPlanRecord` feedback.

## 2. Owed, by layer

### Schema and seed data

- **Platform generics trail the lab schema.** `IBN/infrahub/schemas/intent_model.yml` has no
  `IntentDefinition.tenant` or `ticket`, no `IntentTenant` / `IntentZone` / `IntentCapability`,
  and no typed invariant kinds. `IH/schemas/intent.yml` has all of them.
- **The seed slices one customer outcome into five intents**, one per former realm
  (`IH/scripts/bootstrap.py`). `custc-apps-reachable` contradicts "reachability is an objective
  kind", and `custc-service-assurance` contradicts "per-service observability rides the service
  intent". `custc-resilience` has the same owner and priority as `custc-l3vpn-connectivity`, so
  by the slicing rule it is a contract of that intent. The target shape is the example in
  [extension-checklists.md](extension-checklists.md) § A.
- **Typed invariant kinds carry no attributes.** Their parameters sit on a contract
  (`export_deny_zones`, `min_pe_attachments`) or nowhere.
- **Ownership is free text.** `owner`, `consumer`, `requested_by`, `approved_by` are `Text`, and
  `IntentPolicy` / `IntentInvariant` have no `owner`, so "approved by the target's owner" can't
  be enforced.
- **Role vocabularies diverge.** Device role is `edge | core | cpe | tor`; `attach_device_role`
  is `pe | core | ce`. `IH/transforms/device_config.py` maps `edge → pe` in code and `ce`
  matches nothing.
- **Expressions have no grammar**: `IntentObjective.expression`, `IntentInvariant.expression`,
  waiver `subject_scope`. Signal `condition` has four regex forms in
  `IH/transforms/prometheus_rules.py`; anything else silently takes a default.
- **Signal `severity` (`sev1..sev4`) is authored.** ADR-0017 D4 wants it derived from invariant
  severity.

### Merge time (`IH/checks/`)

- **No scope resolution.** Only `contract_no_leak.py` reads the `intent → invariants` link.
  `contract_prefix_authorization.py` and `observability_capability.py` run unconditionally, so
  linking, disabling or waiving those invariants changes nothing. No check resolves
  `scope: global | domain`.
- **`severity` and `enabled` are never read.** Every finding is `log_error`, which blocks.
- **No check honors a waiver.**
- **Five of eight typed invariants have no projection**: redundancy, OOB reachability,
  reachability preserved, no default origination, no re-origination.
- **`ebgp-max-prefix-required`, the one network policy, has no check.**
- **Constraints owed as checks** (`IBN/infrahub/schemas/README.md`): intent with zero contracts;
  waiver with both or neither target, no subject, or no `approved_by`; `scope: domain` with
  empty `domains`; `scope: intent` with no links.

### Compile (`IH/transforms/`)

- **Only routing contracts compile expectations.** Reachability and reliability compile nothing.
  Security compiles config with no expectation. Objectives compile nothing, so a free-form
  contract can't fail.
- **Invariants have no expectation of their own.** `forbiddenActions` rides inside the routing
  contract's artifact and cites the contract. There is no always-on expectation per invariant
  and no `derives_from` form for an invariant or a policy (the URI roots at an intent; a shared
  rule has none).
- **Constants that the typing rule puts in the SoT**: `MIN_UPTIME_SECONDS`
  (`contract_expectations.py`), `TELEMETRY_CAPABILITIES` (`IH/checks/observability_capability.py`),
  the 60s / 50% defaults (`prometheus_rules.py`).
- **Target-group membership is manual.** A contract outside `routing_contracts` /
  `observability_contracts` gets no check and no artifact, with no warning.
- **No golden tests** in either repo. `IBN/infrahub/{checks,queries,transforms,templates,generators,tests}`
  are empty scaffolding; every compiler and check lives in `IH/`.

### Runtime

- **The validator evaluates BGP session state only**
  (`IBN/validator/src/autonetops_validator/models.py`). Prefix limits, communities, forbidden
  zones and actions, and freshness are emitted and ignored. `IBN/validator/rules/` and
  `IBN/validator/drift/` are empty.
- **A stage with no scoped session expectations passes its gate**, and `unverifiable` fails the
  gate only for a device changed in that stage
  (`IBN/orchestrator/src/autonetops_orchestrator/dispatch.py`). A plan that touches only
  devices outside routing contracts is unproven.
- **`IntentRoutingContract` is hardcoded** in `priority.py` and `render_source.py` (same
  package). A plan touching only devices of another contract kind inherits no
  priority (`medium`) and gets no expectations. Generalizing it is the contract-compilation
  registry that ADR-0016 § 13.1 defers to its own ADR (trigger: a second contract kind).
- **No continuous evaluation, drift classification or compliance roll-up.** `OpsPlanRecord` is
  per plan. `IBN/remediation/`, `IBN/simulations/` and `IBN/orchestrator/flows/` hold
  `.gitkeep` only.
- **Waivers can't relax pack policy**, by decision (ADR-0016 § 13.11).

## 3. Docs that lag the code (fix when touching them)

| Doc | Says | Reality |
|---|---|---|
| `IBN/docs/architecture/intent-model.md` "Migration note"; `IBN/infrahub/schemas/README.md` migration notes | the lab chains `contract → policy → intent` | flattened in `IH/schemas/intent.yml`; `priority.py` walks one hop |
| `intent-model.md`, waiver section | the planner honors a waiver on delivery-preference policy | excluded by ADR-0016 § 13.11 |
| `intent-model.md`, severity row | paging scale is renderer output, never authored | authored on `IntentObservabilitySignal.severity` |
| `intent-model.md` and schema README examples | tenant spelled `cust-c` | the SoT spells it `custc` |
| `intent-model.md`, enforcement matrix | five enforcement points | no row for the simulation gate |
| `IBN/remediation/verifications/README.md` | `infrahub://RoutingContract/<name>` | `infrahub://Intent/<intent>/contract/<contract>` |

## 4. Suggested build order

A recommendation, ordered by how much proof each step unlocks.

1. **One rule resolver for checks**: instruments in force for an intent across all three scopes,
   filtered by `enabled`, minus live waivers, with blocking derived from `severity`. Port the
   three existing checks onto it. This makes shared rules, waivers and `warning` real at once.
2. **The owed constraint checks** (zero contracts, waiver shape, empty scope).
3. **`policy_ebgp_max_prefix.py`**, so the one network policy can reject.
4. **Evaluate what is already emitted**: prefix limits, forbidden exports and freshness in the
   validator.
5. **Reslice the seed** to one intent per outcome, so the lab teaches the model.
6. **Expectations for security, reachability and reliability contracts**, with the
   contract-compilation registry ADR.
7. **ADR: `derives_from` for shared rules**, then always-on invariant expectations.
8. **ADR: expression grammar**, then objective compilation.
9. **Compliance roll-up** records beside the intent.
10. **Platform schema parity** with the lab (tenant, zone, capability, typed invariants, `ticket`).
