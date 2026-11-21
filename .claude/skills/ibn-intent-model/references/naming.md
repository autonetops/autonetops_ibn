# Naming reference

## Global rules

1. **Object names**: lowercase kebab-case, `[a-z0-9-]`, no vendor names, no dates (except
   freeze windows like `q3-…`), no environment suffix (environment lives on
   `IntentTenant.environment` and on branches).
2. **Unique per kind, fleet-wide.** Names are the `human_friendly_id` and appear verbatim in
   `derives_from` URIs, artifact names, plan reasons, alert labels and dashboards. A rename
   breaks all of them at once, so treat it like a schema migration.
3. **Enum values and capability names**: snake_case (`customer_edge`, `internet_peering`,
   `gnmi_set`, `ssh_cli`). Code branches on them. Zone *names* stay kebab-case
   (`internet-peers`) while `zone_type` values are snake_case (`internet_peering`).
4. **Name by role in the model**:
   - Intent = the outcome (noun phrase about the result).
   - Contract = the relationship or subject being promised.
   - Policy = the rule, readable as a requirement.
   - Invariant = the property that must hold.
   - Waiver = who is excused from what.
5. **Kind names**: namespace `Intent`, then `<Thing>Contract`, `<Condition>Invariant`,
   `<Thing>Policy`. The root is `IntentDefinition` (`IntentIntent` stutters). Operational
   kinds live in namespace `Ops` and inherit `IntentPolicy`. A typed invariant's kind name is
   its type: `IntentNoLeakInvariant` → `no_leak` by camel-to-snake, so pick kind names that
   read well both ways.

## Scope prefixes

| Prefix | Use when | Example |
|---|---|---|
| `<tenant-abbr>` | the intent has a tenant | `custc` for `customer-c` |
| `provider` | provider-owned service, no tenant | `provider-core-transport` |
| `fleet` | applies to every device | `fleet-management-plane`, `fleet-baseline` |
| topology scope (`core`, `inet`, `emea`, `ibgp`) | a contract under a provider intent | `ibgp-core-rr`, `inet-peering-emea` |

Derive the tenant abbreviation once, record it in the tenant description, never vary it.
An intent and the contracts, signals and security rules it **owns** share the prefix.
Policies and invariants are **shared**, so they take a prefix only when they really are
specific to one intent tree (`scope: intent`).

The platform docs spell the same tenant `cust-c` (`cust-c-l3vpn`), the lab seed spells it
`custc`. Both are legal kebab-case. Within one SoT pick one form and keep it.

## Per-kind patterns

### IntentDefinition: `<scope>-<outcome>`
- ✅ `custc-l3vpn-connectivity`, `custc-perimeter-protection`, `provider-internet-peering`
- ❌ `custc-bgp` (mechanism), `custc-everything` (no outcome), `custc-intent-1`
- `description`: one sentence a non-engineer can verify, with a measurable clause where
  possible ("…recover within 30 seconds of any single failure").
- `domain`: one lowercase word from the starter set (`connectivity`, `routing`,
  `observability`, `security`, `resilience`, `capacity`, `compliance`, `lifecycle`,
  `operations`). Not part of the name.

### Contracts: `<scope>-<relationship | subject>`

| Typed kind | Pattern | Examples |
|---|---|---|
| Routing | `<a>-to-<b>` or `<session-kind>-<where>` | `custc-ce-to-pe`, `ibgp-core-rr`, `inet-peering-emea` |
| Reachability | `<what>-reachable-from-<zone>` | `custc-apps-reachable-from-emea-corp` |
| Security | `<scope>-<direction>-<posture>` | `custc-inbound-protect` |
| Observability | `<scope>-<purpose>-signals` / `<scope>-baseline` | `custc-service-signals`, `fleet-baseline` |
| Reliability | `<scope>-reliability` | `custc-reliability` |
| Free-form | `<scope>-<subject>` | `cust-c-sessions`, `cust-c-visibility` |

`consumer` names who loses if the promise breaks. Prefer the tenant name or a team name
that also appears as an `owner` somewhere.

### IntentObjective: `<term>`
Unique within its contract. Name the term, not the threshold: `sessions-established`,
`max-prefixes`, `telemetry-fresh`. The threshold lives in `expression`.

### IntentPolicy
- Network policy: the rule itself, `<subject>-<requirement>`: `ebgp-max-prefix-required`,
  `mgmt-no-public-addressing`. If it doesn't read as a rule a reviewer could apply, rename it.
- `OpsChangeWindow`: `<scope>-<cadence | purpose>`; freezes end in `-freeze`:
  `emea-standard-maintenance`, `weekday-low-risk`, `q3-core-audit-freeze`.
- Policy-pack entries (change classes, canary strategies): kebab-case names of what they
  admit: `interface-descriptions`.

### IntentInvariant
- Shared (`scope: global | domain`): `<subject>-<property>`: `customer-site-dual-homed`,
  `no-orphan-vrf`, `fleet-oob-cabled`.
- Intent-scoped: `<scope>-<type-kebab>[-qualifier]`: `custc-no-leak`,
  `custc-prefix-authorization`, `custc-redundancy-floor`, `inet-no-reorigination`.
- Short forms are fine while the type stays recognizable (`custc-no-default` for
  `no_default_origination`). The kind is the machine identity; the name is for people.

### IntentWaiver: `<subject>-<what is violated>`
`cust-c-site3-single-homed`. No dates in the name; `expires_at` carries the date, and a
renewal is a new reviewed waiver with a new name suffix if needed (`-2`).

### Children
- `IntentObservabilitySignal`: `<scope>-<signal-kebab>` (`custc-bgp-route-count`).
- `IntentSecurityRule`: `<action>-<what>` (`allow-corp-https`, `deny-internet-to-tenant`);
  ordering lives in `index` (10, 20, …; leave gaps).

### Supporting kinds
- `IntentTenant`: `<org-slug>` (`customer-c`).
- `IntentZone`: `<purpose>[-<region>]` (`corp-emea`, `core`, `internet-peers`, `mgmt-oob`);
  `zone_type` carries the class.
- `IntentCapability`: snake_case, the capability and not the vendor feature (`gnmi`,
  `bmp_client`, `vpn_ipv4`); `category` is `telemetry | management | forwarding`.

## Code & file naming

| Thing | Convention | Example |
|---|---|---|
| GraphQL query | `queries/<snake>.gql`, `name: <snake>` | `contract_no_leak` |
| Check (new files) | `checks/invariant_<type>.py` or `checks/policy_<rule>.py`; class `<Camel>Check`; definition `<snake>_check` | `invariant_redundancy.py`, `policy_ebgp_max_prefix.py` |
| Check (existing, predate the prefix rule) | keep until deliberately migrated | `contract_no_leak.py`, `contract_prefix_authorization.py`, `observability_capability.py` |
| Transform | `transforms/<snake>.py`, class `<Camel>Transform` | `ContractExpectationsTransform` |
| Generator | `generators/<snake>.py`, class `<Camel>Generator` | `EdgeBgpLocalPrefGenerator` |
| Artifact definition | kebab-case, same for `name` and `artifact_name` | `contract-expectations` |
| Target group | snake_case plural of what it holds | `routing_contracts`, `intent_tenants` |
| Expectation | kind `ContractExpectations`, `apiVersion: expectations.networking.autonetops/v1`, file `<contract-name>.yml` | `custc-ce-to-pe.yml` |
| `derives_from` | `infrahub://Intent/<intent>/contract/<contract>` | `infrahub://Intent/custc-l3vpn-connectivity/contract/custc-ce-to-pe` |
| Verification | `remediation/verifications/<scenarios\|invariants>/<domain>-<subject>.yaml` | `routing-custc-no-leak.yaml` |
| Validator rules dir | `validator/rules/<area>/` (compiled rules; the word "rule" is reserved for these) | `validator/rules/routing/` |
| Policy pack | a directory with `profile.yaml`; data contract in `contracts/profile/v1/` | `planner/policies/` |
| Python packages | `autonetops_<component>` | `autonetops_planner` |

## Names that currently disagree with the model

Recorded so nobody mistakes them for conventions. Each fix is a migration, not a drive-by.

| Where | Issue |
|---|---|
| `IntentReliabilityContract`, `validator/rules/reliability/` | the domain word is `resilience` (ADR-0017 D2) |
| `IntentRoutingContract.pe_devices` / `ce_devices` | used for RR ↔ clients and for peer ↔ us; a role-neutral pair (local side / remote side) would describe all three uses |
| `validator/rules/reachability/` | reachability is an objective kind, not a domain |
| `attach_device_role: pe \| core \| ce` vs device role `edge \| core \| cpe` | two vocabularies for one concept, bridged in renderer code |
| `IntentPolicy.enforcement` | free text for a closed set (`merge \| compile \| dispatch \| continuous`) |
| `remediation/verifications/README.md` | shows `infrahub://RoutingContract/<name>`; the decided URI roots at the intent |
