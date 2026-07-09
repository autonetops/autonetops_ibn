# Architecture Overview

## What this platform is

`autonetops_ibn` implements a **closed-loop, intent-based networking platform**.
The loop is:

> intent → compile → plan → deploy → observe → validate → (feed back)

Infrahub owns the front half of the loop; this repository owns the back half.

## Component responsibilities

### Infrahub (schema, intent, SoT, compiler, renderer)

Infrahub is the desired-state system:

- **Schema** — the data model for intent and SoT nodes. Versioned in
  `infrahub/schemas/` and loaded via repository sync (`.infrahub.yml`).
- **Intent** — what the network *should* do (tenants, routing contracts,
  security policy, observability requirements). Lives as data in Infrahub,
  edited through branches + proposed changes.
- **SoT** — what *exists* (devices, links, IPAM, roles, capabilities).
- **Compiler** — Python transforms (`infrahub/transforms/`) that resolve
  intent + SoT into normalized, vendor-neutral per-device data.
- **Renderer** — Jinja2 templates (`infrahub/templates/`) that render
  vendor-specific artifacts.

Infrahub **artifacts** are the hand-off boundary. Two artifact classes matter:

1. **Config artifacts** — per-device rendered configuration.
2. **Expectation artifacts** — per-device/per-contract statements of what must
   be observably true after deployment (sessions up, routes present, policy
   attached, telemetry signals fresh). These are what the validator consumes.

Infrahub's branch + proposed-change workflow is our review process: checks
(`infrahub/checks/`) run inside proposed changes and act as merge gates.

### Planner (`planner/`)

Planning is **policy**; deployment is **execution**. The planner answers
"is this safe, and in what order?" without touching a device:

- Diffs candidate artifacts (Infrahub branch) against deployed state.
- Computes **blast radius**: affected devices, regions, tenants, contracts.
- Applies safety policies (change windows, canary strategy, rate limits) that
  live as **reviewable data** in `planner/policies/`, not as code.
- Emits a declarative **Plan** document: ordered steps, canary stages,
  validation checkpoints, abort criteria.

### Deployer (`deployer/`)

The deployer executes a Plan and nothing else:

- Transport adapters (gNMI / NETCONF / SSH / vendor API) isolated per protocol.
- **Rollback is a first-class concept**: vendor transactional semantics
  (Junos commit-confirmed, IOS-XR commit replace, EOS checkpoints) live in
  `deployer/rollback/`, tested independently of workflow logic.
- Workflows implement canary progression and stop on validation-gate failure.

### Telemetry (`telemetry/`)

Telemetry is not "monitoring" — it is the **observed-state input to the control
loop**. Collectors (gNMI, BMP, syslog, IPFIX, SNMP) feed normalization and
enrichment pipelines. Enrichment joins observed data with SoT metadata so the
validator can reason in intent terms ("customer-c's contract"), not interface
counters. The collectors may *run* elsewhere; their contracts live here.

### Validator (`validator/`)

The validator turns intent into something enforceable:

- Compares **expectation artifacts** against **observed state**.
- Classifies drift (benign vs. dangerous) instead of raising raw diffs.
- Maps failures to remediation classes: auto-fixable, quarantined, human.
- Reports back into Infrahub (compliance status on intent nodes) and to the
  planner (block further rollout when the canary is failing).

### Simulations (`simulations/`)

Incidents become regression tests: containerlab topologies plus expectation
checks. CI can spin a golden topology, deploy candidate artifacts, and prove
invariants before merge.

## Trust and data-flow boundaries

- Only the **deployer** talks to network devices for writes.
- Only **telemetry collectors** talk to devices for reads (streaming).
- Only **Infrahub** stores intent; nothing in this repo invents desired state.
- The planner and validator are pure functions over data (artifacts, plans,
  observed state) — this is what keeps them testable and auditable.

## Open design questions

Tracked as ADRs as they get decided. Current open items:

- Plan document schema and where plans are stored/versioned (ADR pending).
- Event bus between layers (webhook-driven vs. message broker). (ADR pending)
- Telemetry storage backend and retention. (ADR pending)
- Deployment target for the platform itself (compose → k8s path). (ADR pending)
