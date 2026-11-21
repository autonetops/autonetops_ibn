# Primitives: kinds, fields, controlled vocabularies

A compact view of `IH/schemas/intent.yml` and `IH/schemas/operations.yml`, plus the values
seeded by `IH/scripts/bootstrap.py`. Checked 2026-11-21. The schema wins, so confirm a field
before relying on it: `grep -n -A8 'name: <field>' IH/schemas/intent.yml`.

`*` = required. A default is shown in parentheses.

Contents: 1. root and instruments · 2. typed contract kinds · 3. typed invariant kinds ·
4. supporting kinds · 5. controlled vocabularies · 6. authoring mechanics

## 1. Root and instruments

| Kind | Attributes | Relationships |
|---|---|---|
| `IntentDefinition` | `name`\*, `domain`\*, `owner`\*, `description`, `priority` (medium), `status` (active), `ticket` | `contracts` (owned, cascade) · `policies`, `invariants` (link only when their `scope` is `intent`) · `tenant` (one) |
| `IntentContract` (generic) | `name`\*, `description`, `consumer`, `status` (active) | `intent`\* (parent) · `objectives` (owned) |
| `IntentObjective` | `name`\*, `expression`\*, `description` | `contract`\* (parent) |
| `IntentPolicy` (generic) | `name`\*, `description`, `subject` (network), `scope` (global), `domains`, `enforcement`, `enabled` (true) | `intents` |
| `IntentInvariant` (generic) | `name`\*, `description`, `severity` (critical), `scope` (global), `domains`, `expression`, `enabled` (true) | `intents` |
| `IntentWaiver` | `name`\*, `reason`\*, `requested_by`\*, `expires_at`\*, `approved_by` (needed to merge), `subject_scope` | target: `waived_policy` xor `waived_invariant` · subject: `subject_intent` or `subject_contract` |
| `OpsChangeWindow` (inherits `IntentPolicy`) | `window_type` (maintenance), `max_blast_radius` (moderate); recurring: `days`, `start_utc`, `duration_minutes`; absolute: `starts_at`, `ends_at` | `devices` (empty = every device) |

Free-form starters: `IntentGenericContract` (terms are objectives), `IntentGenericPolicy`,
`IntentGenericInvariant`. `tenant`, `ticket` and the supporting kinds exist in the lab schema
only (see [status.md](status.md)).

## 2. Typed contract kinds

All inherit `IntentContract` and `CoreArtifactTarget`.

| Kind | Terms | Anchors | Compiles today |
|---|---|---|---|
| `IntentRoutingContract` | `role`\*, `peer_asn`\*, `afi_safis`\*, `local_preference`, `max_prefixes_ipv4`, `max_prefixes_ipv6`, `attach_communities`, `require_communities` | `zone`\*, `pe_devices`, `ce_devices`, `allowed_prefixes`, `export_tenants`, `export_deny_zones` | config + expectations |
| `IntentReachabilityContract` | `max_convergence_seconds`, `require_redundancy` | `from_zone`\*, `to_prefixes` | nothing |
| `IntentSecurityContract` | `attach_device_role`\*, `attach_interface_role`\*, `ddos_profile` | `rules` (owned) | config only |
| `IntentObservabilityContract` | none | `signals` (owned) | collector inputs, alert rules, dashboard |
| `IntentReliabilityContract` | `min_pe_attachments`, `require_distinct_failure_domains` | none | nothing |

Children:

- `IntentSecurityRule`: `name`\*, `index`\*, `action`\*, `protocol`, `dst_ports`, `src_zone`,
  `dst_prefixes`.
- `IntentObservabilitySignal`: `name`\*, `signal`\*, `condition`\*, `direction`,
  `frequency_seconds`, `severity`, `watches` (the contract it keeps honest; empty = fleet-wide).
  `condition` forms the alert compiler parses: `down_for > <n>s`, `count > max_prefixes`,
  `count > <n>`, `loss > <n>%`.

`pe_devices` / `ce_devices` mean local side / remote side. The seed uses them for PE ↔ CE,
RR ↔ clients and us ↔ peer. BGP sessions are derived from the two device lists plus cabling,
never authored.

## 3. Typed invariant kinds

All inherit `IntentInvariant` and carry no attributes yet. The type string is the kind name in
snake_case without `Intent` and `Invariant`.

| Kind | Type | Merge projection | Runtime surface |
|---|---|---|---|
| `IntentNoLeakInvariant` | `no_leak` | `contract_no_leak.py` | `forbiddenActions` in the routing expectation |
| `IntentPrefixAuthorizationInvariant` | `prefix_authorization` | `contract_prefix_authorization.py` (runs whether linked or not) | none |
| `IntentCapabilityPresentInvariant` | `capability_present` | `observability_capability.py` (runs whether linked or not) | none |
| `IntentNoDefaultOriginationInvariant` | `no_default_origination` | none | `forbiddenActions` |
| `IntentNoReoriginationInvariant` | `no_reorigination` | none | `forbiddenActions` |
| `IntentRedundancyInvariant` | `redundancy` | none | none |
| `IntentReachabilityPreservedInvariant` | `reachability_preserved` | none | none |
| `IntentOobReachabilityInvariant` | `oob_reachability` | none | none |

## 4. Supporting kinds

| Kind | Attributes | Relationships |
|---|---|---|
| `IntentTenant` (WHO) | `name`\*, `owner`\*, `description`, `environment`, `tenant_community`, `ticket` | `vrfs` (its address space is the prefixes in these VRFs) · `intents` |
| `IntentZone` (WHERE) | `name`\*, `zone_type`\*, `description` | referenced by contracts and security rules |
| `IntentCapability` (WITH WHAT) | `name`\*, `category`\*, `description` | `DcimPlatform.capabilities` |

## 5. Controlled vocabularies

| Vocabulary | Values |
|---|---|
| intent `domain` (free text, so spell it exactly) | `connectivity` · `routing` · `observability` · `security` · `resilience` · `capacity` · `compliance` · `lifecycle` · `operations` |
| `priority` (intent only) | `low` · `medium` · `high` · `critical` |
| intent `status` | `draft` · `active` · `deprecated` · `retired` |
| contract `status` | `draft` · `active` · `retired` |
| policy `subject` | `network` · `operational` |
| policy / invariant `scope` | `global` · `domain` · `intent` |
| policy `enforcement` (informational text) | `merge` · `compile` · `dispatch` · `continuous` |
| invariant `severity` | `warning` · `major` · `critical` |
| blast radius (`max_blast_radius`, plan) | `low` · `moderate` · `high` |
| `window_type` | `maintenance` · `freeze` |
| routing `role` | `customer_edge` · `core` · `internet_peering` · `transit` |
| `afi_safis` (protocol tokens) | `ipv4-unicast` · `ipv6-unicast` · `vpn-ipv4` |
| `zone_type` | `core` · `corp` · `transit` · `internet_peering` · `partner` · `management` |
| zones seeded | `corp-emea` · `core` · `internet-peers` · `transit` · `mgmt-oob` |
| capability `category` | `telemetry` · `management` · `forwarding` |
| capabilities seeded | telemetry: `gnmi`, `snmp`, `ssh_cli`, `bmp_client` · management: `gnmi_set`, `netconf`, `cli_config` · forwarding: `mpls`, `vpn_ipv4` |
| signal `signal` | `bgp_session_state` · `bgp_route_count` · `policy_export_violation` · `interface_errors` (no alert rule yet) · `device_reachability` |
| signal `severity` (paging scale) | `sev1` · `sev2` · `sev3` · `sev4` |
| signal `direction` | `inbound` · `outbound` |
| security `action` / `protocol` | `allow`, `deny` / `any`, `tcp`, `udp`, `icmp` |
| `attach_device_role` / `attach_interface_role` | `pe`, `core`, `ce` / `peering`, `cust`, `core`, `management` |
| `ddos_profile` | `none` · `standard_l3vpn` · `hardened` |
| tenant `environment` | `dev` · `staging` · `prod` |
| device role (DCIM, as seeded) | `edge` · `core` · `cpe` · `tor` |
| verdict | `pass` · `fail` · `pre_existing` · `unverifiable` (compliance adds `waived`) |
| remediation class | `safe_fix` · `quarantine` · `escalate` |
| target groups | `network_devices` · `monitored_devices` · `oob_switches` · `routing_contracts` · `observability_contracts` · `intent_tenants` · `edge_bgp` |

What each domain holds: the Domains table in `IBN/docs/architecture/intent-model.md`.

## 6. Authoring mechanics

Everything goes on an Infrahub branch and merges through a Proposed Change.

- **Python SDK** (the pattern in `IH/scripts/bootstrap.py`):
  `client.create(kind="IntentRoutingContract", branch=<branch>, name=…, intent=<id>, …)` then
  `.save(allow_upsert=True)`. Relationships take ids; many-relationships take a list of ids.
- **GraphQL**: `<Kind>Create` mutations, one request per object, parent first. Recipes in
  `IBN/infrahub/schemas/README.md`.
- **Query the generic** to see every kind at once (`IntentContract`, `IntentPolicy`,
  `IntentInvariant`) and read `__typename` to tell kinds apart.
- **Schema changes** (run in `IH/`): `infrahubctl schema check`, then
  `infrahubctl schema load schemas/intent.yml schemas/operations.yml`. These two files are
  loaded by hand. `.infrahub.yml` syncs only `schemas/dcim_bgp.yml`.
- **Wiring**: queries, checks, transforms, generators and artifact definitions are registered
  in `IH/.infrahub.yml`. A new contract must also join its target group.
- **Plan and prove** (run in `IBN/`): `ibn-orchestrate plan`, then `ibn-orchestrate dispatch`.
  Check the policy pack with `autonetops-planner validate-pack planner/policies`.
