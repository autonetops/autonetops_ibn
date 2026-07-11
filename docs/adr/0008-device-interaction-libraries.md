# 0008 — Device interaction: typed per-transport libraries, not a runner framework

- Status: accepted
- Date: 2026-07-11

## Context

The executor needs to push config and drive commits/rollbacks. Candidates:
Ansible, Netmiko, Nornir (+plugins), or direct per-transport libraries.

The deciding constraint comes from ADR-0005: **the executor performs one
device-level operation at a time; concurrency, batching and ordering live in
the Plan and in Prefect.** The Plan *is* the inventory. That removes the main
selling point of inventory-runner frameworks before the comparison starts.

## Comparison matrix

| Criterion | Ansible | Netmiko | Nornir + plugins | Direct libs (chosen) |
|---|---|---|---|---|
| Usable as a typed library inside the executor | ❌ Subprocess/ansible-runner boundary | ✅ but low-level | ✅ | ✅ |
| Transactional semantics (commit-confirmed / replace / checkpoint) | ⚠️ Varies per module, hidden from caller | ❌ Hand-rolled over CLI | ⚠️ Via NAPALM, good but abstracted | ✅ Full, explicit control — required by `deployer/rollback/` |
| gNMI support | ⚠️ Marginal | ❌ | ⚠️ Via extra plugins | ✅ pygnmi first-class |
| Concurrency/inventory | Built-in (forks) — **redundant with Plan+Prefect** | None | Built-in runner — **redundant with Plan+Prefect** | Not needed at this layer ✅ |
| Testability against containerlab in CI | ⚠️ Slow, process-per-run | ✅ | ✅ | ✅ |
| Evidence extraction (diffs, commit IDs, RPC replies) | ⚠️ Parsing module output | ⚠️ Screen-scraping | ⚠️ Plugin-dependent | ✅ Native structured replies |
| Ecosystem/hiring familiarity | ✅ Largest | ✅ | ✅ In netops | ⚠️ Smaller, but ADR-0005's adapter interface contains the risk |

## Decision

The executor's transport adapters use **direct, typed libraries**:

| Adapter | Library |
|---|---|
| `adapters/gnmi/` | **pygnmi** |
| `adapters/netconf/` | **ncclient** (scrapli-netconf acceptable alternative) |
| `adapters/ssh/` | **scrapli** (async-friendly, structured platform drivers) |
| `adapters/vendor_api/` | vendor SDKs where transactional semantics demand it (e.g. Junos PyEZ inside `rollback/junos*`) |

Explicitly rejected **for the control loop**:

- **Ansible** — not a library; per-module idempotency semantics are opaque,
  and the deployer must own its semantics. Remains acceptable for one-off
  out-of-band ops tasks outside the loop.
- **Nornir** — good tool, wrong layer: its inventory+runner duplicates
  Plan+Prefect. If we ever need bulk ad-hoc reads outside plans (audits),
  Nornir with the scrapli plugin is the sanctioned choice there.
- **Netmiko** — fallback driver only, if scrapli lacks a platform.

## Consequences

- The adapter interface (apply / diff / commit / confirm / rollback, returning
  structured evidence) is the stable contract; libraries behind it are
  swappable per platform without touching flows.
- Each adapter gets integration tests against a containerlab NOS image; the
  simulation harness doubles as the adapter test bench.
