---
name: ibn-intent-model
description: The AutoNetOps IBN intent model (ADR-0015/0017) — an intent is achieved by contracts, governed by policies, guaranteed by invariants, tempered by waivers — with its primitives, naming conventions, placement rules, typing rules and use-case patterns. Use this skill whenever work touches intent, even if the word "intent" is never said - turning a request into an intent tree; modeling a new service or network use-case ("how do we model X?"); naming or creating an intent, contract, objective, policy, invariant, waiver, tenant, zone or capability; adding a typed contract or invariant kind; writing or reviewing a check, transform, query, generator, expectation, verification or playbook; deciding "where does this rule belong?" (SoT vs policy pack vs template vs code); or judging whether the model covers a use-case, what is built versus owed, or whether a new concept is needed.
---

# IBN intent model: vocabulary, placement, naming

Paths: `IBN/` is `autonetops_ibn` (platform: engine, ADRs, generic schema). `IH/` is
`autonetops_infrahub` (the lab SoT: schema, seed data, checks, compilers). Intent is authored in
the SoT, so most authoring work lands in `IH/`.

## Sources of truth (read before changing anything they cover)

| What | Where | Authoritative for |
|---|---|---|
| Decisions | `IBN/docs/adr/0015-intent-vocabulary.md`, `0017-vocabulary-alignment-lab-ontology.md` (both *proposed*: argue there, not in a schema) | the definitions |
| Full model, worked example | `IBN/docs/architecture/intent-model.md` | composition, domains, enforcement matrix |
| Platform generics, field guide | `IBN/infrahub/schemas/intent_model.yml`, `IBN/infrahub/schemas/README.md` | the generic kinds |
| Lab schema | `IH/schemas/intent.yml`, `IH/schemas/operations.yml` | the fields you author against: generics, supporting kinds, typed kinds |
| Seed data | `IH/scripts/bootstrap.py` | names and field usage in the live SoT |
| Operational policy | `IBN/docs/adr/0016-intent-profile-packs.md`, `IBN/docs/architecture/intent-profiles.md`, `IBN/planner/policies/` | the policy pack |

If this skill disagrees with those files, they win; fix the skill. If code or seed data
disagrees with the model, the model wins and the difference is recorded in
[references/status.md](references/status.md). The vocabulary is versioned: changing a definition
means an ADR that supersedes 0015, because external adopters build on these words.

| Reference | Read it when |
|---|---|
| [primitives.md](references/primitives.md) | you need a kind's fields, an enum value, or how to create objects |
| [naming.md](references/naming.md) | naming anything, or translating pre-July-2026 vocabulary (`IntentRealm`, `IntentIntent`, policy-as-bundle) |
| [derivation.md](references/derivation.md) | you need to know what a contract becomes: config, expectations, collectors, alerts, and how they link |
| [extension-checklists.md](references/extension-checklists.md) | adding an intent, a kind, a policy, a waiver or a domain; typing a schema; reviewing a change |
| [use-case-patterns.md](references/use-case-patterns.md) | "how do we model X?", "does the model cover X?" |
| [status.md](references/status.md) | before saying that something is checked, compiled or proven |

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

Contracts, policies, invariants and waivers are the four **instruments**. With the intent they
are everything that is authored; the rest is derived (artifact, expectation, plan) or observed
(evidence, verdict, drift, compliance).

| Composition | Why it matters |
|---|---|
| A contract belongs to exactly one intent (Parent, cascade). An intent with zero contracts is a finding. | Without a contract nothing can fail, so the intent is unverifiable. |
| Policies and invariants are referenced, never owned. | One guards many intents and survives any of them being deleted. Look for an existing one before creating a copy. |
| `priority` lives only on the intent and flows down (intent → contract → plan). | Nothing below the intent may raise its own urgency. |
| `domain` is a free-form attribute, one value per intent. | The taxonomy grows without a schema migration. A typo silently detaches every `scope: domain` policy and invariant, so use the starter set. |
| Compliance rolls up the other way: verdict → objective → contract → intent, worst-of; `waived` is its own state. | A waived finding is never green and never red. |

**In force for an intent** = every enabled policy and invariant with `scope: global`, plus
`scope: domain` whose `domains` contains the intent's domain, plus those explicitly linked, minus
live waivers (compare `expires_at` to now; there is no stored active flag). Anything that
resolves instruments must compute all three scopes.

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

If none fit, you are describing mechanism or a fact, not intent. The deletion test: if deleting
the statement would only change *how* the network is built, it was never intent. Walk the
placement ladder.

### Placement ladder (first match wins)

1. **An outcome a consumer or manager would recognize, in one sentence** → `IntentDefinition.description`. No device names, protocols or knobs.
2. **A measurable promise to a named consumer** → a contract. Use a typed kind when the terms must render config or expectations, else `IntentGenericContract` + objectives.
3. **A standing rule on how the network may be designed** → network policy: a kind inheriting `IntentPolicy` plus the merge check that enforces it. A policy with no check is a comment.
4. **A rule on the automation itself** → operational policy, on one of two surfaces (ADR-0016):
   - *when the network may change* → `OpsChangeWindow` in the SoT;
   - *what the engine reads to shape or gate a plan* (blast-radius thresholds, canary strategies, change classes, approval floors, delivery preferences, rate limits) → the policy pack (`IBN_POLICIES_DIR`, reference pack in `IBN/planner/policies/`). Anything whose misconfiguration could remove a human from the loop stays in the pack under CODEOWNERS.
5. **A state condition that must always hold** → a typed invariant kind.
6. **Who / where / with what** → `IntentTenant`, `IntentZone`, `IntentCapability`. Controlled vocabularies: code branches on these values.
7. **A fact about what exists** (device, link, prefix, VRF, ASN, site) → DCIM/IPAM, not intent.
8. **A value that follows mechanically from intent + facts** (session endpoints, allocated addresses, RD/RT, descriptions) → derive it. Compute it in the transform at compile time (the lab derives BGP sessions from contract + cabling) or materialize it with a generator / resource pool. Never hand-author it and never put it in intent.
9. **Vendor syntax or a platform quirk** → the renderer for that platform (`render_<platform>` in `IH/transforms/device_config.py`, templates in `IH/templates/`). Gate on capability, not on vendor name.
10. **What must be observably true** → a compiled expectation. Never authored.
11. **An active probe** → `IBN/remediation/verifications/` with `derives_from`. Read-only.
12. **What to do on failure** → `IBN/remediation/playbooks/<safe_fixes|quarantines|escalations>/`. A safe fix proposes a plan; it never pushes.
13. **An incident worth never repeating** → `IBN/simulations/golden-topologies/<name>/` plus an expectation that fails while the bug exists.

### Slicing intents

One intent per outcome a consumer would recognize. A connectivity intent may own routing,
reachability, security and observability contracts together; contract kinds are not tied to the
intent's domain. Split into separate intents only when **owner, priority or lifecycle** differ
(secops owning the perimeter of a customer VPN is a real split; "it touches two domains" is
not). A different *consumer* is not a different owner: the NOC consuming a service's signals is
the `consumer` of a contract inside the service's intent. Two consequences from the ADRs:

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

What these outputs look like for a real contract, how they are wired in Infrahub and which
values join them: [references/derivation.md](references/derivation.md).

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
  intent gates nothing. (Keys inside the artifact are camelCase; everywhere else the field is
  `derives_from`.)

Observed-side words are fixed: evidence → evaluation (continuous) / verification (triggered) →
verdict (`pass | fail | pre_existing | unverifiable`) → drift → compliance. The **baseline** is
the set of expectations already failing before a change, so a gate blocks regressions, not
history.

## 4. Naming

Object names are lowercase kebab-case and stable: they become `derives_from` URIs, alert labels
and file names, so a rename is a migration. A name is unique across its generic, so all
contract kinds share one namespace, as do all policies (change windows included) and all
invariants. Enum values and capability names are snake_case. Full rules:
[references/naming.md](references/naming.md).

| Kind | Pattern | Examples |
|---|---|---|
| Intent | `<scope>-<outcome>` (WHAT, never how) | `custc-l3vpn-connectivity`, `provider-core-transport`, `fleet-management-plane` |
| Contract | `<scope>-<relationship or subject>` | `custc-ce-to-pe`, `ibgp-core-rr`, `custc-apps-reachable-from-emea-corp` |
| Objective | `<term>`, unique within its contract | `sessions-established` |
| Network policy | the requirement: `<subject>-<requirement>` | `ebgp-max-prefix-required` |
| Change window | `<scope>-<cadence or purpose>[-freeze]` | `emea-standard-maintenance`, `q3-core-audit-freeze` |
| Invariant | `[<scope>-]<property>`; a typed kind's property echoes its type | `custc-no-leak`, `fleet-oob-cabled`, `no-orphan-vrf` |
| Waiver | `<subject>-<what is violated>` | `custc-site2-single-homed` |
| Typed kinds | `Intent<Thing>Contract`, `Intent<Condition>Invariant`, `Intent<Thing>Policy`; `Ops*` for operational kinds | `IntentRoutingContract`, `IntentNoLeakInvariant`, `OpsChangeWindow` |

Scope prefix: tenant abbreviation (`custc`), `provider`, `fleet`, or a topology scope (`core`,
`inet`, `emea`). An intent and the contracts it owns share one prefix so `grep custc` returns
the tree. A shared policy or invariant is named for the condition it states, not for one
tenant; it takes a tenant prefix only when its `scope` is `intent`.

## 5. Overloaded words: always qualify them

| Word | Meanings here | Say |
|---|---|---|
| **policy** | `IntentPolicy` (network / operational); policy pack files; route policy (route-maps); security rules | "network policy", "operational policy", "policy pack", "route policy" |
| **contract** | `IntentContract`; cross-layer data contract in `IBN/contracts/` (Plan v1, profile v1); driver verb contract | "intent contract", "data contract", "verb contract" |
| **rule** | a compiled check definition in `IBN/validator/rules/`; `IntentSecurityRule` (one line of a security contract) | a policy *is* a standing rule, but never name an authored object or kind "rule", and never say "rules" for policies and invariants together |
| **service** | the instantiated noun: sites, VRFs, bandwidth (facts and design) | "the service is the noun, the contract is the promise about it" |
| **invariant** | the authored object; its merge projection; its always-on expectation | name the surface: "the `custc-no-leak` merge projection" |
| **gate** | merge gate (check); stage gate (expectations at dispatch); dispatch gate (window, approval) | the qualified form |
| **domain** | intent domain tag; controller domain (executor `atomicity: domain`); failure domain | "intent domain", "controller domain", "failure domain" |
| **profile** | intent profile = policy pack (ADR-0016); Infrahub node profiles (`generate_profile`); `ddos_profile` | "policy pack", "Infrahub profile" |
| **role** | device role, interface role, routing-contract role, `attach_device_role`: four separate enums | name which one |
| **severity** | invariant severity (`warning\|major\|critical`); signal paging scale (`sev1..sev4`, authored on the signal today) | "invariant severity", "paging scale" |
| **scope** | policy/invariant `scope`; waiver `subject_scope`; naming scope prefix | the qualified form |

## 6. Deriving an intent from a request

1. **Outcome.** Restate the request as one sentence a consumer could verify, and apply the
   deletion test. If an existing intent already names this outcome for the same owner and
   priority, add contracts to it.
2. **Root.** Scope prefix and name, `domain`, `owner`, `priority`, `tenant`.
3. **Contracts.** List what must be observably true for the outcome to be honored. Each
   statement is a term. Group terms into contracts by consumer and by kind, with a typed kind
   wherever the terms must render config or expectations. Anchor every term to SoT objects.
4. **Policies and invariants.** Compute what is already in force. Add one only for a condition
   none of them states, and prefer `scope: domain` over a copy per tenant.
5. **Waivers.** A known, sanctioned violation becomes a waiver with an expiry, never a disabled
   invariant.
6. **Everything left over** is a fact, a derived value or mechanism (ladder steps 7 to 9).
   Don't author it as intent.
7. **Say what will be proven.** For each contract, state what compiles and what is evaluated
   today ([references/status.md](references/status.md)), so the distance between "merged" and
   "proven" is explicit.

Fields and enum values: [references/primitives.md](references/primitives.md). Mechanics and a
worked tree: [references/extension-checklists.md](references/extension-checklists.md) § A.

## 7. Extending the model

Look the use-case up in [references/use-case-patterns.md](references/use-case-patterns.md)
before inventing anything. Most needs are a new *typed kind* under an existing generic; a new
*concept* needs an ADR. Prefer the narrowest change: new data over a new attribute, a new
attribute over a new kind, a new kind over a new concept. Steps per change, the typing rules
for schema kinds and the review checklist are in
[references/extension-checklists.md](references/extension-checklists.md).

## 8. Gaps: the known ones, and what to do with a new one

The model is ahead of the code. [references/status.md](references/status.md) lists what is
built and what is owed; read it before saying that something is checked, compiled or proven.
The traps that matter most while authoring:

- Only `IntentRoutingContract` compiles expectations, gates a stage and lends its intent's
  priority to a plan.
- Merge checks see only explicit `intent → invariants` links. `scope: global | domain`,
  `severity`, `enabled` and waivers have no effect at merge time yet.
- Waivers, objectives and the one network policy exist as data only.
- The seed data slices one customer outcome into five intents. Follow the slicing rule in § 2,
  not the seed.

Real requests will hit things that don't fit. Sort a new gap before building around it:

| The gap | Do | Record it |
|---|---|---|
| This skill is wrong or silent and the sources are clear | follow the sources | fix the skill in the same change |
| A kind, field or enum value is missing | author what fits; propose the narrowest schema change to the user | nothing enters the schema without review |
| The kind exists but nothing compiles, checks or evaluates it | author it anyway and say plainly that it is unproven | `references/status.md`, dated, naming the file that shows it |
| No word in the vocabulary fits | stop and describe the need in the user's terms | `references/use-case-patterns.md` § 3, then an ADR |

Never close a gap by putting mechanism into intent, inventing a word, packing structured meaning
into a free-text field, or dropping a term without saying so.
