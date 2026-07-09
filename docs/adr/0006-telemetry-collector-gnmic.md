# 0006 — Telemetry collection: gnmic primary, telegraf for legacy gaps

- Status: accepted
- Date: 2026-07-09

## Context

gNMI streaming is the core observed-state input. Two mainstream collectors
were compared: **gnmic** (OpenConfig project, purpose-built gNMI client) and
**telegraf** (InfluxData's general-purpose agent with a gNMI input plugin).

## Comparison matrix

| Criterion | gnmic | telegraf |
|---|---|---|
| gNMI depth (subscription modes, origins, updates-only, dial-out via tunnel) | ✅ Purpose-built, full coverage | ⚠️ Input plugin covers the common path, lags on edge features |
| Dynamic target management | ✅ Target loaders (file/HTTP/Consul/Docker) — SoT can add/remove devices without restarts | ❌ Static TOML; config regeneration + reload per change |
| Horizontal scale / HA | ✅ Native clustering (leader election, target distribution) | ⚠️ No native gNMI HA; shard manually, dedupe downstream |
| Processing pipeline | ✅ Processors (rename, convert, tag, event transforms) tuned for gNMI paths | ✅ Very mature, huge processor/aggregator set |
| Outputs | ✅ Prometheus, InfluxDB, Kafka, NATS, file… | ✅ Largest output ecosystem |
| Non-gNMI protocols (SNMP, syslog, exec, ping…) | ❌ gNMI only | ✅ One agent covers all legacy inputs |
| Config rendered as an Infrahub artifact | ✅ YAML; loaders mean only subscriptions/outputs need rendering | ✅ TOML renders fine, but every target change is a config change |
| Community fit | ✅ Standard in the OpenConfig/netops space | ✅ Broader general observability community |

## Decision

- **gnmic is the primary collector** for gNMI streaming: subscriptions and
  outputs rendered from observability intent (Infrahub artifact), targets fed
  by a file loader that is itself generated from SoT, clustering enabled when
  we scale past one collector.
- **telegraf is reserved for the legacy gap** — SNMP/syslog-only platforms —
  and is only introduced when such a platform actually enters SoT. One tool
  per job; both configs rendered, never hand-maintained.

## Consequences

- `telemetry/collectors/gnmi/` = gnmic deployment + rendered-config contract.
- `telemetry/collectors/snmp|syslog/` = telegraf, dormant until needed.
- The "subscriptions rendered from intent" pipeline needs an Infrahub
  transform (`telemetry_subscriptions`) — added to the infrahub/ backlog.
- Output backend (Prometheus/Mimir vs. ClickHouse) remains open in the ADR
  backlog; gnmic supports both paths, so this decision doesn't block it.
