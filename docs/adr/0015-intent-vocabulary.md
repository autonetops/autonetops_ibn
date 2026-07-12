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

1. **Intent** is the umbrella term: any reviewed statement of desired
   outcome in the SoT. Intent is outcome, never mechanism.
2. Intent comes in **exactly three authored kinds**, each classified by one
   question:
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
3. A **Service** is the instantiated noun; its **contract** is the testable
   terms about it. Schemas may embed contract terms in a service kind, but
   the word "contract" is reserved for the checkable terms — the part
   expectations compile from. **Objective** (one measurable term inside a
   contract) is available as a refinement.
4. **Expectation** is the only compiled check form the runtime evaluates —
   contracts, policies and invariants all compile down to expectations
   (plus artifacts). **Rule** is reserved for compiled/derived check
   definitions in the validator and must never name authored intent.
5. Observed-side vocabulary is fixed as: **evidence → evaluation
   (continuous) / verification (triggered) → verdict
   (pass | fail | pre_existing | unverifiable) → drift (classified) →
   compliance**, with **baseline** naming the pre-change failure set.
6. **Waiver** is reserved (not yet implemented) for a reviewed, owned,
   time-boxed permission for a named subject to violate a named policy or
   invariant. No waiver is permanent; "exception" is rejected as its name
   because it invites permanence.
7. Traceability is mandatory: every expectation, rule, gate and verification
   cites the intent it derives from (`derives_from: infrahub://...`).
   A check that cannot cite intent does not gate anything.

## Consequences

- Existing names already comply: `IntentRoutingContract` (contract),
  `OpsChangeWindow` / `change_classes.yaml` / `canary_strategies.yaml`
  (operational policies), `validator/rules/` (compiled rules),
  `ContractExpectations` (expectations). New kinds must pick their word by
  the classifying questions above.
- `infrahub/checks/` implement policy enforcement and invariant
  *projections* at intent-merge time; naming in that directory should say
  which ("policy_" / "invariant_" prefixes when files land).
- Docs and schema descriptions use these words consistently; drive-by
  synonyms ("rule" for a policy, "SLA" for a contract) are review findings.
- The vocabulary is versioned with the repo: changing a definition is an
  ADR superseding this one, not a doc edit — external adopters will build
  on these words.
