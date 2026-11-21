# Use-case patterns and coverage

Paths: `IBN/` = `autonetops_ibn`, `IH/` = `autonetops_infrahub`.

How each common network-automation use-case is expressed in the intent model, and where the
model or the code stops short. Use it to answer "how do we model X?" and "do we need a new
concept for X?".

Status column, checked 2026-11-21 against both repos (details in [status.md](status.md)):
**built** = schema + compiler/check exist in the lab · **schema** = kinds exist, nothing
compiles or checks them · **kind** = fits the vocabulary, needs a new typed kind ·
**concept** = the vocabulary has no word for it; needs an ADR.

Contents: 1. patterns by use-case · 2. what kind of gap is it · 3. concept gaps ·
4. crosswalk to the common "starter schema set"

## 1. Patterns by use-case

### Service delivery

| Use-case | Domain | Express it as | Status |
|---|---|---|---|
| Customer L3VPN / private connectivity | connectivity | intent + `IntentRoutingContract` (`customer_edge`) + `IntentReachabilityContract`; invariants no-leak, no-default-origination; policy `ebgp-max-prefix-required`; tenant with VRFs | **built** for routing (config + expectations); reachability is **schema** |
| Internet peering / transit | connectivity | `IntentRoutingContract` (`internet_peering` / `transit`), empty `export_tenants`, no-re-origination invariant | **built** |
| Core / underlay design (RR, iBGP) | routing | `IntentRoutingContract` (`core`) | **built** (BGP terms only; IGP/MPLS underlay is renderer knowledge) |
| DC fabric, EVPN, L2 segments, VLAN/port provisioning, campus | connectivity | a typed contract per service shape (fabric, segment, access port) + a generator that materializes per-device facts from it | **kind** + derived facts (concept gap 2) |
| SD-WAN / controller-managed overlay | connectivity | contracts compile into an artifact for the controller's control point (ADR-0011). The vendor data model is the *artifact*, not the intent: mirroring it into the SoT schema recreates a vendor config repository | **kind** (the lab's mirrored SD-WAN schema is disabled) |
| Firewall / access request from a service catalog | security | `IntentSecurityContract` + `IntentSecurityRule`; intake is a branch + Proposed Change opened by the portal | **built** for config, no expectation; temporary access is concept gap 6 |
| Traffic steering, egress preference, path constraints | routing / connectivity | a soft preference is a contract term; a hard boundary ("traffic must not leave the region") is an invariant; mechanism (local-pref, SR policy, RSVP) is chosen by the compiler | **kind**. Today the lab steers by editing `DcimDevice.bgp_local_pref` through a generator, which is a mechanism knob stored as a fact |
| QoS, bandwidth, latency promises | capacity | contract with numeric objectives (`_mbps`, `_ms`, `_pct`) and range expectations | **kind** |

### Fleet baseline and compliance

| Use-case | Domain | Express it as | Status |
|---|---|---|---|
| Golden config / hardening (NTP, AAA, syslog, SNMP, banners) | compliance / security | network policy `scope: global` + its merge check; a fleet contract for what gets rendered and proven | **kind**; the one existing network policy has no check |
| Software compliance (approved versions, EOL) | lifecycle | policy or contract objective "version ∈ approved set", evidence from `get_facts` | detect: **kind** · remediate (upgrade): **concept** gap 1 |
| Certificate / credential rotation | lifecycle | same shape as software compliance | **concept** gap 1 |
| Audit and regulatory reporting | compliance | compliance roll-up per intent, written back beside it (`OpsPlanRecord` today) | partial: per-contract compliance records are owed |
| Sanctioned, temporary violations | any | `IntentWaiver` | **schema**: nothing honors a waiver yet |

### Change management

| Use-case | Express it as | Status |
|---|---|---|
| Maintenance windows, freezes | `OpsChangeWindow` (operational policy in the SoT) | **built** |
| Staged rollout, blast radius, approvals | policy pack: `blast_radius`, `canary_strategies`, `approvals` | **built** |
| Pre-approved routine changes | policy pack: `change_classes` with golden fixtures (ADR-0014) | **built** |
| Rollback | pack `rollback` + driver `rollback` verb | **built** |
| Emergency change | intent `priority: critical` + emergency dispatch override, on record | **built** |
| Decommission | retire the contract (`status: retired`) → artifacts drop the config → plan with `removed_targets` (never pre-approved) | pattern |
| Multi-customer operation | one engine, one policy pack per customer (ADR-0016) | **built** |

### Assurance and day 2

| Use-case | Express it as | Status |
|---|---|---|
| Service monitoring and alerting | `IntentObservabilityContract` + signals → collector inputs, alert rules, dashboards | **built** |
| Post-change validation | stage gates evaluating contract expectations scoped to touched devices and neighbors, with baseline | **built** for BGP session state only |
| Redundancy and resilience audit | `IntentReliabilityContract` + `IntentRedundancyInvariant` | **schema** |
| Drift detection and remediation | validator classifies drift → playbook class → safe fix *proposes a plan* | structure only |
| Troubleshooting, on-demand probes | verifications, executor read verbs only | structure only |
| Maintenance drain / isolating a device | set a SoT fact (device status) that renderers honor (overload bit, graceful shutdown); cover the planned redundancy loss with a waiver | pattern, not implemented |
| Incident → regression test | `IBN/simulations/golden-topologies/<incident>/` + failing expectation | structure only; simulation is concept gap 5 |
| Capacity planning, what-if | simulations + capacity contracts | **kind** |

### Day 0 and SoT hygiene

| Use-case | Express it as | Status |
|---|---|---|
| Device onboarding / ZTP | facts (device, platform, capabilities, control point); `fleet-*` intents and global policies and invariants then apply by scope with no per-device authoring | pattern; `IBN/orchestrator/flows/onboard/` is a placeholder |
| IPAM, resource allocation (addresses, RD/RT, VLAN, ASN) | facts allocated from resource pools; contracts reference them | pattern (derived facts, concept gap 2) |
| Brownfield discovery / import | observed → SoT is outside the intent model, which only names the result (drift) | **concept** gap 7 |

## 2. What kind of gap is it?

Sort a missing capability into one of three buckets before proposing work. They cost very
different amounts.

1. **Kind gap**: the classifying questions give a clear answer, there is just no typed kind
   yet (path constraints, QoS, fabric, hardening, software compliance). Add a kind under the
   existing generic (checklists B, C, D). No ADR unless a new artifact class appears.
2. **Compiler or check gap**: the kind exists but nothing renders, proves or enforces it
   (reachability, reliability, waivers, objectives, most invariants, the network policy).
   Under the model's own law these are unfinished: a contract without expectations can't
   fail and a policy without a check can't reject. They are listed in
   [status.md](status.md).
3. **Concept gap**: no word in the vocabulary fits. Section 3. Needs an ADR.

Most new use-cases land in bucket 1. Reach for bucket 3 only after the classifying questions
and the placement ladder both fail to place the thing.

## 3. Concept gaps (candidates for ADRs)

Ordered by how many use-cases each one blocks.

1. **Procedural operations.** The executor's verb contract is artifact delivery
   (`get_facts`, `snapshot`, `dry_run`, `apply`, `confirm`, `rollback`). An OS upgrade,
   reboot, certificate rotation or traffic drain is an ordered procedure with its own
   pre/post conditions, not a config diff. The intent side already fits ("fleet runs
   approved software" is a lifecycle policy with expectations); what is missing is the
   plan-side notion: a step class for operations, its verbs, and how blast radius and
   rollback apply to it. Blocks the whole `lifecycle` domain beyond detection.
2. **Derived facts.** Between intent and artifacts sits data that follows mechanically from
   intent + facts: session endpoints, allocated addresses and identifiers, per-device objects
   expanded from a service or fabric design. The derived vocabulary names only artifact,
   expectation, plan and rule. The lab already uses both forms (derive in the transform;
   materialize with a generator) with no guidance for choosing, and no marker distinguishing a
   generated fact from an authored one. Needed for any design-driven use-case (fabrics,
   L2 services, pools). "Realization" is already reserved by ADR-0017 D1 for a grouping of
   contracts, so this needs its own word.
3. **Selectors and one role taxonomy.** Contracts mostly enumerate devices, and where they
   select by role the vocabularies diverge (device role, interface role, contract role,
   `attach_device_role`). `IntentWaiver.subject_scope` is a free-text selector. One
   controlled role vocabulary plus a selector shape (role + zone + group) would let a
   contract say "every PE in EMEA" and have onboarding pick up intent automatically.
4. **Ownership as identity.** `owner`, `consumer`, `requested_by` and `approved_by` are free
   text, and policies and invariants have no owner at all. Waiver governance ("approved by
   the target's owner, who is not the requester") and escalation routing both branch on
   these values, so they belong in a controlled kind or mapped to SoT accounts/groups.
5. **Simulation as an enforcement point.** `IBN/simulations/` describes a CI gate that deploys
   candidate artifacts to a golden topology and evaluates expectations before merge. The
   enforcement matrix in `intent-model.md` has no row for it, and "evaluation in simulation"
   is not in the observed vocabulary.
6. **Validity windows on promises.** Only waivers expire. A temporary firewall opening, a
   trial service or a scheduled turn-up is a contract that should start or stop being
   promised at a known time. A waiver doesn't fit: it sanctions a violation and compiles to
   nothing, while temporary access must render config. Candidate: `valid_from` /
   `valid_until` on the contract generic, with expiry producing a proposed plan.
7. **Adoption (observed → SoT).** Discovery and brownfield import run against the grain of
   the model. Drift classification covers "fix the network"; nothing names "accept what the
   network has into the SoT under review". Without it the first step of every brownfield
   onboarding stays outside the platform.
8. **Expression grammar.** `IntentObjective.expression`, `IntentInvariant.expression`, signal
   `condition` and waiver `subject_scope` are free text ("until the grammar lands").
   Free-form contracts can't compile to expectations until it does, so typed kinds are
   currently the only contracts that can fail.

## 4. Crosswalk to the common "starter schema set"

Industry write-ups on intent modeling converge on roughly the same object list. How it maps:

| Commonly proposed object | Here | Difference worth knowing |
|---|---|---|
| TenantIntent (identity, VRFs, segments) | `IntentTenant` + IPAM (`IpamVRF`, `IpamPrefix`) | the tenant is WHO; VRFs and prefixes are facts. No named segment object: security rules reference prefixes |
| RoutingContractIntent | `IntentRoutingContract` | invariants are not nested in the contract; they are shared typed kinds referenced by the intent |
| ReachabilityIntent | `IntentReachabilityContract` | a contract kind (an objective kind), deliberately not a domain |
| Path constraints | none yet | kind gap; soft preference = contract term, hard boundary = invariant |
| SecurityIntent | `IntentSecurityContract` + `IntentSecurityRule` | a sanctioned violation is a waiver with an expiry, not a comment on a rule |
| ReliabilityIntent | `IntentReliabilityContract` + `IntentRedundancyInvariant` | domain word is `resilience` |
| ObservabilityIntent | `IntentObservabilityContract` + `IntentObservabilitySignal` | per-service signals ride the service intent; only fleet baselines are observability intents |
| Expectations (compiled) | `ContractExpectations` artifact | one kind, per contract; reachability and security expectations not compiled yet |
| Capability & role taxonomy | `IntentCapability`, `IntentZone`; roles as enums | capability and zone are controlled kinds; role is not unified (concept gap 3) |
| *(usually absent)* | `IntentPolicy` with network / operational subjects | separates "rejected change" from "incident", and models change management as intent |
| *(usually absent)* | `IntentWaiver` | exceptions that expire |
| *(usually absent)* | Plan, change class, policy pack | the transaction that moves the network toward intent |
