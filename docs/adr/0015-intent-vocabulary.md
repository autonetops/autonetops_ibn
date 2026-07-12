# 0015 — Intent vocabulary: contracts, policies, invariants

- Status: proposed
- Date: 2026-07-12

## Context

The project is being opened up with the explicit goal of unifying network
automation delivery around Infrahub. Delivery only composes across teams and
tools when the words do: today "policy", "contract", "rule", "invariant" and
"intent" are used interchangeably across the industry, and every integration
starts by re-negotiating them. We already have implicit answers scattered
through the repo (IntentRoutingContract, planner *policies*, validator
*rules*, checks that guard "invariant removal") — this ADR makes them
explicit before external contributors harden the ambiguity. The full model
with correlations and enforcement points lives in
`docs/architecture/intent-model.md`; this records the decision.

## Decision

1. **Intent** is both the umbrella term for the authored layer and,
   precisely, the **aggregate-root node in the SoT**: name, owner,
   `priority`, `domain`, description — and nothing that compiles. The
   Intent node exists to give identity, urgency and ownership to the
   instruments attached to it. Intent is outcome, never mechanism.
2. Four **instruments** do the work, summarized as: *an intent is achieved
   by its contracts, governed by policies, guaranteed by invariants, and
   tempered by waivers.* The three authored rule-kinds are classified by
   one question each:
   - **Contract** — a promise of a measurable outcome to a named consumer.
     *Who loses if it breaks?* Fails as a broken promise.
   - **Policy** — a standing rule constraining how outcomes may be realized;
     two subjects, same shape: *network* policies (constrain the network)
     and *operational* policies (constrain the automation: windows, canary
     strategies, change classes, rate limits, approval bars).
     *Which actions or designs does it forbid or shape?* Fails as a
     rejected change.
   - **Invariant** — a condition on network state that must always hold,
     independent of any contract or recent change.
     *If false, is it an incident regardless of what changed?* Fails as an
     incident. Policies bite at decision time; invariants are evaluated
     continuously (with optional decision-time projections, e.g.
     invariant-removal checks).
3. **Composition rules** (full model in
   `docs/architecture/intent-model.md`):
   - a contract belongs to exactly one intent (owned, 1..*; an intent with
     zero contracts is a merge-check finding);
   - policies and invariants are **referenced, never owned**, attaching by
     scope `global | domain | intent`;
   - a waiver names one target (policy or invariant), one subject (intent,
     contract or device scope), an owner and a **hard expiry**; requested by
     the subject's owner, approved by the target's owner;
   - priority lives on the intent and only flows down (intent → contract →
     plan); compliance rolls up the other way (verdict → objective →
     contract → intent, worst-of, `waived` visible as its own state);
   - `domain` is an **attribute** on Intent, not a node kind (starter set:
     connectivity, routing, observability, security, resilience, capacity,
     compliance, lifecycle, operations). *Collection* is not a domain —
     it is what observability contracts compile into; *reachability* is an
     objective kind inside contracts, not a domain.
4. A **Service** is the instantiated noun; its **contract** is the testable
   terms about it. Schemas may embed contract terms in a service kind, but
   the word "contract" is reserved for the checkable terms — the part
   expectations compile from. **Objective** (one measurable term inside a
   contract) is available as a refinement.
5. **Expectation** is the only compiled check form the runtime evaluates —
   contracts, policies and invariants all compile down to expectations
   (plus artifacts). **Rule** is reserved for compiled/derived check
   definitions in the validator and must never name authored intent.
6. Observed-side vocabulary is fixed as: **evidence → evaluation
   (continuous) / verification (triggered) → verdict
   (pass | fail | pre_existing | unverifiable) → drift (classified) →
   compliance**, with **baseline** naming the pre-change failure set.
7. **Waiver** naming: "exception" is rejected because it invites
   permanence; no waiver is permanent. (Shape and governance in decision 3;
   not yet implemented in code.)
8. Traceability is mandatory: every expectation, rule, gate and verification
   cites the intent it derives from (`derives_from: infrahub://...`).
   A check that cannot cite intent does not gate anything.

## Consequences

- Existing names already comply: `IntentRoutingContract` (contract),
  `OpsChangeWindow` / `change_classes.yaml` / `canary_strategies.yaml`
  (operational policies), `validator/rules/` (compiled rules),
  `ContractExpectations` (expectations). New kinds must pick their word by
  the classifying questions above.
- One existing structure does NOT comply: the lab SoT chains
  `IntentRoutingContract → policy → intent`, using a "policy" node as a
  grouping level between contract and intent. Under decision 3 that level
  flattens — contracts link straight to their intent, "policy" is freed for
  rule instruments — and `orchestrator/priority.py`'s walk shortens by a
  hop. Schema migration owed in the SoT repo alongside
  `infrahub/schemas/intent_model.yml` here: `IntentRoutingContract` gains
  `inherit_from: [IntentContract]`, and `OpsChangeWindow` (with future
  operational-policy kinds) gains `inherit_from: [IntentPolicy]` so "what
  rules are in force" has one query.
- `infrahub/checks/` implement policy enforcement and invariant
  *projections* at intent-merge time; naming in that directory should say
  which ("policy_" / "invariant_" prefixes when files land).
- Docs and schema descriptions use these words consistently; drive-by
  synonyms ("rule" for a policy, "SLA" for a contract) are review findings.
- The vocabulary is versioned with the repo: changing a definition is an
  ADR superseding this one, not a doc edit — external adopters will build
  on these words.
