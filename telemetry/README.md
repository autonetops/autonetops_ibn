# telemetry/

Telemetry is not "monitoring" — it is the **observed-state input to the control
loop**. Its output contract is normalized, SoT-enriched state the validator can
reason about in intent terms.

The collectors and pipelines may *run* on separate infrastructure, but their
**contracts live here**, next to the expectations and validator rules they must
satisfy. That adjacency is deliberate: it prevents the failure mode where
"monitoring" is owned by a team that doesn't know what needs to be proven.

```
telemetry/
  collectors/        # one directory per protocol; config + deployment manifests
    gnmi/            # streaming subscriptions (interfaces, protocols, counters)
    bmp/             # BGP monitoring — RIB visibility for routing expectations
    syslog/
    ipfix/
    snmp/            # legacy / capability-gap fallback
  pipelines/
    normalization/   # vendor-neutral event/metric shapes
    enrichment/      # join with SoT metadata (role, region, tenant, contract)
    storage/         # storage backend interface (backend choice: ADR backlog)
  dashboards/        # dashboards as code (bgp-health, intent-compliance, …)
```

## Design rules

1. **Freshness is part of the contract.** Stale data is a validation failure,
   not silence.
2. **Enrichment uses Infrahub as its metadata source** — the same SoT that
   produced the configs, so identity never diverges.
3. Required signals per device role are declared as intent in Infrahub; the
   collectors' subscription configs should be *rendered from* that intent
   (an artifact) rather than maintained by hand — target state, phased in.
