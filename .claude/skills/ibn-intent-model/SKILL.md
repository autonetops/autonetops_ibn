---
name: ibn-intent-model
description: The AutoNetOps IBN intent model (ADR-0015/0017) — an intent is achieved by contracts, governed by policies, guaranteed by invariants, tempered by waivers — with its naming conventions, placement rules, typing rules and use-case patterns. Use this skill whenever work touches intent, even if the word "intent" is never said - modeling a new service or network use-case ("how do we model X?"), naming or creating an intent, contract, objective, policy, invariant, waiver, tenant, zone or capability; adding a typed contract or invariant kind; writing or reviewing a check, transform, query, generator, expectation, verification or playbook; deciding "where does this rule belong?" (SoT vs policy pack vs template vs code); or judging whether the model covers a use-case or needs a new concept.
---

# IBN intent model: vocabulary, placement, naming

## Sources of truth (read before changing anything they cover)

| What | Where |
|---|---|
| The decisions | `autonetops_ibn/docs/adr/0015-intent-vocabulary.md`, `0017-vocabulary-alignment-lab-ontology.md` (both *proposed*: argue there, not in a schema) |
| The full model | `autonetops_ibn/docs/architecture/intent-model.md` |
| Platform generics + field guide | `autonetops_ibn/infrahub/schemas/intent_model.yml`, `infrahub/schemas/README.md` |
| Lab schema (generics mirror + typed kinds) | `autonetops_infrahub/schemas/intent.yml`, `schemas/operations.yml` |
| Every convention in use | `autonetops_infrahub/scripts/bootstrap.py` |
| Operational policy surfaces | `docs/adr/0016-intent-profile-packs.md`, `planner/policies/` |

If this skill and those files disagree, they win; fix the skill. The vocabulary is versioned:
changing a definition means an ADR that supersedes 0015, because external adopters build on
these words.

**Retired vocabulary.** Before July 2026 the lab used a different hierarchy. You will still
meet it in old plans, `schemas/migrations/` and older notes. Translate, never reintroduce:

| Retired | Now |
|---|---|
| `IntentRealm` node kind | `domain` attribute on the intent (`reliability → resilience`, `performance → capacity`, `reachability` is not a domain) |
| `IntentIntent`, `statement`, `suspended` | `IntentDefinition`, `description`; suspend with waivers / contract `status` |
| `IntentPolicy` as a bundle between intent and contracts | gone: contracts hang straight off the intent. "Policy" now means a standing rule |
| `Policy.enforcement: design_time \| runtime \| full` | derived from the instruments attached, never authored |
| `invariant_type` enum + `params` JSON | typed invariant kinds (`IntentNoLeakInvariant` → `no_leak`); parameters are typed attributes |
| invariant `severity: blocking \| warning` | `warning \| major \| critical`; blocking is derived (`major`/`critical` block the merge) |

## 1. The model

> An intent is **achieved by** its contracts, **governed by** policies, **guaranteed by**
> invariants, and **tempered by** waivers.

```
IntentDefinition          root: outcome + owner + priority + domain + tenant. Compiles to NOTHING.
  ├─ contracts   OWNED     IntentContract (generic). Typed kinds carry terms as attributes;
  │                        IntentGenericContract carries them as IntentObjective nodes.
  ├─ policies    REFERENCED IntentPolicy (generic): subject network | operational,
  │                        scope global | domain | intent. OpsChangeWindow inherits it.
  └─ invariants  REFERENCED IntentInvariant (generic): typed kind per condition,
                           severity warning | major | critical, scope global | domain | intent.
IntentWaiver              one target (policy XOR invariant) + one subject (intent | contract |
                          device scope) + requested_by + approved_by + hard expires_at.
Supporting                IntentTenant (WHO) · IntentZone (WHERE) · IntentCapability (WITH WHAT)
```

| Rule | Why it matters |
|---|---|
| A contract belongs to exactly one intent (Parent, cascade). An intent with zero contracts is a finding. | Without a contract nothing can fail, so the intent is unverifiable. |
| Policies and invariants are referenced, never owned. | One rule guards many intents and survives any of them being deleted. Look for an existing one before creating a copy. |
| `priority` lives only on the intent and flows down (intent → contract → plan). | Nothing below the intent may raise its own urgency. |
| `domain` is a free-form attribute, one value per intent. | The taxonomy grows without a schema migration. A typo silently detaches every `scope: domain` rule, so use the starter set in `intent-model.md`. |
| Compliance rolls up the other way: verdict → objective → contract → intent, worst-of; `waived` is its own state. | A waived finding is never green and never red. |

**Rules in force for an intent** = every enabled policy/invariant with `scope: global`, plus
`scope: domain` whose `domains` contains the intent's domain, plus those explicitly linked,
minus live waivers (compare `expires_at` to now; there is no stored active flag). Anything that
resolves instruments must compute all three scopes. Walking only `intent → invariants` sees
just the explicit links (today's checks do this; see Known gaps).

## 2. Classify before you create

One question per instrument. Ask them in this order:

| Question | Answer | Fails as |
|---|---|---|
| Who loses if this breaks? (a nameable consumer) | **Contract** | a broken promise |
| Which designs or actions does this forbid or shape? | **Policy** | a rejected change |
| If false, is it an incident regardless of what changed? | **Invariant** | an incident |
| Is it a sanctioned, temporary violation of a policy or invariant? | **Waiver** | a finding again on expiry |

Tie-breaker for policy vs invariant: *can it become false without anyone changing the SoT?*
A link failing makes a redundancy floor false with no change at all, so that is an invariant.
"Every eBGP session declares max-prefix" can only become false through a change, so it is a
policy. The distinction decides the enforcement point: a policy refuses the action, an invariant
detects the state (and may *project* onto merge time: "would this change remove the second
uplink?").

If none fit, you are describing mechanism or a fact, not intent. Walk the placement ladder.

### Placement ladder (first match wins)

1. **An outcome a consumer or manager would recognize, in one sentence** → `IntentDefinition.description`. No device names, protocols or knobs.
2. **A measurable promise to a named consumer** → a contract. Use a typed kind when the terms must render config or expectations, else `IntentGenericContract` + objectives.
3. **A standing rule on how the network may be designed** → network policy: a kind inheriting `IntentPolicy` plus the merge check that enforces it. A policy with no check is a comment.
4. **A rule on the automation itself** → operational policy, on one of two surfaces (ADR-0016):
   - *when the network may change* → `OpsChangeWindow` in the SoT;
   - *what the engine reads to shape or gate a plan* (blast-radius thresholds, canary strategies, change classes, approval floors, delivery preferences, rate limits) → the policy pack (`IBN_POLICIES_DIR`, `planner/policies/`). Anything whose misconfiguration could remove a human from the loop stays in the pack under CODEOWNERS.
5. **A state condition that must always hold** → a typed invariant kind.
6. **Who / where / with what** → `IntentTenant`, `IntentZone`, `IntentCapability`. Controlled vocabularies: code branches on these values.
7. **A fact about what exists** (device, link, prefix, VRF, ASN, site) → DCIM/IPAM, not intent.
8. **A value that follows mechanically from intent + facts** (session endpoints, allocated addresses, RD/RT, descriptions) → derive it. Compute it in the transform at compile time (the lab derives BGP sessions from contract + cabling) or materialize it with a generator / resource pool. Never hand-author it and never put it in intent.
9. **Vendor syntax or a platform quirk** → the renderer for that platform (`render_<platform>` in the lab's `transforms/device_config.py`; `infrahub/templates/<vendor>/` on the platform). Gate on capability, not on vendor name.
10. **What must be observably true** → a compiled expectation. Never authored.
11. **An active probe** → `remediation/verifications/` with `derives_from`. Read-only.
12. **What to do on failure** → `remediation/playbooks/<safe_fixes|quarantines|escalations>/`. A safe fix proposes a plan; it never pushes.
13. **An incident worth never repeating** → `simulations/golden-topologies/<name>/` plus an expectation that fails while the bug exists.

### Slicing intents

One intent per outcome a consumer would recognize. A connectivity intent may own routing,
reachability, security and observability contracts together; contract kinds are not tied to the
intent's domain. Split into separate intents only when **owner, priority or lifecycle** differ
(secops owning the perimeter of a customer VPN is a real split; "it touches two domains" is
not). Two consequences from the ADRs:

- Reachability is an *objective kind* inside contracts, not a domain and not its own intent.
- Observability rides two patterns: per-service signals belong to the service's intent;
  only fleet baselines ("every production device streams telemetry, freshness ≤ 30s") get an
  intent in the `observability` domain.

## 3. What compiles into what, and where it bites

| Source | Compiles into | Enforced at |
|---|---|---|
| Contract (typed terms or objectives) | config artifacts per control point **and** a `ContractExpectations` artifact per contract | stage gates at dispatch; continuous evaluation |
| Observability contract / signals | collector inputs, alert rules, dashboards | continuous |
| Network policy | merge check | intent merge (Proposed Change) |
| Operational policy | windows, canary strategy, change class, approval bar, rate limits | plan compile, plan approval, dispatch |
| Invariant | merge *projection* (blocks when `major`/`critical`) + always-on expectations | intent merge; continuous |
| Waiver | nothing; it turns a finding into `waived` wherever its target bites | everywhere the target is, expiry checked first |
| Intent | nothing; lends `derives_from` root, priority, owner | n/a |

Three axes that look alike and must stay separate: **priority** (on the intent: how important
is the outcome), **severity** (on the invariant: what is a violation worth), **blast radius**
(computed on the plan, a ceiling on the window: how big is this change).

### Expectations are the proof

A config artifact without a sibling expectation only shows the change can be pushed. It doesn't
show the intent is met. When compiling expectations:

- **Ranges, never exact values**: `route_count <= 200`, not `== 173`.
- **State forbidden behavior explicitly**: a negative nobody wrote down can't be proven.
- **Derive the collector from platform capability** (`observedVia`), never choose it by hand.
- **Freshness is part of the proof**: stale or missing evidence is `unverifiable`, never `pass`.
- **Carry the trace**: `metadata` = `name`, `intent`, `domain`, `description`, `tenant`, `zone`,
  `derivesFrom: infrahub://Intent/<intent>/contract/<contract>`. A check that can't cite its
  intent gates nothing.

Observed-side words are fixed: evidence → evaluation (continuous) / verification (triggered) →
verdict (`pass | fail | pre_existing | unverifiable`) → drift → compliance.

## 4. Typing: make invalid states unrepresentable

Intent should read like a human declaration and behave like a validated API. A formatting
ambiguity in intent becomes a deployment issue, so remove the ambiguity in the schema:

- A closed vocabulary is a `Dropdown`. A reference to something that exists is a
  relationship to its SoT kind (device, prefix, zone, tenant), never a `Text` name.
- Units go in the attribute name (`_seconds`, `_pct`, `_mbps`). Bounded numbers and patterned
  strings (ASN, community, RD) get a range or `regex`.
- Scope things with a **selector built from controlled values** (role, zone, group membership),
  not an enumerated device list where avoidable, and never a free-text selector.
- No vendor keys (`junos:`, `iosxr:`) in intent. A platform difference is a capability in the
  SoT plus a renderer arm.
- Thresholds are typed attributes on the kind that owns them, never constants in a check or
  transform.
- What the schema can't express (xor relationships, "at least one contract") becomes a merge
  check, listed under "Constraints owed as checks" in `infrahub/schemas/README.md`.

A check must fail loudly when it is **vacuous** (empty scope makes it trivially true, e.g.
no-leak with no denied zones) or **unverifiable** (missing tenant or anchor). Silent pass is
the failure mode that erodes trust in every other green light.

## 5. Naming

Object names are lowercase kebab-case, unique per kind, stable (they become `derives_from`
URIs, alert labels and file names, so a rename is a migration). Enum values and capability
names are snake_case. Full rules: [references/naming.md](references/naming.md).

| Kind | Pattern | Examples |
|---|---|---|
| Intent | `<scope>-<outcome>` (WHAT, never how) | `custc-l3vpn-connectivity`, `provider-core-transport`, `fleet-management-plane` |
| Contract | `<scope>-<relationship or subject>` | `custc-ce-to-pe`, `ibgp-core-rr`, `custc-apps-reachable-from-emea-corp` |
| Objective | `<term>`, unique within its contract | `sessions-established` |
| Network policy | the rule itself: `<subject>-<requirement>` | `ebgp-max-prefix-required` |
| Change window | `<scope>-<cadence or purpose>[-freeze]` | `emea-standard-maintenance`, `q3-core-audit-freeze` |
| Invariant | shared: `<subject>-<property>`; intent-scoped: `<scope>-<type-kebab>` | `fleet-oob-cabled`, `custc-no-leak` |
| Waiver | `<subject>-<what is violated>` | `cust-c-site3-single-homed` |
| Typed kinds | `Intent<Thing>Contract`, `Intent<Condition>Invariant`, `Intent<Thing>Policy`; `Ops*` for operational kinds | `IntentRoutingContract`, `IntentNoLeakInvariant`, `OpsChangeWindow` |

Scope prefix: tenant abbreviation (`custc`), `provider`, `fleet`, or a topology scope (`core`,
`inet`, `emea`). An intent and the contracts it owns share one prefix so `grep custc` returns
the tree. Shared policies and invariants are named for the rule, not for one tenant.

## 6. Overloaded words: always qualify them

| Word | Meanings here | Say |
|---|---|---|
| **policy** | `IntentPolicy` (network / operational); policy pack files; route policy (route-maps); security rules | "network policy", "operational policy", "policy pack", "route policy" |
| **contract** | `IntentContract`; cross-layer data contract in `contracts/` (Plan v1, profile v1); driver verb contract | "intent contract", "data contract", "verb contract" |
| **rule** | reserved for compiled check definitions in `validator/rules/`; also `IntentSecurityRule` | never use "rule" for authored policy or invariant |
| **invariant** | the authored object; its merge projection; its always-on expectation | name the surface: "the `custc-no-leak` merge projection" |
| **gate** | merge gate (check); stage gate (expectations at dispatch); dispatch gate (window, approval) | the qualified form |
| **domain** | intent domain tag; controller domain (executor `atomicity: domain`); failure domain | "intent domain", "controller domain", "failure domain" |
| **profile** | intent profile = policy pack (ADR-0016); Infrahub node profiles (`generate_profile`); `ddos_profile` | "policy pack", "Infrahub profile" |
| **role** | device role, interface role, routing-contract role, `attach_device_role`: four separate enums | name which one; see Known gaps |
| **severity** | invariant severity (`warning\|major\|critical`); signal paging scale (`sev1..sev4`, compiler output) | "invariant severity", "paging scale" |
| **scope** | policy/invariant `scope`; waiver `subject_scope`; naming scope prefix | the qualified form |

## 7. Modeling a use-case, extending the model

- **"How do we model X?" / "does the model cover X?"** → look X up in
  [references/use-case-patterns.md](references/use-case-patterns.md) before inventing a kind.
  Most needs are a new *typed kind* under an existing generic. A new *concept* needs an ADR.
- **Step-by-step changes** (new intent, typed contract kind, typed invariant kind, network
  policy, operational policy, waiver, domain) →
  [references/extension-checklists.md](references/extension-checklists.md).

Prefer the narrowest change: new data over a new attribute, a new attribute over a new kind,
a new kind over a new concept.

## 8. Review red flags

- Intent named after a mechanism or vendor (`custc-bgp-config`, `eos-acl`), or with zero contracts.
- Intents split per domain for one outcome with the same owner and priority.
- A per-tenant copy of an invariant or policy that could be one `scope: domain` rule.
- A network policy with no merge check; an invariant with neither projection nor expectation.
- Config artifact without a sibling expectation; artifact or verdict without the trace metadata.
- `Text` where a relationship or `Dropdown` fits; thresholds hardcoded in a check or transform.
- Vendor conditionals in intent logic; a mechanism knob stored as a SoT fact and edited by hand.
- Priority anywhere but the intent; windows, canary or approval rules as code or CLI flags.
- `enabled: false` or an un-expiring exception where a scoped waiver belongs; a waiver aimed at a contract; `requested_by == approved_by`.
- Missing or stale evidence counted as pass.
- "Rule", "SLA", "realm", "exception" used for authored intent.

## Known gaps (verify before relying on them)

Checked 2026-11-18. Each is a place where the code is behind the model, so don't copy the
existing pattern as if it were the convention.

- `orchestrator/.../priority.py` walks `IntentRoutingContract` only, so a plan touching only
  devices of another contract kind inherits no intent priority and falls back to `medium`.
- Lab checks resolve invariants through explicit `intent → invariants` links only;
  `scope: global | domain` instruments are not picked up.
- Waivers and objectives exist in the schema only: no check honors a waiver, nothing compiles
  an objective. The "constraints owed as checks" list is still owed.
- Only routing contracts compile expectations. Reachability and reliability contracts compile
  nothing; security contracts compile config with no expectation. The validator evaluates BGP
  session state only (prefix limits, communities, forbidden exports and freshness are emitted
  and ignored).
- Five of eight typed invariants have no merge projection (redundancy, OOB reachability,
  reachability preserved, no default origination, no re-origination). Typed invariant kinds
  carry no attributes yet.
- `ebgp-max-prefix-required` (the one network policy) has no check.
- `IntentPolicy` and `IntentInvariant` have no `owner`, and every owner field is free text, so
  "approved by the target's owner" can't be enforced.
- Role vocabularies diverge (device role `edge|core|cpe` vs `attach_device_role: pe|core|ce`;
  the renderer translates `edge → pe` in code and `ce` matches nothing).
- `derives_from` for invariant- or policy-derived expectations is undefined (the URI roots at
  an intent, but shared rules have none). Older docs show `infrahub://RoutingContract/<name>`;
  the decided form is `infrahub://Intent/<intent>/contract/<contract>`.
- Free-form expressions (`Objective.expression`, `Invariant.expression`, signal `condition`,
  waiver `subject_scope`) have no grammar yet.
