# 0013 — Orchestrator flow: SoT change windows, timeline evaluation, dispatch decision

- Status: accepted
- Date: 2026-07-12

## Context

The planner (ADR-0011/0012) answers *what* changes and *in what order*; the
executor answers *how one step lands on one device*. Nothing answered *when*:
change windows, freezes, approval requirements, and the decision to dispatch
now versus wait. The draft `planner/policies/change_windows.yaml` said
"enforced by the planner, schema TBD".

## Decision

1. **Change windows live in the SoT** (`OpsChangeWindow` in Infrahub), not in
   a policy YAML. They are operational intent — reviewed, versioned and
   queried exactly like the rest of the model. One kind, two shapes:
   recurring weekly (`days` + `start_utc` + `duration_minutes`) and absolute
   (`starts_at` + `ends_at`, used mainly by freezes). Windows carry a
   `max_blast_radius` ceiling and a device scope (empty scope = fleet-wide).
   The draft YAML is retired; `planner/policies/` keeps canary strategies,
   delivery preferences and rate limits.

2. **The orchestrator is a plain library first** (`autonetops-orchestrator`,
   CLI `ibn-orchestrate`), per ADR-0005's "independently runnable package"
   rule. Its phases map 1:1 to future Prefect tasks:
   `render → diff/plan (planner) → evaluate timeline → decide → dispatch`.
   No Prefect imports; `orchestrator/flows/` wraps these functions when the
   Prefect deployment lands.

3. **Artifacts are rendered in-process per branch** (RenderedArtifactSource):
   the SoT repo's own GraphQL queries + transform classes, executed against
   any branch. Same query, same renderer, same bytes as the server — without
   depending on Git-sync timing. The plan directory
   (`plans/<plan-id>/{plan,timeline,decision}.yaml + content/ + expectations/`)
   is the immutable hand-off to dispatch: a merged (deleted) branch can no
   longer change what was approved, and every payload is checksum-verified
   against the plan before it touches a device.

4. **Timeline evaluation is sequential fit**: each stage needs
   `steps × 3 min` inside an eligible maintenance window (blast-radius
   ceiling + device scope honored), freezes defer or truncate slots, soak
   time chains stages. Windows are re-checked at dispatch time — a schedule
   computed at plan time is a forecast, not a permission.

5. **The dispatch decision is one of four modes**: `immediate`, `scheduled`,
   `needs_approval` (canary strategy demands named approvals, supplied via
   `--approve`), `blocked` (no eligible window in the horizon). Emergency is
   an *override with a name on it*, not a mode: `--emergency` plus a
   critical-priority intent dispatches immediately and writes the override
   into the decision and the evidence log. Priority is never typed by hand —
   it is inherited from the intents whose contracts run on the changed
   devices (highest wins).

6. **The stage gate is real**: `validator.expectations_pass` renders the
   candidate branch's ContractExpectations, scopes them to the stage's
   devices, collects facts through the executor verb contract
   (`get_facts` now returns parsed `bgp_neighbors`), and evaluates via
   `autonetops-validator`. Unverifiable is a first-class verdict: a device
   nobody can observe is reported, never silently passed. A failed gate
   aborts the plan before the next stage.

7. **One verb sequence, two consumers**: the per-step
   snapshot → dry_run → apply → confirm / rollback-on-failure walk moved
   into `autonetops_executor.run_step()`; `ibnctl` (manual) and
   `ibn-orchestrate dispatch` (flow) both call it, so the sequence cannot
   drift between the break-glass path and the orchestrated path.

## Consequences

- `ibnctl` no longer pretends to evaluate gates; it points at
  `ibn-orchestrate dispatch`.
- `watch` implements the ADR-0004 reconcile half against proposed changes:
  plan on open (reviewable before merge), dispatch on merge, state on disk.
- Rate limits remain `not_evaluated` in `policy_evaluation` — honest until
  a rate-limit evaluator exists.
- Absolute-time windows assume UTC everywhere; a timezone field is a
  deliberate non-feature until someone needs it.
