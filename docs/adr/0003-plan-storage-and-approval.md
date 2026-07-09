# 0003 — Plan document storage and approval workflow

- Status: accepted
- Date: 2026-07-09

## Context

The planner's output is a declarative **Plan** (contract §3). Nothing executes
without one, so where plans live and how they get approved *is* the change
management process. Three candidate homes were compared.

## Options

**A. Git PRs** — the planner commits the plan as a file under `plans/` and
opens a PR; approval = PR review; merge = execution trigger.

**B. Infrahub objects** — a `Plan` node kind in the schema; the planner writes
it via the API; approval = status transition or a proposed change.

**C. Planner database** — the planner service owns Postgres + an approval
API/UI.

## Comparison matrix

| Criterion | A: Git PR (`plans/`) | B: Infrahub object | C: Planner DB |
|---|---|---|---|
| Audit trail | ✅ Immutable git history, signed commits | ✅ Versioned graph | ⚠️ Only as good as we build it |
| Blast-radius-based approval enforcement | ✅ CODEOWNERS + branch protection + required checks — mature, battle-tested | ⚠️ Review exists (proposed changes) but per-object approval rules are coarse | ❌ Must be built from scratch |
| New infrastructure required | ✅ None | ✅ None (Infrahub exists) | ❌ Service + DB + UI |
| Review UX | ✅ Diff review, comments, familiar to everyone | ⚠️ Good for data, weaker for "read this rollout plan" | ⚠️ Custom UI |
| Machine consumption (deployer/Prefect) | ✅ Webhook on merge → checkout file | ✅ GraphQL | ✅ API |
| Immutability after approval | ✅ Merge commit is frozen | ⚠️ Mutable unless explicitly designed | ⚠️ Mutable unless explicitly designed |
| Single pane of glass | ⚠️ Second surface next to Infrahub | ✅ Everything in Infrahub | ❌ Third surface |
| High change volume (many plans/day) | ⚠️ PR noise, review fatigue | ✅ Scales as data | ✅ Scales as data |
| Emergency-path latency | ⚠️ PR mechanics overhead | ✅ Status flip | ✅ Status flip |

## Decision

**Option A now: plans are Git PRs under `plans/`.** Revisit B when plan volume
makes PR review fatiguing (explicit trigger: sustained >~10 plans/day, or when
auto-approved low-blast-radius plans dominate).

The apparent duplication with Infrahub proposed changes is not duplication:
they answer different questions. The Infrahub proposed change approves the
**intent** ("is this what we want?"). The plan PR approves the **rollout**
("is this safe to do, this way, now?"). Separating them is a feature — the
person who approves a routing contract is not necessarily the person who
approves touching 40 PEs on a Friday.

## Consequences

- `plans/` exists in this repo; CODEOWNERS maps it to rollout approvers, and
  the planner annotates each PR with blast radius so approval bars can be
  raised by path/label.
- Plan files are immutable post-merge; a changed rollout = a new plan PR that
  supersedes the old one.
- Merge of a plan PR is the execution trigger (webhook → Prefect flow,
  see ADR-0004/0005).
- Emergency path must be defined in `docs/runbooks/emergency-changes.md`
  before production go-live (pre-approved break-glass plan template).
