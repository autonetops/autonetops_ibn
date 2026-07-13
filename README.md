# autonetops_ibn

Intent-Based Networking (IBN) platform for AutoNetOps.

This repository is the home of the **closed-loop automation platform** that sits
around [Infrahub](https://docs.infrahub.app/). The division of responsibility is
deliberate and is the single most important thing to understand about this repo:

| Concern | Lives in | Notes |
|---|---|---|
| Schema (data model) | **Infrahub** | Loaded from `infrahub/schemas/` via repo sync |
| Intent | **Infrahub** | Nodes/branches/proposed changes in Infrahub |
| Source of Truth (SoT) | **Infrahub** | Devices, links, IPAM, topology |
| Compiler (transforms) | **Infrahub artifacts** | Python transforms in `infrahub/transforms/` |
| Renderer (templates) | **Infrahub artifacts** | Jinja2 templates in `infrahub/templates/` |
| Planner | **this repo** → `planner/` | Safety, blast radius, ordering, change policy |
| Orchestrator | **this repo** → `orchestrator/` | Workflows: rollout, reconcile, remediate (Prefect) |
| Executor | **this repo** → `executor/` | The only component touching the network: drivers, transports |
| Telemetry | **this repo** → `telemetry/` | Observed state: collectors, pipelines |
| Validator | **this repo** → `validator/` | Expectations vs. observed state, drift |
| Simulations | **this repo** → `simulations/` | Containerlab topologies, regression scenarios |
| Infra | **this repo** → `infra/` | How the platform itself is deployed |

Infrahub is the **desired-state brain**; this repo is the **nervous system and
muscles**: it decides *how* to apply what Infrahub says should exist, applies
it, observes reality, and proves (or disproves) compliance.

## Repository layout

```
autonetops_ibn/
  .infrahub.yml          # Infrahub repository-sync manifest (schemas, transforms, templates, checks)
  docs/                  # Architecture, data flows, component contracts, ADRs, runbooks
  infrahub/              # Everything Infrahub syncs: schemas, queries, transforms, templates, generators, checks
  contracts/             # Generated JSON Schemas for cross-layer contracts (Plan v1, …)
  plans/                 # Rollout Plans as PRs: review = approval, merge = execution trigger (ADR-0003)
  planner/               # Python pkg: diffing, blast radius, plan building; policies as data
  orchestrator/          # Prefect flows: deploy, reconcile, remediate, onboard (ADR-0010)
  executor/              # southbound layer: drivers (NOS/API/controller) + transports (ADR-0010/0011)
  telemetry/             # Observed state: gnmic-first collectors (ADR-0006), pipelines, dashboards
  validator/             # Passive proof: compliance rules + drift classification (telemetry-driven)
  remediation/           # Active verification suites + remediation playbooks (content library)
  simulations/           # Containerlab fabrics and golden topologies (incidents as regression tests)
  infra/                 # Deployment of the platform itself (compose for lab, helm/terraform for prod)
  tools/                 # ibnctl CLI, migration and import helpers
  .github/workflows/     # CI gates (schema validation, golden tests, simulation gates)
```

## The closed loop

```
        ┌─────────────────────────── Infrahub ────────────────────────────┐
        │  Schema · Intent · SoT · Compiler (transforms) · Renderer       │
        │  (branches + proposed changes = review workflow)                │
        └───────────────┬──────────────────────────────▲──────────────────┘
                        │ artifacts                    │ drift / compliance
                        │ (configs + expectations)     │ feedback
                        ▼                              │
   ┌──────────┐    ┌──────────┐    ┌───────────┐    ┌───┴───────┐
   │ planner  │ →  │ orchestr.│ →  │ executor │ →  │ network │ → telemetry → validator
   │ (is it   │    │ (do it   │    │           │    │ (what is  │   (prove it)
   │  safe?)  │    │  safely) │    │           │    │  true?)   │
   └──────────┘    └──────────┘    └───────────┘    └───────────┘
```

1. Intent changes happen in Infrahub (branch → proposed change).
2. Infrahub compiles + renders **artifacts**: per-device configs *and* expectations.
3. The **planner** diffs candidate artifacts against deployed state, computes
   blast radius, and emits a reviewable, declarative **Plan**.
4. The **orchestrator** runs the rollout flow; the **executor** performs each
   control-point operation with driver-declared transactional semantics
   (commit-confirmed, checkpoints, controller revisions).
5. **Telemetry** streams observed state into normalized pipelines.
6. The **validator** compares expectations vs. observed state, classifies drift,
   and feeds results back into Infrahub / the planner.

## Where to start

- New to the project → `docs/architecture/overview.md`
- The words this project is built on (intent, contract, policy, invariant) →
  `docs/architecture/intent-model.md`
- Understanding component boundaries → `docs/architecture/component-contracts.md`
- How a rollout Plan lives (compiled → approved → gated → executed) →
  `docs/architecture/plan-lifecycle.md`
- How to run it (Prefect vs CI, executor placement, triggers, queues) →
  `docs/architecture/runtime-topology.md`
- Why things are the way they are → `docs/adr/`
- Operating the system → `docs/runbooks/`
- Deploying the platform through Styrmin (Application Driver, Helm chart,
  container image) → `docs/integrations/styrmin.md`

## Working on the Python packages

The five packages (`planner`, `orchestrator`, `executor`, `validator`,
`tools/ibnctl`) form a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
rooted at the top-level `pyproject.toml`:

```
uv sync          # create .venv with all packages + dev tools
uv run pytest planner/tests executor/tests orchestrator/tests validator/tests
uv run ruff check planner executor orchestrator validator tools
```

## Status

🚧 Build order: **planner** ✅ (diff → blast radius → staged Plan over control
points, protocol selection per ADR-0012) → **executor** 🚧 (verb contract +
capability registry + reference driver ✅; SR Linux driver pending containerlab
integration) → **orchestrator flows** → **telemetry** → **validator**,
proving the full loop on a containerlab topology.
Key decisions so far: ADR-0003 (plans as Git PRs), ADR-0004 (webhooks first),
ADR-0005/0009/0010 (orchestrator and executor as separate first-class roles),
ADR-0006 (gnmic), ADR-0007 (Python), ADR-0008 (typed transport libraries),
ADR-0011 (control-point target model: NOS / API vendors / controllers),
ADR-0012 (protocol preference: transactional safety first).
