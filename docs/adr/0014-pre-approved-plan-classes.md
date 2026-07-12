# 0014 — Pre-approved plan classes: auto-approval as reviewed policy

- Status: accepted
- Date: 2026-07-12

## Context

ADR-0003 separates intent approval (Infrahub proposed change) from rollout
approval (plan review), and the ADR backlog (`docs/adr/README.md`) owes
"auto-approve rules for low blast radius" under Plan-PR automation. Today the *only* input to the approval bar is blast-radius
class: low/moderate plans select a builtin canary strategy with no required
approvals, and `watch --auto-dispatch` (default on) executes them on PC merge
with zero human plan review. That is already auto-approval — unnamed, and
blunt: the planner diffs artifacts by checksum only
(`planner/src/autonetops_planner/diffing.py`), so it cannot distinguish an
interface-description edit from a BGP policy rewrite touching the same three
devices. Both are "moderate". Meanwhile genuinely routine changes
(descriptions, cosmetic metadata) deserve to flow unattended, and remediation
`safe_fixes` are documented as "pre-approved actions" that must propose a
Plan — which today would still queue behind whatever bar the blast radius
sets.

The question is not *whether* some plans skip human review — they already do —
but how to make that skip **named, content-aware, reviewed, and recorded**.

## Options

**A. Classify in the planner, on artifact content** — fetch the changed
artifacts' bytes at plan time, diff them, match the diff against reviewed
change-class definitions.

**B. Label in Infrahub** — an intent-side check classifies the proposed
change (e.g. "only `description` attributes changed") and the plan inherits
the label.

**C. Keep blast radius as the only key** — tune thresholds and strategy
approvals; no content awareness.

B classifies the *intent* diff, but rollout approval is about the *rendered
outcome* — a template bug can turn an innocent intent edit into a config
rewrite, and only the artifact diff shows that. C is the status quo that
cannot express "descriptions are safe at any fan-out, BGP is not at any".
A classifies exactly what will be pushed, in the component that owns rollout
safety. Intent-side checks (B) remain valuable as *intent* gates and can
cheaply pre-label candidates, but the authoritative classification is A.

## Decision

1. **Change classes are reviewed policy data**:
   `planner/policies/change_classes.yaml`, owned via CODEOWNERS by rollout
   approvers, versioned in Git like every other policy. Pre-approval moves
   the review earlier — onto the class definition — it does not remove
   review. Every auto-approved plan cites the class name and the policy
   version (commit) that authorized it.

2. **The planner grows a content-aware classifier**
   (`autonetops_planner.change_classes`), a new compile stage between diff
   and strategy selection; the orchestrator supplies the before/after bytes
   per changed (target, definition) — `fetch_content` already exists on all
   three artifact sources and the candidate bytes are already frozen into
   `content/` at plan time; what is new is a *decision* reading them. The
   diff is matched against class matchers, per `content_format`:
   - `cli-text`: regex allowlists over added/removed lines of the unified
     diff (renderer context noise accounted for);
   - `openconfig-json` / `ietf-xml`: **model-path allowlists** (e.g.
     `/interfaces/interface[*]/config/description`) — structurally robust.
   CLI-text matching is the weak form; model-path matching is the durable
   one. This is a second, concrete payoff of the move to model-based
   artifacts anticipated by ADR-0012 (its preference order already rewards
   model-based payloads with NETCONF/gNMI delivery; the compilers that emit
   them are still future work): it raises the ceiling of what can be safely
   pre-approved.

3. **Eligibility is fail-closed.** A plan is pre-approved iff *all* hold:
   - every changed target's diff matches, **entirely**, the matchers of one
     class (one unmatched hunk anywhere → normal approval path);
   - `removed_targets` is empty;
   - blast radius ≤ the class's `max_blast_radius` ceiling;
   - no emergency override in play;
   - the class is `enabled` and its rate limit is not exhausted.
   Unclassifiable, mixed, or over-ceiling changes fall through to the normal
   path silently costing nothing — the classifier can only ever *remove* a
   human step, never add risk.

4. **The classification is recorded, never implicit**:
   - `plan.yaml`: `policy_evaluation.pre_approved` = `{class, policy_version}`
     (a pydantic field + schema regen; plan identity is unaffected because
     `deterministic_id` hashes only `source + stages`);
   - `decision.yaml`: `approvals_required: []` with a reason
     `pre-approved by change class 'interface-descriptions' @ <commit>`;
   - the SoT `OpsPlanRecord` gains a `pre_approved_class` attribute, so
     "what flowed unattended, under which policy" is queryable next to the
     intent.

5. **Enforcement points**:
   - `strategy.decide()` consults the classification when computing
     `approvals_required` — the single existing choke point for the decision;
   - dispatch exits with a dedicated code (4) on missing approvals, and
     `watch` treats it as non-terminal: the plan goes on **approval hold**
     (announced once, no dispatch hammering) until a manual
     `dispatch --approve ...` leaves a real outcome behind — this
     simultaneously fixes watch dead-ending `needs_approval` plans;
   - **dispatch re-derives the class from the frozen bundle** before
     honoring an empty approvals list: pre-approved plans freeze the base
     bytes too (`content_base/`, integrity-anchored by the steps'
     `checksum_before`), so the claim is re-proven from bytes alone under
     the *current* policy — which also makes the kill switch effective for
     already-planned bundles. `decision.yaml` has no integrity protection;
     re-derivation makes tampering pointless — the recorded decision may
     only ever be *tightened* at dispatch time, never loosened, and a claim
     that cannot be checked (unknown strategy, missing bytes) is refused
     via an un-satisfiable `unverifiable-pre-approval` requirement.

6. **Pre-approval removes exactly one thing: the human plan-review step.**
   Change windows, per-stage validator gates, baseline/soak/unverifiable
   semantics, evidence, `report.yaml` and the `OpsPlanRecord` upsert all
   apply unchanged. A class *may* name its own canary strategy (e.g. a
   no-soak single stage for descriptions) — but only via its own reviewed
   definition, resolved by name (`strategy_by_name`) and failing loudly at
   plan time when the named strategy does not exist.

7. **Guardrails**: a per-class rate limit (`max_plans_per_hour`, counted
   statelessly from the plan bundles on disk) and a per-class kill switch
   (`enabled: false` — one reviewed line to halt a class fleet-wide, effective
   even for already-planned bundles via dispatch re-derivation). Every class
   definition must land with golden tests pinning a diff it matches *and*
   diffs it must refuse (a description change bundled with an MTU change must
   not match) — see `planner/tests/test_change_classes.py`.

Sketch of the policy shape:

```yaml
# planner/policies/change_classes.yaml
version: 1
classes:
  - name: interface-descriptions
    enabled: true
    description: Only interface description leaves change; nothing else.
    applies_to:
      artifact_definitions: [device-configuration]
    match:
      cli-text:
        changed_lines_allow:
          - '^\s*interface \S+$'          # section context re-emitted by renderers
          - '^\s*description .+$'
      openconfig-json:
        paths_allow:
          - /interfaces/interface[*]/config/description
    max_blast_radius: high                # safe at any fan-out — rate limit still applies
    # canary_strategy: <name>             # optional; must exist in canary_strategies.yaml
    rate_limit:
      max_plans_per_hour: 10
```

`safe_fixes` remediation playbooks compose with this for free: a safe fix
proposes a Plan through the planner (it never pushes directly, per
`remediation/playbooks/README.md`); when that plan's diff matches a
pre-approved class, the drift → remediation loop closes unattended — without
weakening any rule.

## Consequences

- Plan compilation **consumes** artifact bytes for the first time — bytes
  are already rendered and frozen into the bundle's `content/` at plan time,
  but diffing and every compiled decision see only checksums today;
  classification cost is bounded to changed targets.
- `PolicyEvaluation` gains a field; `contracts/plan/v1/plan.schema.json` is
  regenerated (`autonetops-planner export-schema`) — an additive, non-breaking
  v1 change.
- A class-named canary strategy is resolved via `strategy_by_name`;
  `decide()`, `watch`, and dispatch change as in §5 — including the new
  dispatch exit code 4 (missing approvals) so `needs_approval` is
  non-terminal under automation. `--policies-dir` is plumbed through
  `dispatch` and `watch` (default: `IBN_POLICIES_DIR` — plan-time
  classification and dispatch-time re-verification must read the same
  reviewed data, or every claim fails its re-check), which also lets custom
  strategies apply in the automated path for the first time.
- Pre-approved bundles grow a `content_base/` directory (frozen base bytes,
  anchored by the steps' `checksum_before`) so dispatch re-derivation needs
  nothing but the bundle and the current policy.
- The `policy-validate` CI slot (`.github/workflows/ci.yaml` header) is
  seeded by `test_shipped_policy_file_loads_and_pins_the_descriptions_class`:
  the committed YAML must parse, compile, and hold its match/refuse boundary;
  per-class golden match/refuse tests are mandatory.
- The emergency break-glass template (owed by ADR-0003 in
  `docs/runbooks/emergency-changes.md`) is a *different* mechanism — an
  override with a name on it, not a class — and stays separate.
- Once pre-approved classes dominate plan volume, ADR-0003's revisit trigger
  (PR review fatigue) arrives sooner: Option B (plans as Infrahub objects)
  becomes the storage answer, and classes port unchanged because they are
  policy data, not storage.
- The ADR backlog item shrinks to "Plan-PR automation details (bot
  identity)"; auto-approve rules are decided here.
