# Extension checklists

Paths: `IH` = `autonetops_infrahub/`, `IBN` = `autonetops_ibn/`.

Everything is authored on a branch and merged through a Proposed Change, by people and agents
alike. Pick the narrowest change that does the job: data before attributes, attributes before
kinds, kinds before concepts.

Contents: A. new intent (data) · B. typed contract kind · C. typed invariant kind ·
D. network policy · E. operational policy · F. waiver · G. domain · H. new concept

## A. New intent (data only, no schema change)

1. **Outcome first.** Write the `description` as one sentence a consumer could verify. If you
   can't, you are describing mechanism; stop and walk the placement ladder in `SKILL.md`.
2. **Reuse or split.** Does an existing intent already name this outcome for the same owner
   and priority? Then add contracts to it. Create a new intent only for a different outcome,
   owner, priority or lifecycle.
3. **Root fields**: `name` (per `naming.md`), `domain` (one value from the starter set),
   `owner`, `priority`, `tenant` (required for anything tenant-relative such as no-leak or
   prefix authorization), `ticket`. Use `critical` priority sparingly because it gates
   emergency eligibility.
4. **At least one contract**, with a `consumer`. Typed kind when the terms render config or
   expectations; `IntentGenericContract` + `IntentObjective` nodes otherwise. Anchor contracts
   to SoT objects (devices, prefixes, zones), never to names typed as text.
5. **Rules in force.** Query `IntentPolicy` and `IntentInvariant` first: which global and
   domain-scoped ones already apply? Link intent-scoped ones explicitly. Create a new
   invariant only if no existing one states the condition.
6. **Groups.** Add contracts to the target groups the lab's `.infrahub.yml` consumers read
   (`routing_contracts`, `observability_contracts`, `intent_tenants`, …). Without group
   membership no check or artifact runs for them, and nothing warns you.
7. Branch → Proposed Change → checks pass → artifacts render (config **and** expectations) →
   plan (`ibn-orchestrate plan`) → review the plan.

## B. New typed contract kind

1. Confirm no existing kind fits with an extra attribute. ADR first if the kind introduces a
   new artifact class.
2. Schema: `inherit_from: [IntentContract, CoreArtifactTarget]`. Don't redeclare what the
   generic gives you (`name`, `description`, `consumer`, `status`, `intent`, `objectives`).
   Description ≤ 128 characters (server cap). `include_in_menu: false`; the generic's menu
   entry lists every subtype.
3. **Type the terms** (section 4 of `SKILL.md`): relationships to SoT kinds, `Dropdown` for
   closed sets, units in names, `regex`/ranges for patterned values. Hysteresis pairs
   (`threshold_pct` / `clear_pct`) and rate limits belong on the contract, not in loop code.
4. Prefer selectors built from controlled values (role, zone, group) over enumerated device
   lists where the platform can resolve them. Keep role-neutral attribute names so the kind
   survives its second use-case.
5. Fields written by automation rather than people must be written through a branch, and the
   description must say so.
6. **Both compilers**: a vendor-neutral transform feeding per-platform renderers, **and** an
   expectation transform with the full trace metadata. Apply the expectation discipline
   (ranges, explicit forbidden behavior, capability-derived collector, freshness).
7. Target group + `artifact_definitions` in `IH/.infrahub.yml`.
8. Evaluation: extend `IBN/validator` (`ExpectationSet` parsing + rules). An expectation
   field the validator ignores proves nothing, so land emit and evaluate together.
9. Priority inheritance: extend `IBN/orchestrator/.../priority.py` so plans touching this
   kind's devices inherit the intent's priority (it walks routing contracts only today).
10. Signals that `watch` it, where it should page.
11. Golden tests: intent → rendered output per platform. Golden diffs are acknowledged in
    review, never regenerated blindly.

## C. New typed invariant kind

1. Confirm it is an invariant: false = incident regardless of what changed, and it can become
   false without an SoT change. A pure design rule is a network policy (D).
2. Schema: a node `Intent<Condition>Invariant` with `inherit_from: [IntentInvariant]`,
   `generate_profile: false`. Description phrased "X must / never Y". Give it the typed
   attributes that parameterize the condition (which zones, which floor, which capability),
   so one authored value tunes every surface.
3. Decide `severity`: `critical` (projection blocks, live violation pages), `major`
   (projection blocks), `warning` (reports only).
4. Decide `scope`. Prefer `global` or `domain` over one copy per tenant; per-subject
   differences are what waivers and typed attributes are for.
5. **Merge projection**: `IH/queries/<snake>.gql` + `IH/checks/invariant_<type>.py`
   (`<Camel>Check(InfrahubCheck)`):
   - resolve applicability across all three scopes (global, domain, linked), not just
     `intent → invariants`;
   - honor live waivers (expiry compared to now) and report them as `waived`;
   - `log_error` when unverifiable (missing tenant/anchor) and when vacuous (empty scope);
   - message format: `Invariant violated (<type>): <who> <what> <where>`.
6. **Runtime surface**: always-on expectations derived from the invariant (forbidden exports
   absent, floor held), evaluated by the validator; alert rule where it should page.
7. Active verification in `IBN/remediation/verifications/invariants/<domain>-<type>.yaml`
   with `derives_from`, and a remediation class on failure
   (`safe_fix | quarantine | escalate`) with its playbook.
8. Tests: a check unit test, and a `IBN/simulations/` scenario that fails while the
   violation exists.

## D. New network policy

1. Confirm it is a policy: it forbids or shapes a design, and a violation is a rejected
   change with nothing broken yet.
2. Start with `IntentGenericPolicy` (`subject: network`, `scope`, `domains`, `enforcement`).
   Promote to a typed kind inheriting `IntentPolicy` when the rule needs parameters.
3. Write the `description` so a reviewer could apply it without asking.
4. **Land the check in the same change**: `IH/checks/policy_<rule>.py`, registered in
   `.infrahub.yml`. Same loud-failure rules as invariant checks (vacuous, unverifiable,
   waiver-aware).
5. `scope: domain` needs a non-empty `domains`; `scope: intent` needs at least one link. A
   scope that matches nothing is a vacuous rule.

## E. Operational policy

Dividing rule (ADR-0016): if the engine reads it to shape or gate a plan, it is pack data;
if it says when the network may change, it is SoT data.

- **Change windows and freezes** → `OpsChangeWindow` in the SoT (`IH/schemas/operations.yml`),
  `subject: operational`. Recurring (days + `start_utc` + `duration_minutes`) or absolute
  (`starts_at` / `ends_at`). Empty device scope means every device.
- **Blast-radius thresholds, canary strategies, change classes, approval floors, delivery
  preferences, rate limits, platform → driver bindings** → the policy pack
  (`IBN_POLICIES_DIR`; reference pack in `IBN/planner/policies/`, baseline in
  `planner/src/autonetops_planner/packs/baseline/`). Validate with `validate-pack`.
- A new change class ships a `.match.yaml` **and** a `.refuse.yaml` golden fixture, or it is
  invalid.
- The profile parameterizes the engine's decision points; it never adds one. A need no pack
  section can express is an engine ADR.
- Never as code constants, and never as CLI flags that silently override reviewed data.

## F. Waiver

1. Target a **rule** (`waived_policy` xor `waived_invariant`), never a contract.
2. Subject: `subject_intent`, or `subject_contract` (optionally narrowed by `subject_scope`),
   or `subject_scope` alone.
3. `reason` says why it is sanctioned and what removes the need for it.
4. `requested_by` = the subject's owner; `approved_by` = the target's owner; they differ.
5. `expires_at` you can defend in review. Renewal is a new reviewed waiver.
6. Prefer a waiver over `enabled: false`: disabling is fleet-wide and lasts until someone
   remembers.

## G. New domain

Set `domain: "<value>"` on the intent; no schema change. Check that the value isn't a synonym
of an existing one (`reliability` vs `resilience`), that it names a concern and not a
mechanism (`collection` is a mechanism), and add it to the starter table in
`IBN/docs/architecture/intent-model.md` so `scope: domain` rules can target it.

## H. New concept (rare)

A new word in the vocabulary (a fifth instrument, a new derived or observed term, a new
enforcement point) is an ADR superseding or extending 0015, plus updates to
`intent-model.md`, the schema README and this skill in the same change. Check
[use-case-patterns.md](use-case-patterns.md) first: its "concept gaps" list records the
candidates already identified, so extend that discussion instead of starting a parallel one.
