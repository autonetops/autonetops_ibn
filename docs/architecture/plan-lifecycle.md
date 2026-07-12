# Plan Lifecycle

How a rollout Plan is **compiled**, **extended** with new evaluations,
**presented** for review at any moment, **customized** by its requester, and
**gated** before and during execution. This document is the map; the binding
decisions live in ADR-0003 (storage/approval), ADR-0013 (timeline/dispatch)
and ADR-0014 (pre-approved plan classes).

Each section separates **implemented** (true in code today, with file
references) from **target** (accepted design, not built yet). The honesty
markers in the code (`not_evaluated`, `strategies: []`, empty `flows/`) are
deliberate — this document follows the same rule.

## What a Plan is

A Plan is a declarative, generated, immutable rollout document — never written
by hand, never edited after approval. The unit of storage and review is the
**plan bundle**, a directory `plans/<plan-id>/`:

| File | Written by | Content |
|---|---|---|
| `plan.yaml` | planner | The Plan (contract `contracts/plan/v1/plan.schema.json`): source branches, blast radius, canary stages/steps, gates, rollback, abort criteria |
| `timeline.yaml` | orchestrator | Per-stage window fit: `starts_at` / `ends_by` / `soak_until`, `feasible` flag |
| `decision.yaml` | orchestrator | Dispatch decision: `mode`, `reasons`, `approvals_required`, `window`, `priority`, `emergency_override` |
| `content/` | orchestrator | Frozen rendered artifacts, one file per target + definition, checksum-pinned by the plan's steps |
| `expectations/` | orchestrator | Rendered `ContractExpectations`, one per intent contract on the candidate branch |
| `evidence.jsonl` | dispatch | Append-only record of every executor verb, gate verdict, baseline, override |
| `report.yaml` | dispatch | Outcome: per-stage results, gate summaries, status (`waiting`, or terminal `succeeded \| failed \| aborted \| checked`) |

The bundle is the immutable hand-off (ADR-0013 §3): a merged (deleted)
Infrahub branch can no longer change what was approved, and every payload is
checksum-verified against the plan before it touches a device
(`executor/src/autonetops_executor/runner.py`). Plan IDs are
content-addressed over `source + stages`
(`planner/src/autonetops_planner/models.py`), so metadata annotations
(approvals, classifications, schedules) never perturb plan identity.

## Lifecycle states

```
            compile                    approve                       execute
 intent ──► compiled ──► pending ────► approved ──► scheduled ──► dispatching ──► succeeded
 (PC open)     │         review  │        ▲          /waiting        │   │
               │                 │        │                          │   ├──► failed
               │                 └── pre-approved class              │   └──► aborted
               │                     (ADR-0014, policy = approval)   │
               └─────────────► superseded ◄──────────────────────────┘
                               (a new plan replaces this one — the only "edit")
```

Where each state is visible:

- **compiled / pending review** — the bundle exists under `plans/`;
  `decision.yaml` carries `mode: immediate | scheduled | needs_approval |
  blocked` (`orchestrator/src/autonetops_orchestrator/strategy.py`).
- **waiting** — `report.yaml` `status: waiting` (window not open, or a manual
  gate paused the plan); dispatch exit code 3; retried by `watch`.
- **terminal** — `report.yaml` `status: succeeded | failed | aborted |
  checked`. Non-`--check` outcomes (including `waiting`) are mirrored into
  the SoT as an `OpsPlanRecord` node
  (`infrahub/schemas/ops_plan_record.yml`,
  `orchestrator/src/autonetops_orchestrator/feedback.py`); `checked` stays on
  disk only, because `--check` runs skip SoT feedback.
- **superseded** — implicit today (a newer plan for the same branches);
  becomes explicit when the plan record grows a `superseded_by` field.

## 1. Compiled

**Implemented.** `ibn-orchestrate plan` (or the `watch` loop, on every *open*
Infrahub proposed change) runs the pipeline
(`orchestrator/src/autonetops_orchestrator/cli.py`):

1. **Render** both branches in-process — the SoT repo's own GraphQL queries +
   transform classes, same bytes as the server (`render_source.py`, ADR-0013 §3).
2. **Diff** artifacts by checksum per (target, definition)
   (`planner/src/autonetops_planner/diffing.py`).
3. **Blast radius** over affected devices → `low | moderate | high`
   (`blast_radius.py`; ≤2 devices low, ≥10 devices or ≥2 regions high).
4. **Canary strategy** selected by blast-radius class (`policies.py`).
   Policy data belongs in `planner/policies/canary_strategies.yaml`, but the
   file is only read when `--policies-dir` points at it — the default path
   (and always the `watch` loop) uses the builtin strategies; the shipped
   file's `strategies: []` also falls back to builtins.
5. **Stages** partitioned over control points (`one_target` / `one_per_role` /
   `remainder`), each with a validation gate; a trailing remainder is
   auto-appended so no target is dropped (`plan_builder.py`).
6. **Protocol** per step: per-platform delivery preference order ∩ what the
   artifact's `content_format` can ride (`select_protocol`, ADR-0012). Driver
   capabilities are *not* consulted at plan time — a platform absent from the
   preference table yields `protocol: null`, deferring to the driver's own
   declared order.
7. **Timeline** against SoT change windows (`OpsChangeWindow` nodes), stage
   duration = steps × 3 min, soak chains stages (`timeline.py`, ADR-0013 §4).
8. **Priority** inherited from the intents whose contracts run on the changed
   devices — never typed by hand (`priority.py`, ADR-0013 §5).
9. **Decision** — one of four modes (§5 below) — then the whole bundle is
   persisted.

**Target.**

- The planner opens the plan as a **PR** under `plans/` with a bot identity
  and blast-radius annotations (ADR-0003 — the bundle lands on disk today,
  committed manually; bot identity is still in the ADR backlog).
- **Change-class classification** joins the pipeline between diff and
  strategy selection (ADR-0014): classify *what kind of change this is* from
  the artifacts' bytes. The bytes are already rendered and frozen into
  `content/` at plan time — but no pipeline *decision* reads them: diffing
  and strategy selection see only checksums, so today the compiler cannot
  tell an interface-description edit from a BGP policy rewrite.
- Webhooks short-circuit the poll interval (ADR-0004); the `watch` loop stays
  as the reconciliation guarantee.
- The same pipeline phases wrap 1:1 into Prefect tasks
  (`orchestrator/flows/`, ADR-0005/0013 §2) — the Prefect server is already
  provisioned in `infra/terraform`, unused by any code.

## 2. Extended — new evaluations from intentions and contracts

The extension model: **every evaluation traces back to intent.** Config
artifacts and expectation artifacts are compiled siblings from the same
Infrahub intent (repo rule: every config artifact has a sibling expectation
artifact); a check nobody can trace to a contract does not get to block a
rollout.

**Implemented seam** (this is the recipe for adding an evaluation):

1. **Compile it from intent**: a transform + GraphQL query in the SoT repo
   renders an expectation block per intent kind. Today
   `render_expectations()` is hardcoded to one pair —
   `IntentRoutingContract` → `ContractExpectationsTransform`
   (`render_source.py`).
2. **Parse and evaluate it in the validator**:
   `ExpectationSet.from_artifacts` currently reads only
   `spec.bgp.sessions`; the rendered artifacts *already* carry `routePolicy`
   (max prefixes, allowed prefixes, communities), `telemetry.required`
   (freshness) and `alerting` blocks that nothing consumes yet — each is a
   ready-made evaluation waiting for a parser field and an `evaluate_*`
   sibling of `evaluate_sessions` (`validator/src/autonetops_validator/`).
3. **Collect the matching facts**: extend the executor `get_facts` verb
   per-driver (today the SR Linux and EOS drivers return parsed
   `bgp_neighbors`; the mock and NETCONF drivers return other facts); facts
   flow through `collect_facts` unchanged.
4. **Only if the checkpoint semantics are new**, add a `Gate.kind`. The kind
   is a closed enum — planner Literal (`models.py`), generated contract, and
   the dispatch branch (`dispatch.py`, which treats any unknown kind as a
   pausing manual gate) must change together.

Gate semantics that new evaluations inherit for free: pre-change **baseline**
(gates block on regressions, never on pre-existing drift), **soak**,
**unverifiable as a first-class verdict** (never silently passes; a
just-changed device that goes unobservable *fails* the gate), and
neighbor-scoped proof (a CE change is proven on the PE that faces it).

**Target.**

- Generalize `render_source.py` to a registry of
  *(intent kind → query → transform)* so new contract kinds get expectation
  coverage without orchestrator changes.
- **Verification suites** (`remediation/verifications/`, schema to be
  formalized under `contracts/verification/v1/`): declarative checks with
  mandatory intent traceability (`derives_from: infrahub://...`), triggers
  (`post_deploy`, `nightly`), and an `on_fail` remediation class. Plan stage
  gates reference suites by name — this is the growth path beyond the
  two-value gate enum.
- **Intent-merge checks** (`infrahub/checks/`, scaffolded in `.infrahub.yml`):
  evaluations that must block the *intent* (IPAM bounds, invariant removal,
  redundancy floors) run as Infrahub checks on the proposed change — before a
  plan is ever compiled. Rollout gates and intent checks are different
  planes; extend the right one.
- **Simulation gate** in CI (named in the target-gate-set header comment of
  `.github/workflows/ci.yaml`; no job exists yet): deploy candidate artifacts
  to a golden containerlab topology and run the same validator before merge —
  the same evaluations, third context.

## 3. Presented — retrieve and review at any moment

**Implemented.**

- The **bundle in Git is the canonical record** at every stage. Everything in
  `plans/<plan-id>/` is meant to be committed — including `evidence.jsonl`
  and `report.yaml` (only `.watch-state.json` is gitignored). Review = read
  the diff; audit = read the history.
- `watch` plans every **open** proposed change, so the blast radius, timeline
  and decision are reviewable *before anyone clicks merge* (`watch.py`).
- Human summaries at plan time (id, blast radius + devices, strategy,
  priority with source intents, per-stage schedule, decision + reasons) and
  `ibn-orchestrate windows` for the schedule landscape (`cli.py`).
- After dispatch, the outcome is upserted into the SoT as an
  **`OpsPlanRecord`** node — compliance state queryable in Infrahub next to
  the intent that caused the change, not only on one operator's disk
  (`feedback.py`; feature-detected, degrades to a loud skip).

**Target.**

- **A plan is retrievable in the SoT at *every* lifecycle stage, not only
  after dispatch**: upsert the `OpsPlanRecord` at plan time with
  `status: planned | awaiting_approval | scheduled`, and extend the schema
  with `approvals_required`, supplied approver names, decision reasons, a
  `pre_approved_class` label (ADR-0014) and relationships to devices /
  intents / the proposed change. This is the deliberate on-ramp to ADR-0003's
  Option B (plans as Infrahub objects) without moving storage yet.
- **`ibnctl` grows the operator verbs** already promised in
  `tools/README.md`: `plan list` / `plan show <id>` (render the bundle
  human-first), `plan status` (decision + report + SoT record), `abort`
  (the plan's own `abort_criteria` name "manual abort via ibnctl", which does
  not exist yet).
- The plan **PR** is the review surface for approval (ADR-0003) — one place
  where diff review, comments and CODEOWNERS already work.
- Productization keeps the contract and swaps the view: "a UI, an API, and an
  approval workflow are all views over Plans"
  (`docs/architecture/scaling-and-productization.md`).

## 4. Customized — strategy and timing

The customization principle: **users influence a plan by editing reviewed
data — policy files and SoT nodes — never by editing the plan document.**
A generated, immutable document that people hand-tune stops being evidence.

**Implemented knobs.**

| Axis | Knob | Where |
|---|---|---|
| Rollout shape | Canary strategies: per-stage `select` / `soak_minutes` / `gate`, `requires_approvals`, keyed by blast radius | `planner/policies/canary_strategies.yaml` (+ `--policies-dir`) |
| Delivery | Per-platform protocol preference order | `planner/policies/delivery_preferences.yaml` |
| Timing | **Change windows and freezes are SoT intent data** (`OpsChangeWindow`: recurring weekly or absolute, `max_blast_radius` ceiling, device scope) — reviewed like any other intent | Infrahub (ADR-0013 §1) |
| "Run at time X" | An **absolute-shaped window scoped to the plan's devices** can pin the start today — but only when it yields the earliest eligible slot: `next_slot` takes the earliest across *every* window matching the devices and blast radius, so a sooner-opening standing window still wins | Infrahub |
| What-if | `plan --at <ISO>` evaluates timeline + decision as if now were T | `ibn-orchestrate` |
| Dispatch-time | `--check` (dry-run everywhere), `--wait` (sleep to window), `--override-windows` (lab/emergency; skips window re-checks — despite the CLI help, the flag itself is not written to evidence or the SoT record today), `--soak-scale`, `--approve NAME` | `DispatchOptions` |
| Break-glass | `--stage N` (run one stage), `--content-dir` | `ibnctl apply` |
| Emergency | `--emergency` + intent-inherited `critical` priority only; the override goes on the record | `strategy.py` |

**Target.**

- **Requested strategy**: the change author may *request* a canary strategy
  (annotation on the proposed change, or a plan-time flag). The planner
  validates the request against policy — a request may **tighten** the rollout
  (more stages, longer soak, extra approvals), never weaken it below the
  policy floor for the blast radius / change class.
- **First-class "not before T"**: a `not_before` field on the Decision plus a
  matching `DispatchOption`, honored inside the per-stage window fit — so
  pinning a time no longer requires creating a window. The window model stays
  authoritative: `not_before` can only delay into a later eligible slot.
- **Durable scheduling**: Prefect deployments replace `--wait` foreground
  sleeps and give "run at time X" and human-in-the-loop pauses a home that
  survives restarts (ADR-0005; `orchestrator/flows/` is reserved for exactly
  this).
- Strategy selection widens beyond blast-radius class to include the change
  class (ADR-0014) — a descriptions-only change can legitimately map to a
  no-soak single-stage strategy.
- Blast-radius thresholds move from hardcoded defaults into
  `planner/policies/` (already accepted intent in `blast_radius.py`'s
  docstring; `compute_blast_radius` takes a `Thresholds` param that is simply
  not plumbed).

## 5. Gated

Approval is deliberately **two separate planes** (ADR-0003): the Infrahub
proposed change approves the **intent** ("is this what we want?"); the plan
approves the **rollout** ("is this safe to do, this way, now?"). The person
who approves a routing contract is not necessarily the person who approves
touching 40 PEs on a Friday. Runtime gates are a third plane that no approval
bypasses.

| Plane | Gate | Status |
|---|---|---|
| Intent | Proposed-change review in Infrahub; `infrahub/checks/` safety checks | Review implemented (Infrahub); checks scaffolded |
| Rollout | Plan PR review under `plans/` (CODEOWNERS, blast-radius-scaled bar); merge = execution trigger | Decided (ADR-0003); PR automation not built — today `watch` keys on the *intent* PC merge |
| Rollout | Dispatch decision: `immediate \| scheduled \| needs_approval \| blocked`; named approvals from the canary strategy, enforced at dispatch (`--approve`) | Implemented |
| Rollout | Emergency = an override **with a name on it**, not a mode: `--emergency` + inherited `critical` priority; recorded in decision + evidence | Implemented |
| Runtime | Windows re-checked per stage at execution time — "a schedule computed at plan time is a forecast, not a permission" | Implemented |
| Runtime | Stage gate `validator.expectations_pass`: baseline, soak, regression-only blocking, unverifiable-fails-if-changed | Implemented |
| Runtime | `abort_on_failure`, `rollback_failed` always aborts ("page a human"), `removed_targets` never auto-executed | Implemented |

### Pre-approved plan classes

Some changes should not queue behind a human: interface descriptions,
cosmetic metadata, any change whose *entire* diff is provably inside a class
that rollout approvers have already reviewed **as a class**. ADR-0014 defines
the mechanism: reviewed change-class policy data + a content-aware classifier
in the planner + fail-closed eligibility + the classification recorded in the
plan, the decision and the SoT record. Pre-approval moves the review earlier
— onto the class definition — it does not remove review, and it removes
**only** the human plan-review step: windows, stage gates, evidence and
feedback still apply unchanged.

Today's *de-facto* pre-approval — low/moderate blast radius selects a builtin
strategy with no required approvals, and `watch --auto-dispatch` (default on)
executes on PC merge — is blunt: it cannot distinguish a description edit
from a BGP rewrite on three devices. ADR-0014 replaces "small is safe" with
"provably in a reviewed class is safe".

## Known gaps (verified against code, in priority order)

1. **`watch` dead-ends `needs_approval` plans**: its dispatch closure
   hardcodes `approvals=[]` and any non-`waiting` exit is marked dispatched —
   a high-blast plan merged under watch aborts once on "missing approvals"
   and is never retried. Fix: make `needs_approval` a non-terminal state and
   inject an approval source (plan-PR reviews) into the watch closure.
2. **`decision.yaml` is not integrity-protected**: editing it to clear
   `approvals_required` or set `emergency_override` changes gating
   undetected. Fix: dispatch re-derives the decision floor from policy +
   frozen content at dispatch time; the recorded decision may only *tighten*.
3. **Approver names are free strings** (`--approve alice`). Near-term: map
   plan-PR review identities; productization: RBAC in the approval service.
4. **Priority is self-escalatable**: it is read from the *candidate* branch,
   and priority is what unlocks `--emergency`. Rule needed: inherit priority
   from `main` (the intent must already be critical before the change).
5. **Dispatch-time window re-check ignores stage duration** (`next_slot`
   called without `need_minutes`): a stage can start in a window too short to
   finish it. The parameter exists and is tested — pass it.
6. **`RollbackSpec.confirm_timeout_minutes` is unwired**: `run_step` confirms
   immediately. Holding the commit-confirm window open *across the validator
   gate* (auto-revert on gate failure) is the strongest automated gate the
   contract already promises.
7. **CI gates**: committed `plans/*/plan.yaml` are never schema-validated;
   `policy-validate` and `simulation-gate` exist only as entries in
   `ci.yaml`'s header comment listing the target gate set — neither has a
   job defined.
8. **Reconcile gap**: a proposed change merged before `watch` ever saw it
   open is recorded as handled but never planned — the promised
   merged-but-unrun scan does not exist.
9. **`watch` pins default policies** (`policies_dir=None`): custom strategies
   (including custom approval bars) can never apply in the automated path.
