# From a contract to config, proof and monitoring

Paths: `IBN/` = `autonetops_ibn`, `IH/` = `autonetops_infrahub`.

What a contract turns into, how the pieces are wired in Infrahub, and which values tie them
together. The excerpts were rendered on 2026-11-21 by running the lab's transforms on the seed
values, then trimmed. Where the chain stops short is listed in [status.md](status.md).

Contents: 1. wiring in Infrahub · 2. join keys · 3. one contract traced · 4. adding monitoring
to a contract · 5. adding a new compiled output

## 1. Wiring in Infrahub

Nothing is linked by hand per object. One chain, declared in `IH/.infrahub.yml`:

```
kind inherits CoreArtifactTarget → object joins a target group
  → artifact_definition (targets: <group>, parameters) → python_transform → query (.gql)
```

| Artifact | One per | Target group | Transform (`IH/transforms/`) | Reads | Reaches its consumer through |
|---|---|---|---|---|---|
| `device-configuration` | device | `network_devices` | `device_config.py` | every routing and security contract that touches the device, tenant VRFs, cabling, platform capabilities | `ibn-orchestrate plan` and `dispatch` |
| `contract-expectations` | routing contract | `routing_contracts` | `contract_expectations.py` | the contract, its intent's tenant and invariants, the signals that watch it | the stage gate at dispatch |
| `telegraf-inputs` | device | `monitored_devices` | `telemetry_collector.py` | signals whose watched contract lists the device in `pe_devices`, platform capabilities | `IH/scripts/fetch_artifacts.py` |
| `prometheus-rules` | observability contract | `observability_contracts` | `prometheus_rules.py` | its signals, the watched contract's limits and tenant | `IH/scripts/fetch_artifacts.py` |
| `grafana-dashboard` | tenant | `intent_tenants` | `grafana_dashboard.py` | the tenant's routing contracts and signals | `IH/scripts/fetch_artifacts.py` |

Merge checks hang on the same groups (`check_definitions`, `targets: routing_contracts`).
Generators are declared under `generator_definitions`.

Two consequences:

- Artifacts attach to **devices, contracts and tenants**, never to the intent. The intent shows
  up only as `metadata.intent` and the `derivesFrom` root.
- A device config is the sum of **every** contract that names the device. Changing one contract
  re-renders each device it touches, and a contract can put config on a device it doesn't list
  (see the no-leak row below).

## 2. Join keys

| Value | Where it reappears |
|---|---|
| contract `name` | expectation `metadata.name` and file name · `derivesFrom` · telegraf tag `contract` · Prometheus label `contract` and alert-name prefix · route-map and prefix-list names, upper-cased |
| tenant `name` | `metadata.tenant` · label `tenant` · dashboard uid `intent-<tenant>` · community list `DENY-TENANT-<TENANT>` |
| device `name` | config and telegraf file names · `sessions[].device` · tag `device` |
| signal `signal` | gNMI subscription name, mapped to a metric by the processor in `IH/monitoring/telegraf/telegraf.conf` |

Metrics the alert rules query: `bgp_session_state_established`, `bgp_session_prefixes_received`,
`bgp_session_prefixes_sent`, `ping_percent_packet_loss`. Renaming a contract breaks every row
of the first line at once.

## 3. One contract traced: `custc-ce-to-pe`

| Authored | Config (EOS) | Expectation | Monitoring |
|---|---|---|---|
| `pe_devices`, `ce_devices` + cabling | one `neighbor` per derived session, under the VRF | `sessions[]`: `device`, `neighborIp`, `mustBe` | which devices get the collector input |
| `peer_asn: 65123` | `remote-as 65123` | `peerAsn` | none |
| `max_prefixes_ipv4: 200` | `maximum-routes 200` | `maxPrefixes.ipv4` | threshold of `count > max_prefixes` |
| `allowed_prefixes` | `ip prefix-list CUSTC-CE-TO-PE-IN-V4` | `allowedPrefixes` | none |
| `require_communities`, `attach_communities` | `set community … additive` | `mustIncludeCommunities` | none |
| `local_preference: 120` | `set local-preference 120` | none | none |
| intent `tenant` → `vrfs` | `vrf instance`, `rd`, `route-target` | `metadata.tenant` | label `tenant`, one dashboard |
| `export_deny_zones` + linked `IntentNoLeakInvariant` | on the **peering** contract's PE: `DENY-TENANT-CUSTOMER-C`, denied in `INET-PEERING-EMEA-OUT` | `forbiddenZones`, `forbiddenActions` | a `policy_export_violation` signal watching the peering contract |
| a signal that `watches` it | none | `telemetry.required` (freshness = 2 × `frequency_seconds`), `alerting` | subscription + alert rules |
| platform capabilities | which renderer arms emit (on SR Linux, `mpls` gates LDP) | `observedVia` | gNMI subscription or CLI-scrape collector |

Config, `pe-emea-02`:

```
router bgp 65010
 vrf CUSTC-PROD
  rd 65010:1203
  route-target import vpn-ipv4 65010:1203
  neighbor 10.84.255.6 remote-as 65123
  neighbor 10.84.255.6 route-map CUSTC-CE-TO-PE-IN in
  neighbor 10.84.255.6 maximum-routes 200
ip prefix-list CUSTC-CE-TO-PE-IN-V4 seq 5 permit 10.84.0.0/16
route-map CUSTC-CE-TO-PE-IN permit 10
 match ip address prefix-list CUSTC-CE-TO-PE-IN-V4
 set community 65010:1203 65010:30010 65010:55555 additive
 set local-preference 120
ip community-list DENY-TENANT-CUSTOMER-C permit 65010:1203
route-map INET-PEERING-EMEA-OUT deny 10
 match community DENY-TENANT-CUSTOMER-C
```

Expectation, `custc-ce-to-pe.yml`:

```yaml
metadata:
  name: custc-ce-to-pe
  intent: custc-l3vpn-connectivity
  domain: connectivity
  tenant: customer-c
  zone: corp-emea
  derivesFrom: infrahub://Intent/custc-l3vpn-connectivity/contract/custc-ce-to-pe
spec:
  bgp:
    sessions:
    - {device: pe-emea-02, neighborIp: 10.84.255.6, neighborDevice: ce-custc-02, peerAsn: 65123,
       observedVia: gnmi, mustBe: {sessionState: established, minUptimeSeconds: 300}}
    routePolicy:
      inbound: {maxPrefixes: {ipv4: 200, ipv6: 100}, allowedPrefixes: [10.84.0.0/16, …]}
      outbound:
        forbiddenZones: [internet-peers, transit]
        forbiddenActions: [export_prefixes_from_tenant(customer-c), originate_default_route_to_peer]
  telemetry:
    required: [{signal: bgp_session_state, freshnessSeconds: 20}]
  alerting: [{signal: bgp_session_state, severity: sev2, condition: down_for > 60s}]
```

Monitoring, from the signal `custc-bgp-session-state` (collector on the PE, rule in the
observability contract's group):

```
[[inputs.gnmi]]
  addresses = ["172.20.20.11:6030"]
  [inputs.gnmi.tags]
    device = "pe-emea-01"
    contract = "custc-ce-to-pe"
  [[inputs.gnmi.subscription]]
    name = "bgp_session_state"
    sample_interval = "10s"
```

```yaml
- alert: custc-ce-to-pe-bgp-session-down
  expr: bgp_session_state_established{contract="custc-ce-to-pe"} == 0
  for: 60s
  labels: {severity: sev2, contract: custc-ce-to-pe, tenant: customer-c, managed_by: infrahub-intent}
- alert: custc-ce-to-pe-bgp_session_state-telemetry-stale
  expr: absent(bgp_session_state_established{contract="custc-ce-to-pe"})
  for: 20s
```

The expectation and the alert rule are two compilations of the same intent. The gate reads the
first, Prometheus the second; neither reads the other.

## 4. Adding monitoring to a contract

1. One `IntentObservabilityContract` under the **service's own intent**, with `consumer` set to
   whoever gets paged. Add it to `observability_contracts`.
2. One `IntentObservabilitySignal` per thing to watch: `signal`, `condition` (one of the four
   parsed forms), `frequency_seconds`, `severity`, and `watches` pointing at the contract.
3. The watched contract's `pe_devices` must be in `monitored_devices`, and their platform must
   claim a telemetry capability, or the `capability_present` projection blocks the merge.

That is everything authored. The collector type, subscription paths, alert names, labels and
dashboard panels are compiled. A signal that `watches` nothing is fleet-wide.

## 5. Adding a new compiled output

A new signal kind, a new contract kind or a new consumer (a ticketing system, a different
collector) follows the chain in § 1:

1. The authored term: a schema attribute or enum value (checklist B in
   [extension-checklists.md](extension-checklists.md)).
2. A query that reads it, and a transform arm per output. A signal kind needs three: the
   subscription paths per platform in `telemetry_collector.py`, the alert arm in
   `prometheus_rules.py`, and the metric mapping in `IH/monitoring/telegraf/telegraf.conf`.
3. An `artifact_definition` and a target group, if the output is a new artifact.
4. The expectation for it in the same change, carrying the join keys of § 2.
5. A consumer. An artifact nothing fetches or evaluates is a gap; record it in `status.md`.
