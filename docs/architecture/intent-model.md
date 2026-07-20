# The intent model: a common vocabulary

This project's open-source ambition is to unify network automation
*delivery* around Infrahub — and delivery only composes across teams and
tools when the words compose first. This document defines the vocabulary:
what counts as intent, the kinds of intent, the derived and observed
vocabulary around them, and — the part that actually matters — **how the
kinds correlate and where each one is enforced**. ADR-0015 records the
naming decision; this is the full model.

Two ground rules before the words:

1. **Intent is outcome, never mechanism.** "Customer C's sites can reach
   each other" is intent; "vrf CUST-C on pe-emea-01" is compilation output.
   If deleting a statement would only change *how* the network is built,
   it was never intent.
2. **Every check traces to intent.** Nothing gates a merge, a rollout or a
   compliance report unless it can cite the intent it derives from
   (`derives_from: infrahub://...`). A check nobody can trace is folklore
   with root access.

## The Intent and its four instruments

**Intent** is two things, deliberately. Loosely, it is the umbrella word for
the whole authored layer ("the intent layer"). Precisely, it is a **node in
the SoT**: the aggregate root that names an outcome, carries an owner, a
priority and a domain — and *does nothing else*. An Intent node compiles to
nothing. It exists to give identity, urgency and ownership to the four
**instruments** attached to it, which do all the work:

> An intent is **achieved by its contracts**, **governed by policies**,
> **guaranteed by invariants**, and **tempered by waivers**.

The four verbs are the composition model. Contracts define what "achieved"
looks like; policies rule how it may be realized; invariants floor what must
never be untrue while realizing it; waivers carve reviewed, expiring holes.
The next section defines the three authored instrument kinds; waivers and
the composition rules follow.

## The three instrument kinds

Each is distinguished by one question:

| Kind | The question that classifies it | Fails as | Closest familiar idea |
|---|---|---|---|
| **Contract** | *Who loses if this breaks?* — a nameable consumer | a broken promise (page the owner, apologize to the consumer) | SLO/SLA (SRE) |
| **Policy** | *Which actions or designs does this forbid or shape?* | a **rejected change** (nothing broke; the gate said no) | admission policy (OPA), change management rules |
| **Invariant** | *If this is false, is it an incident — regardless of what changed recently?* | an **incident** (the network is in a state it must never be in) | safety property (formal methods) |

### Contract

A promise of a measurable outcome to a named consumer: a customer, a peer,
an internal team. Contracts have a beneficiary, terms, and (ideally) an
owner and a priority. `IntentRoutingContract` — PE/CE sessions that must be
established, prefix limits, communities — is the first implemented kind.

A **Service** (the thing Infrahub models get built around) and a contract
are not rivals: *the service is the noun, the contract is the promise about
the noun.* An L3VPN service instance names sites, VRFs, bandwidth; its
contract states what must be observably true for that instance to be
honored (sessions up, prefixes bounded, reachability between the sites). If
a schema wants a single node kind, model the Service and embed its
contract terms — but keep the *word* "contract" for the testable terms,
because that is precisely the part expectations compile from. A service
without a contract is furniture: it exists, but nothing can fail.

Suggested refinement (borrowed from SRE, adopt when needed): an
**objective** is one measurable term inside a contract ("session
established", "≤100 prefixes", "p99 RTT < 30ms"). Contracts bundle
objectives; expectations are compiled per objective.

### Policy

A standing, unilateral rule that constrains how outcomes may be realized.
No single beneficiary — it applies to *classes* of things. Two subjects,
same shape:

- **Network policies** constrain the network's design and configuration:
  "every eBGP session carries max-prefix", "no public addressing on
  management", "communities from zone X are forbidden on Y".
- **Operational policies** constrain the *automation itself*: change
  windows and freezes (`OpsChangeWindow`), canary strategies and their
  approval bars, pre-approved change classes (ADR-0014), rate limits,
  protocol delivery preferences.

That the same word covers both is a feature: both are reviewed data, both
gate decisions, both answer "what are the rules of the game?". Only the
subject differs. Policies as *data under review* — never hardcoded — is
already a repo law; this vocabulary just names what that data is.

### Invariant

A condition on **network state** that must always hold, independent of any
contract and any recent change: "every device keeps two uplinks", "the
management plane is reachable", "no VRF exists without an owning service",
"IGP is loop-free". Invariants are the safety floor under everything.

The policy/invariant distinction is not pedantry — it decides the
enforcement point:

- A **policy** is checked at *decision time* (intent merge, plan compile,
  dispatch). You can refuse the action; that is the whole point.
- An **invariant** is checked *continuously against observed state*.
  There is no action to refuse — if it is false, you are already in an
  incident, whoever's change (or no change at all) caused it.

Many invariants also project onto decision time ("would this change remove
the second uplink?" — the `infrahub/checks/` sketch calls this *invariant
removal*). That projection is a derived policy-shaped check; the invariant
itself remains a statement about state.

## How they compose: the correlation rules

These are the decided cardinalities and directions — the part that makes the
vocabulary a *model* instead of a glossary:

1. **A contract belongs to exactly one intent** (composition — delete the
   intent, the contract has no reason to exist). An intent with zero
   contracts is untestable furniture; that is a merge-check finding, not a
   style opinion.
2. **Policies and invariants are referenced, never owned.** One policy
   governs many intents; one invariant guarantees many. They attach by
   **scope**: `global` (fleet-wide, no intent link), `domain` (all intents
   in a domain), or `intent` (explicitly linked). Deleting an intent never
   deletes a policy.
3. **A waiver has exactly one target and one subject.** Target: the policy
   or invariant being waived. Subject: the intent, contract or device scope
   it is waived *for*. Plus a named owner and a hard expiry. Governance
   rule: the waiver is *requested* by the subject's owner and *approved* by
   the target's owner — you don't waive your own rules for yourself.
4. **Priority lives on the intent and only flows down**: intent → contract →
   the plans that touch its devices (highest wins; already implemented in
   `orchestrator/priority.py`). Nothing below the intent may raise its own
   priority.
5. **Compilation touches instruments, never the root**: contracts and
   policies and invariants compile to artifacts + expectations; the Intent
   node contributes only the `derives_from` URI root
   (`infrahub://Intent/<name>/contract/<name>`), so every downstream check
   can answer "why do you exist?" in one hop.
6. **Compliance rolls up the opposite way**: verdict → objective → contract
   → intent, worst-of, with waived findings shown as `waived` (visible,
   never green, never red) until expiry flips them back to findings.
7. **Observability rides two patterns**: per-service observability terms
   are *objectives inside the service's contracts* (the rendered
   `ContractExpectations` already carry `telemetry.required` freshness and
   `alerting` blocks); fleet-baseline observability ("every production
   device streams gNMI, freshness ≤30s") is its own intent in the
   `observability` domain. *Collection* is not a domain — it is what
   observability contracts compile into (subscription artifacts for the
   collectors), exactly as connectivity contracts compile into VRF config.

Migration note: today's lab schema chains `IntentRoutingContract → policy →
intent`, using a policy node as a *grouping* level between contract and
intent. Under this model that middle level flattens: contracts link straight
to their intent, and "policy" is reserved for rule instruments (rule 2
above). One rename in the SoT schema, and `priority.py`'s walk shortens by
a hop.

## Domains

`domain` is an **attribute on the Intent node, not a node kind** — the
taxonomy must be able to grow without a schema migration. Starter set, with
opinions on the ones proposed so far:

| Domain | Holds intents about | Note |
|---|---|---|
| `connectivity` | what consumers get: VPNs, transit, peering, access | most contracts live here |
| `routing` | how the control plane is designed: protocols, route-policy architecture, TE | keep separate from connectivity: different owners, different failure modes |
| `observability` | fleet visibility baselines: streaming coverage, freshness, alerting floors | **`collection` folds in here** — collection is the compiled *mechanism* (subscription artifacts), not an intent domain |
| `security` | segmentation, zoning, control-plane protection, AAA | policies-heavy domain |
| `resilience` | redundancy floors, diverse paths, failover budgets | invariants-heavy domain |
| `capacity` | utilization ceilings, latency budgets, QoS promises | contracts with numeric objectives |
| `compliance` | regulatory: logging retention, crypto standards, banned protocols | audit-facing; waivers concentrate here |
| `lifecycle` | OS versions, EOL hardware, config hygiene | the "boring" domain that prevents incidents |
| `operations` | the automation's own rules: windows, freezes, change classes, canary strategies, rate limits | operational policies root here |

On **`reachability`**: not a domain — it is an *objective kind* that appears
inside contracts across domains ("site A reaches site B" in connectivity,
"management plane reachable" in operations/resilience). Promoting it to a
domain would scatter one intent's terms across two intents.

The lab's workshop ontology calls this concept a **realm** and models it as
a node kind; ADR-0017 records the alignment: same concept, attribute form
(the taxonomy must grow without schema migrations), with `reliability →
resilience`, `performance → capacity`, and `reachability` folding into
objectives as above. Domain values are customer data — each tenant's
Infrahub carries its own taxonomy; this table is the recommended starter.

## The supporting vocabulary: tenant, zone, capability

Three kinds a customer's intent layer should model so that critical
questions are answered by a typed relationship instead of a naming
convention (adopted from the lab's workshop ontology, ADR-0017):

- **Tenant** — WHO an intent serves: a customer, a partner, the provider
  itself. A contract's `consumer` is the prose form; the tenant kind is
  the structured one, and tenant-relative invariants (no-leak, prefix
  authorization) are meaningless without it.
- **Zone** — WHERE, as a named region instruments can reference: `core`,
  `transit`, `internet_peering`, `management`, … A contract says "never
  toward internet-peers" without enumerating devices.
- **Capability** — WITH WHAT each platform can participate: `gnmi`,
  `ssh_cli`, `mpls`, … The switchboard between intent and mechanism:
  collectors are selected off it, renderer arms gate on it,
  `capability_present` invariants check it — and when capability records
  land in the SoT (ADR-0011), the planner's protocol selection and driver
  resolution read it instead of the interim profile bindings (ADR-0016).

All three are **controlled vocabularies**, never free text: every machine
decision downstream branches on these values, so free text here is
undefined behavior there.

## Three axes that look alike (and must not be conflated)

| Axis | Lives on | Vocabulary | Answers |
|---|---|---|---|
| **priority** | the Intent (only; flows down) | low / medium / high / critical | how important is this outcome to the business? Inherited by plans; gates emergency eligibility. |
| **severity** | the Invariant (and observability signals) | warning / major / critical | what is a violation of this specific condition worth when it happens? Merge-time projections derive their blocking behavior from it. |
| **blast radius** | the Plan (computed); the change window (as a ceiling) | low / moderate / high | how big is this specific change? Selects the canary strategy and the admitting windows. |

A `critical`-priority intent can receive a `low`-blast-radius change
guarded by a `critical`-severity invariant. Three different questions,
three different objects — and per-customer thresholds for the third axis
are profile data (ADR-0016), while the first two never leave the intent
layer.

## The derived vocabulary (compiled, never authored)

Everything below is **generated from intent** — reviewed as output, never
written by hand:

- **Artifact** — rendered config (and other consumables) per control point.
  The *how*, checksummed at the ADR-0001 boundary.
- **Expectation** — the compiled, per-device *checkable form* of intent:
  what must be observably true if the intent is honored. Contracts compile
  to session/prefix/reachability expectations; network policies to
  config-shape and behavior expectations; invariants to always-on
  expectations with fleet scope. **Expectation is the only check form the
  runtime evaluates** — one vocabulary between compiler and validator.
  Rule of the repo: every config artifact has a sibling expectation
  artifact.

  Four disciplines make expectations prove instead of spam (adopted from
  the lab's workshop ontology, ADR-0017):
  1. **Ranges, never exact values** — `route_count <= 200`, not `== 173`;
     exact values turn normal churn into false alarms.
  2. **Forbidden behavior is stated explicitly** — you cannot prove a
     negative you never wrote down.
  3. **The collector is derived from platform capability, never chosen by
     hand** — re-platform a box and `observedVia` flips with no intent
     edit (ADR-0011/0012).
  4. **Freshness is part of the proof** — stale evidence is no evidence;
     a dead collector reads as *unknown*, never as *fine*.
- **Plan** — the declarative rollout document (ADR-0003); **stages**,
  **steps**, **gates** inside it; **blast radius** as its risk annotation;
  **change class** as its provable diff shape (ADR-0014). A plan is not
  intent — it is the *transaction* that moves the network toward intent.
- **Rule** — reserved word. A rule is a compiled/derived check definition
  inside the validator (`validator/rules/`). Never use "rule" for intent:
  authors write contracts, policies and invariants; compilers emit
  expectations and rules. (Colloquial "guardrail" ≈ operational policy;
  fine in prose, not a kind.)

## The observed vocabulary

- **Evidence** — raw, timestamped observations (executor verb results,
  telemetry samples). Append-only; the stuff verdicts cite.
- **Evaluation** — comparing expectations against observed state,
  *passively and continuously* (telemetry-driven).
- **Verification** — the *active, triggered* form: probes run at a moment
  that matters (post-deploy gate, nightly suite). Same expectations,
  different clock and different evidence collection.
- **Verdict** — per check: `pass | fail | pre_existing | unverifiable`.
  Unverifiable is first-class: a device nobody can observe never counts as
  passing.
- **Baseline** — the pre-change snapshot of failing expectations, so gates
  block *regressions*, not history.
- **Drift** — confirmed divergence between intent and observed state,
  classified (benign / dangerous-auto-fixable / dangerous-escalate).
- **Compliance** — the aggregate, per-intent answer to "is this contract /
  invariant honored right now?", written back into the SoT next to the
  intent (`OpsPlanRecord` today; per-contract compliance records next).

## How they correlate

```
                         INTENT (in the SoT, reviewed)
        ┌──────────────┬─────────────────────┬──────────────────┐
        │  Contract    │       Policy        │    Invariant     │
        │  (promise    │ (rules of the game: │ (must never be   │
        │  to someone) │  network + operational) │  false)      │
        └──────┬───────┴──────────┬──────────┴────────┬─────────┘
               │ compile          │ gate & shape      │ compile
               ▼                  ▼                   ▼
        artifacts + expectations  │            always-on expectations
               │                  │                   │
               ▼                  ▼                   │
             PLAN  ◄── blast radius · canary strategy · windows ·
               │        change classes · rate limits · approval bars
               │ execute (staged, gated)
               ▼
            network ──► evidence ──► evaluation / verification
                                          │
                                          ▼
                        verdicts ──► drift ──► compliance ──► back beside
                                                              the intent
```

The enforcement matrix — *which intent kind bites where* — is the practical
payoff of the vocabulary:

| Enforcement point | What runs | Which intent bites |
|---|---|---|
| Intent merge (Infrahub proposed change) | `infrahub/checks/`: bounds, redundancy floors, invariant-removal projections | Policies; invariants (projected) |
| Plan compile (planner) | blast radius, canary strategy, change-class classification, rate limits | Operational policies |
| Plan approval | PR review scaled by blast radius, or pre-approved class | Operational policies (the approval bar *is* policy) |
| Dispatch (per stage) | window re-check, approval re-check, expectation gates with baseline/soak | Operational policies + contract/invariant expectations scoped to the stage |
| Continuous | telemetry-driven evaluation, drift classification, nightly verification suites | Contracts + invariants (the long tail where they actually live) |

Reading the matrix row-wise explains the system; reading it column-wise
explains each term. A contract is barely visible at merge time and dominant
in continuous evaluation; an operational policy is invisible to telemetry
and dominant at compile/dispatch. That asymmetry is why the words must stay
distinct.

## The fourth instrument: the Waiver

Every real network carries sanctioned violations — the legacy box that
cannot do max-prefix, the customer exempted from a freeze. Unmodeled, these
become tribal knowledge and eternal red dashboards; modeled, they become
reviewable and — crucially — **expiring**:

> **Waiver** — a reviewed, owned, *time-boxed* permission for a named
> subject to violate a named policy or invariant. Expired waiver = the
> violation is a finding again. No waiver is permanent.

Part of the model (correlation rule 3: one target, one subject, an owner,
a hard expiry; requested by the subject's owner, approved by the target's
owner), not yet implemented in code. It earns its place because both the
validator ("suppress this known drift until date X") and the planner ("this
device is exempt from delivery-preference policy") need the same object,
and "exception" (its rejected synonym) invites permanence. Waivers
correlate as *negative intent*: evaluated wherever their target would bite,
always with an expiry check first.

## A worked example

One intent, all four instruments, walked through the enforcement matrix.
The node kinds are real — `infrahub/schemas/intent_model.yml` implements
this model (`infrahub/schemas/README.md` explains how to build around it);
below is the example in condensed shape:

```yaml
intent:
  name: cust-c-l3vpn
  domain: connectivity
  description: Customer C's three sites communicate privately over the MPLS core
  owner: provider-edge-team
  priority: high

contracts:                                # ACHIEVED BY (owned, 1..*)
  - name: cust-c-sessions
    objectives:
      - each site's PE-CE eBGP session is established     # sessionState
      - each session carries at most 100 prefixes         # maxPrefixes
  - name: cust-c-reachability
    objectives:
      - site loopbacks are mutually reachable within the VRF
  - name: cust-c-visibility                # per-service observability terms
    objectives:                            # ride the intent they observe
      - PE interface + session telemetry streamed, freshness <= 30s
      - alert fires within 60s of session-down

policies:                                  # GOVERNED BY (referenced, scoped)
  - ebgp-max-prefix-required   # network policy, scope: global
  - emea-standard-maintenance  # operational: OpsChangeWindow, scope: domain
  - interface-descriptions     # operational: pre-approved change class (ADR-0014)

invariants:                                # GUARANTEED BY (referenced)
  - customer-site-dual-homed   # every customer site attaches to >= 2 PEs
  - no-orphan-vrf              # no VRF exists without an owning contract

waivers:                                   # TEMPERED BY (target + subject + expiry)
  - name: cust-c-site3-single-homed
    target: invariant/customer-site-dual-homed
    subject: contract/cust-c-sessions @ site-3
    reason: second circuit on order, carrier ETA
    owner: provider-edge-team              # requested by subject's owner
    approved_by: resilience-team           # approved by target's owner
    expires: 2026-09-30                    # hard; then it is a finding again
```

Now the lifecycle, instrument by instrument:

1. **Author.** An engineer adds site 3 to the intent on an Infrahub branch
   and opens a proposed change. Merge checks run: `ebgp-max-prefix-required`
   (policy) verifies the new session declares a prefix limit; the
   dual-homing *projection* of `customer-site-dual-homed` (invariant) flags
   site 3 — and finds the approved waiver, so the finding lands as `waived`,
   not blocking. The intent merges.
2. **Compile.** The contracts render *artifacts* (VRF + BGP config for the
   new PE-CE pair; gNMI subscription config for `cust-c-visibility`) and
   *expectations* (session established, ≤100 prefixes, loopback
   reachability, telemetry freshness ≤30s) — every one stamped
   `derives_from: infrahub://Intent/cust-c-l3vpn/contract/...`.
3. **Plan.** The planner diffs artifacts: two devices change → blast radius
   `low|moderate`; the diff is BGP-shaped, so no pre-approved change class
   matches (had it been descriptions-only, `interface-descriptions` would
   have waived plan review); canary strategy selected; the timeline fits
   stages into `emea-standard-maintenance`; the plan inherits
   `priority: high` from the intent. Rollout approval per ADR-0003.
4. **Dispatch.** Windows re-checked per stage; after the canary stage the
   gate evaluates the *contract expectations scoped to the touched devices
   and their neighbors* — session up on the new pair, prefix count sane,
   nothing regressed on the unchanged PE. Soak, then remainder.
5. **Prove, continuously.** Telemetry-driven evaluation keeps scoring the
   session, reachability and freshness expectations; `no-orphan-vrf` and
   `customer-site-dual-homed` run fleet-wide. Site 3's single-homing shows
   as `waived` on every report until 2026-09-30 — on expiry it becomes a
   red finding and, if a remediation playbook exists, a *proposed plan*.
6. **Roll up.** Verdicts aggregate per objective → per contract → the
   intent: `cust-c-l3vpn: compliant (1 waived)` — one line a human and an
   API can both consume, sitting in the SoT next to the intent that caused
   all of it.

The same example read column-wise: delete the *contracts* and nothing can
ever fail; delete the *policies* and anything may be built anyhow, anytime;
delete the *invariants* and the safety floor is gone even when every
contract is green; delete the *waiver* and site 3 is an eternal red light
everyone learns to ignore. All four instruments, one intent.

## Alternatives considered (and why not)

- **"Constraint" as the umbrella for policy + invariant** — rejected: it
  erases the action-vs-state distinction that decides the enforcement
  point, which is the most operationally useful thing the vocabulary does.
- **"SLA" instead of contract** — rejected: legal connotation; and the
  useful part is the testable terms (SLO-shaped), not the penalty clause.
- **"Rule" as an authored kind** — rejected: hopelessly overloaded, and we
  need it for the compiled check definitions. Authors don't write rules;
  compilers do.
- **One mega-kind ("policy" for everything)** — rejected: when one word
  covers "customer C gets L3VPN" and "no changes on Fridays", every
  conversation starts with ten minutes of disambiguation. Three kinds, one
  classifying question each, is the minimum that stays sayable.
- **"Desired state" as the umbrella** — kept as an *explanation* of intent,
  not a kind: desired state is what intent compiles into; the intent is why.
