# Running the platform: runtime topology

How the platform is deployed, triggered and scaled — the operational
synthesis of ADR-0004 (eventing), ADR-0005 (Prefect), ADR-0009 (executor
split), ADR-0010 (component roles) and ADR-0013 (library-first phases).
Direct answers first, profiles after.

The one rule everything else follows from:

> **Every phase is a plain library + CLI first; substrates only wrap.**
> `render → plan → decide → dispatch` runs identically under a laptop
> terminal, a CI job, a systemd unit, or a Prefect flow (ADR-0013 §2). The
> substrate choices below change durability, scheduling and placement —
> never semantics. That is what makes them choices instead of rewrites.

## The direct answers

### Prefect, GitLab CI, or a service?

All three appear — in different roles. The boundary rule:

> **CI gates documents. The orchestrator changes the network.**

| Concern | Substrate | Why |
|---|---|---|
| May this *intent* merge? | Infrahub proposed-change checks | Intent gates live with the intent (ADR-0001) |
| May this *plan* merge? | Git CI (GitHub Actions / GitLab CI) on the plan PR: schema-validate, policy-validate, simulation gate | Stateless verdicts over documents — exactly what CI runners are for |
| Execute the rollout | **Orchestrator** (today: `ibn-orchestrate` as a long-running process; target: the same functions as Prefect flows) | Soak timers, change windows, human pauses, resume-after-restart, per-stage gates — durable workflow state that CI executors do not have |

Why the rollout does **not** belong in a CI job, even though the CLI would
run there: CI runners are ephemeral (a 60-minute soak against a job timeout
is a coin flip), rerun semantics are wrong (re-running a failed *deploy* job
must not blindly re-apply), device credentials on shared runners widen the
blast radius of a CI compromise, and "waiting for Tuesday's window" is not a
thing a pipeline does well. A **CI-runner profile** is still explicitly
supported for small shops (see Profile 1's variant) — with those caveats
accepted consciously, not discovered in an incident.

Prefect specifically (vs. Temporal/Airflow/hand-rolled): decided in
ADR-0005 for durable timers, retries and human-in-the-loop pauses; the
library-first rule keeps the exit cheap if that decision ages badly. The
Prefect server is already provisioned in `infra/terraform`
(`helm_release "prefect-server"`); `orchestrator/flows/` is the reserved
landing zone.

"As a service": yes — the orchestrator is the service. It is the only
long-running platform process: the webhook receiver + reconcile loop
(`watch`) + flow runner. The **planner and validator stay libraries inside
it** (pure functions over documents — nothing to daemonize); the plan
approval surface stays Git until plan volume forces the Plan API + approval
UI (`scaling-and-productization.md`).

### Should the executor be located separately?

**Not by default.** ADR-0009 is deliberate: two packages, one process, and a
pre-designed promotion to a standalone **device gateway** service. Promote
when any of these is true — and not before:

1. **Reachability/segmentation**: devices are only reachable from specific
   management networks or via jump hosts. Then run executor *workers* inside
   each management domain; the orchestrator stays in the platform cluster
   and never needs a route to a router.
2. **Credential isolation**: device credentials must not exist where flows
   run (multi-tenant, customer-run workers). The gateway owns credentials;
   the orchestrator holds none.
3. **Global coordination**: per-device session limits / rate limiting across
   *concurrent* plans — a library cannot enforce a process-wide invariant
   from two processes.
4. **Audited chokepoint**: compliance wants every device write through one
   throat.
5. A **non-Python caller** needs device operations.

Placement rule when promoted: **one executor per management domain** (site,
region, tenant — whatever bounds reachability and credentials), addressed by
the plan's control points. The verb contract (`get_facts / snapshot /
dry_run / apply / confirm / rollback`, serializable pydantic in/out) was
designed as-if-remote from day one, so promotion is a transport addition
(gRPC/REST), not a redesign.

### How is it triggered?

ADR-0004, unchanged and load-bearing: **webhooks trigger; reconciliation
guarantees.** Every trigger row has a poll-loop twin, so a missed event
costs one interval, never a lost deployment.

| Event | Fast path (webhook) | Guarantee (reconcile) | Today |
|---|---|---|---|
| Proposed change opened | Infrahub webhook → plan (reviewable pre-merge) | `watch` polls `CoreProposedChange` | Poll only |
| Proposed change / plan PR merged | Infrahub or Git webhook → dispatch | `watch`: merged + not dispatched → dispatch | Poll only |
| Window opens for a `waiting` plan | (none — time is not an event) | `watch` retries exit-3 plans every pass; target: Prefect scheduled resume | Poll |
| Plan needs approval | approval given → re-dispatch | `watch` approval-hold until a manual `dispatch --approve` outcome | Implemented |
| Nightly verification / drift sweep | — | Prefect schedule (target); cron + CLI (today) | CLI |
| Break-glass | human runs `ibnctl` / `dispatch --emergency` | drift shows up in the validator by design | Implemented |

Payloads carry **references only** (branch, plan id, checksums) — that is
what makes the webhook→broker swap later a transport change, not a contract
change.

### Should there be a queue?

There already are three queue-shaped things. Use them in this order and
resist building a fourth:

1. **The `plans/` directory is the durable work queue.** A plan bundle +
   its `decision.yaml` + `report.yaml`/watch-state *is* a pending-work
   record with states (scheduled / waiting / approval-hold / dispatched) —
   inspectable with `ls`, replayable, survives every restart. At lab and
   single-team scale this is the whole answer.
2. **Prefect work pools are the concurrency layer** when flows land: one
   pool per management domain gives routing (site-local executor workers
   pull only their site's work) and bounded concurrency per pool. Do not
   build a second queue next to the one the orchestrator ships with.
3. **A broker (NATS/Kafka) only on ADR-0004's revisit triggers**: >1
   consumer per event, replay/event-history requirements, or a streaming
   bus already exists for telemetry (then reuse it).

Two things a queue must **not** do here: reorder approvals (approval is a
property of the plan document, not of queue position) and provide the rate
limiting (admission control is planner policy — `rate_limits.yaml`, change
class `max_plans_per_hour` — evaluated against the plan record, so the
limits hold no matter which substrate feeds work in).

## Deployment profiles

### Profile 1 — Lab / single operator (exists today)

```
one host: docker compose (Infrahub + Prefect server) + containerlab fabric
process:  ibn-orchestrate watch          # reconcile loop: plan on open, dispatch on merge
          IBN_SOT_REPO / IBN_PLANS_DIR / IBN_POLICIES_DIR set once
storage:  plans/ in the Git repo; policies in planner/policies/
executor: in-process (mock, srlinux, eos drivers)
queue:    none — watch serializes; plans/ is the record
```

Variant — **CI-runner mode** (no long-running process at all): CI on the
plan PR runs `ibn-orchestrate dispatch --plan-dir ... --wait` on merge.
Acceptable when soaks are short, runners are trusted with device
credentials, and someone owns the "job timed out mid-soak" runbook.

### Profile 2 — Team / production, single tenant

```
kubernetes (infra/helm + kustomize; terraform ibn-platform module):
  infrahub            tier-0, backup/restore runbook required
  prefect-server      provisioned already (terraform)
  orchestrator        deployment: webhook receiver + watch (reconcile) + Prefect flows
  prefect worker(s)   run flow tasks; executor library in-process
triggers:  Infrahub/Git webhooks → Prefect API; watch stays as the guarantee
plans:     Git PRs under plans/ (ADR-0003) — CI gates the documents
queue:     Prefect work pools; concurrency limits per pool
secrets:   device credentials + tokens via the secrets backend (design pending)
```

### Profile 3 — Scaled / multi-domain / product

Added on explicit triggers, each pre-named:

- **Executor → device gateway** per management domain (ADR-0009 level 3
  triggers above); flows swap an import for a client.
- **Broker** for control events (ADR-0004 revisit); telemetry bus reused if
  one exists.
- **Plan API + approval UI** replacing plan PRs; RBAC replacing CODEOWNERS;
  storage moves to DB/Infrahub with the Plan contract unchanged
  (`scaling-and-productization.md`).
- **Per-tenant stacks** via the Terraform project factory; policy packs
  versioned per tenant.

## What runs where (summary)

| Component | Shape | Placement |
|---|---|---|
| Infrahub | tier-0 service | platform cluster (or SaaS) |
| Planner | library | inside the orchestrator process/flows |
| Orchestrator | **the** service: webhooks + reconcile + flows | platform cluster |
| Executor | library → device gateway on promotion triggers | with the orchestrator → one per management domain |
| Validator | library (gates) + scheduled evaluation | in-flow + scheduled flows |
| Telemetry | collectors + pipelines | near the network; its own scaling axis |
| CI (GitHub/GitLab) | document gates | wherever the Git host runs |
