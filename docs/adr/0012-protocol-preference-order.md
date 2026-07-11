# 0012 — Protocol preference order for delivery strategy selection

- Status: accepted
- Date: 2026-07-11
- Refines: ADR-0008 (libraries), ADR-0011 (capability matrix)

## Context

Most platforms speak several management protocols. The planner needs a
deterministic rule for which one carries a config change, because the
protocol decides the available delivery strategy (confirm windows, atomic
replace, dry-run) and therefore the rollback plan.

## Principle

**For config delivery, transactional safety beats structural elegance.**
The protocol that gives the strongest native revert semantics on that
platform wins — even when a "more modern" protocol exists. For
reads/verification, streaming and structure win. Concretely:

1. **Config writes** — prefer, in order:
   1. Candidate + commit-confirmed/auto-revert semantics
      (NETCONF on Junos/IOS-XR; eAPI config sessions with commit timer on EOS)
   2. Atomic full/subtree replace without confirm (gNMI SetRequest — SR Linux
      and other gNMI-native NOSes) → planner pairs it with snapshot_revert +
      a stricter gate
   3. Structured vendor HTTP API without transactions → snapshot_revert +
      mandatory simulation gate
   4. CLI screen-scraping — last resort, `manual` rollback, never silently
      chosen (requires explicit per-platform pin in the policy file)
2. **State reads / verification probes** — gNMI (subscribe/once) →
   NETCONF get → vendor API → CLI. (Telemetry stays gnmic-first, ADR-0006.)
3. **Controllers** — their native API by definition; the "protocol choice"
   moves inside the controller and our lever is its revision/rollback model.

## Mechanics

- Each **driver** declares its supported protocols in preferred order in its
  `CapabilityMatrix` (executor, ADR-0011) — the authority on what *works*.
- The **planner** holds the *policy*: `planner/policies/delivery_preferences.yaml`
  (data, reviewable) mapping platforms to ordered protocol lists, with a
  global default for unlisted platforms. The planner stamps the chosen
  protocol on each Plan step; the driver refuses (loudly) if it can't honor it.
- When SoT capability records land in Infrahub, per-device capability
  (e.g. an old Junos without NETCONF) filters the list before preference
  applies; until then the platform-level table is the interim source.

## Default table (initial; the YAML file is authoritative)

| Platform | Order | Resulting delivery strategy |
|---|---|---|
| junos | netconf → gnmi → cli | commit-confirmed |
| iosxr | netconf → gnmi → cli | commit-confirmed |
| eos | eapi → gnmi → cli | config-session commit timer / checkpoint |
| srlinux | gnmi → json_rpc | atomic replace + snapshot_revert |
| cloudvision (controller) | http_api | controller revision revert |

## Consequences

- Plan steps carry `protocol`; the schema is regenerated.
- A platform absent from both the YAML and the driver registry produces a
  step with `protocol: null` — the driver's own preference order applies.
- Choosing CLI for delivery always requires an explicit policy entry — it can
  never be reached through defaults.
