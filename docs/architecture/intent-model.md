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

## The three kinds of intent

**Intent** is the umbrella term — any reviewed statement of desired outcome
living in the SoT. It comes in exactly three kinds, distinguished by one
question each:

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

## Suggested fourth kind: the Waiver

Every real network carries sanctioned violations — the legacy box that
cannot do max-prefix, the customer exempted from a freeze. Unmodeled, these
become tribal knowledge and eternal red dashboards; modeled as intent, they
become reviewable and — crucially — **expiring**:

> **Waiver** — a reviewed, owned, *time-boxed* permission for a named
> subject to violate a named policy or invariant. Expired waiver = the
> violation is a finding again. No waiver is permanent.

This is proposed vocabulary (nothing implements it yet); it earns its place
because both the validator ("suppress this known drift until date X") and
the planner ("this device is exempt from delivery-preference policy") need
the same object, and "exception" (its rejected synonym) invites
permanence. Waivers correlate as *negative intent*: evaluated wherever
their target would bite, always with an expiry check first.

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
