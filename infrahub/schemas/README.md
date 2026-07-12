# SoT schemas: the intent model

Two schema files live here, loaded into Infrahub by repository sync
(`.infrahub.yml`) or manually with `infrahubctl schema load infrahub/schemas/`.
Before the **first** load into an existing SoT: dry-run with
`infrahubctl schema check` (client-side validation misses server rules, e.g.
the 128-char description cap), and confirm none of the `Intent*` kind names
below already exist there (`GET /api/schema` filtered to the `Intent`
namespace) — a same-named kind of a different shape fails the load, and one
of a compatible shape gets silently merged:

| File | What it defines |
|---|---|
| `intent_model.yml` | The intent model (ADR-0015): `Intent` and its four instruments |
| `ops_plan_record.yml` | `OpsPlanRecord` — the closed-loop feedback node the orchestrator upserts after every dispatch |

This README explains the intent model so that a human **or an AI agent** can
create, extend and query it without reading anything else. The reasoning
behind the model is in `docs/architecture/intent-model.md`; the naming
decision is ADR-0015 (status: proposed — argue there, not in the schema).

## The model in one breath

> An **Intent** is *achieved by* its **Contracts**, *governed by*
> **Policies**, *guaranteed by* **Invariants**, and *tempered by*
> **Waivers**.

```
                       IntentDefinition  (the root: WHY + owner + priority + domain)
                      /       |        \
        owns (cascade)   references      references
                    /         |            \
        IntentContract   IntentPolicy   IntentInvariant     ← generics
             |            (scope:        (scope:              (typed kinds
        owns (cascade)     global|        global|              inherit these)
             |             domain|        domain|
        IntentObjective    intent)        intent)
                              ▲              ▲
                              └── target ────┘
                                   IntentWaiver ── subject ──► intent | contract (+ scope)
                                   (one target, one subject, hard expiry)
```

The Intent node **compiles to nothing** — it lends identity (`derives_from`
URIs root at it), urgency (`priority`) and ownership to the instruments,
which do all the work.

## Kind reference

| Kind | Shape | Role | Key attributes | Key relationships |
|---|---|---|---|---|
| `IntentDefinition` | node | Aggregate root | `name` (unique), `domain` (free-form tag), `owner`, `priority` (low/medium/high/critical), `status` | `contracts` (owns, cascade), `policies` / `invariants` (references) |
| `IntentContract` | **generic** | A promise to a named consumer | `name`, `consumer`, `status` | `intent` (Parent, exactly one), `objectives` (owns, cascade) |
| `IntentObjective` | node | One measurable term (SLO-shaped) | `name`, `expression` (the checkable statement) | `contract` (Parent, exactly one) |
| `IntentPolicy` | **generic** | A rule on HOW outcomes may be realized | `subject` (network/operational), `scope`, `domains`, `enforcement`, `enabled` | `intents` (reference, only when scope=intent) |
| `IntentInvariant` | **generic** | A condition on state that must always hold | `severity`, `scope`, `domains`, `expression`, `enabled` | `intents` (reference, only when scope=intent) |
| `IntentWaiver` | node | Time-boxed permission to violate one policy or invariant | `reason`, `requested_by`, `approved_by`, **`expires_at`** (DateTime), `subject_scope` | `waived_policy` **xor** `waived_invariant` (target); `subject_intent` / `subject_contract` / standalone `subject_scope` (subject) |
| `IntentGenericContract` / `...Policy` / `...Invariant` | nodes | Free-form starter implementations of the generics | — | inherited |

**Why generics?** Platform queries target the generic (`IntentContract`)
and automatically see every implementation — the free-form starters *and*
domain-typed kinds like `IntentRoutingContract`. Typed kinds encode their
terms as native attributes (PE/CE devices, prefix limits); free-form kinds
put every term in `IntentObjective.expression`. Both answer the same
queries.

## The correlation rules, as schema mechanics

1. **Contracts are owned.** `IntentContract.intent` is a `Parent`
   relationship (exactly one, required); `IntentDefinition.contracts` is a
   `Component` with `on_delete: cascade` — delete the intent and its
   contracts (and their objectives) go with it. An intent with zero
   contracts can never fail: creating one is a merge-check finding (check
   owed, see below).
2. **Policies and invariants are referenced, never owned.** Plain
   relationships, no cascade — deleting an intent never deletes a rule.
   Attachment is by `scope`: `global` (no links needed), `domain` (list the
   domains in `domains`), `intent` (link explicitly via `intents`).
3. **Waivers**: exactly one *target* (`waived_policy` xor
   `waived_invariant`), one *subject* (`subject_intent`, `subject_contract`
   — optionally narrowed by `subject_scope` — or `subject_scope` standing
   alone as a pure device/site scope), a named `requested_by` (the
   subject's owner), an `approved_by` (the target's owner — you don't waive
   your own rules for yourself), and a **hard `expires_at`** (DateTime).
   Consumers MUST check expiry before honoring a waiver; there is no stored
   active/expired status to go stale.
4. **Priority flows down only** (intent → contract → the plans touching its
   devices). No kind below the intent has a priority attribute — that is
   deliberate; do not add one.
5. **Traceability**: everything compiled cites its origin as
   `infrahub://Intent/<intent>/contract/<contract>` (built from `name`
   values — keep names stable; renames are migrations).
6. **Compliance rolls up the reverse of ownership**: verdict → objective →
   contract → intent, worst-of. Waived findings surface as `waived` — a
   third state that is never green and never red — until `expires_at` flips
   them back to findings.

## Recipes

### Create a complete intent (GraphQL, same pattern for any client)

Three **separate requests**, in order — GraphQL rejects multiple anonymous
operations in one document, and each step needs the `object.id` returned by
the previous one:

```graphql
mutation {
  IntentDefinitionCreate(data: {
    name: {value: "cust-c-l3vpn"},
    description: {value: "Customer C's three sites communicate privately over the MPLS core"},
    domain: {value: "connectivity"},
    owner: {value: "provider-edge-team"},
    priority: {value: "high"}
  }) { ok object { id } }
}
```

```graphql
mutation {
  IntentGenericContractCreate(data: {
    name: {value: "cust-c-sessions"},
    consumer: {value: "customer-c"},
    intent: {id: "<intent-id from step 1>"}
  }) { ok object { id } }
}
```

```graphql
mutation {
  IntentObjectiveCreate(data: {
    name: {value: "sessions-established"},
    expression: {value: "each site's PE-CE eBGP session is established"},
    contract: {id: "<contract-id from step 2>"}
  }) { ok }
}
```

Always author on a **branch** and open a proposed change — intent review is
the first approval plane; nothing here is exempt.

### Add a domain-typed contract kind

Create your kind in a new schema file, inherit the generic, encode terms
natively, and it automatically joins every platform query:

```yaml
nodes:
  - name: PeeringContract      # pick a name that does not collide with existing kinds
    namespace: Intent
    inherit_from:
      - IntentContract
    attributes:
      - name: max_prefixes
        kind: Number
        optional: true
    relationships:
      - name: peer_devices
        peer: DcimDevice        # adjust to your device kind
        cardinality: many
```

Migration notes (recorded in ADR-0015's consequences):

- The existing lab `IntentRoutingContract` predates this model and chains
  `contract → policy → intent` through a grouping node. It should gain
  `inherit_from: [IntentContract]` and a direct `intent` Parent link; the
  grouping hop then disappears (and the walk in
  `orchestrator/src/autonetops_orchestrator/priority.py` shortens by one
  level). Do **not** create a new kind named `RoutingContract` alongside the
  legacy one — migrate the legacy kind itself.
- Operational-policy kinds should join the same queries: `OpsChangeWindow`
  (in the SoT schema repo) gains `inherit_from: [IntentPolicy]` with
  `subject: operational`, so "what rules are in force" has one answer.
  Until then, operational-policy kinds live outside `IntentPolicy` queries.

### Add a domain

Set `domain: "your-domain"` on the intent. That's it — the taxonomy is a
free-form attribute precisely so this never needs a schema migration.
Starter set: `connectivity, routing, observability, security, resilience,
capacity, compliance, lifecycle, operations`.

### Write a waiver

Target the *rule*, subject the *promise*, and give it an expiry you can
defend in review:

```graphql
mutation {
  IntentWaiverCreate(data: {
    name: {value: "cust-c-site3-single-homed"},
    reason: {value: "second circuit on order, carrier ETA"},
    requested_by: {value: "provider-edge-team"},
    approved_by: {value: "resilience-team"},
    expires_at: {value: "2026-09-30T00:00:00Z"},
    waived_invariant: {id: "<customer-site-dual-homed-id>"},
    subject_contract: {id: "<cust-c-sessions-id>"},
    subject_scope: {value: "site-3"}
  }) { ok }
}
```

### Query patterns the platform uses

```graphql
# every contract of every kind, with its intent's priority (query the GENERIC)
query { IntentContract { edges { node {
  name { value }
  intent { node { name { value } priority { value } } }
}}}}

# rules in force for an intent = global + its domain + explicitly linked
query { IntentPolicy(enabled__value: true) { edges { node {
  name { value } scope { value } domains { value }
  intents { edges { node { name { value } } } }
}}}}

# waivers - expires_at is a DateTime, but honor/expire is decided
# IN THE CONSUMER (compare against now; no stored active/expired status)
query { IntentWaiver { edges { node {
  name { value } expires_at { value }
  waived_invariant { node { name { value } } }
  subject_contract { node { name { value } } }
}}}}
```

## Rules for humans and AI agents

When creating or editing objects in this model, apply these in order:

1. **Classify before you create.** Ask the three questions:
   *Who loses if it breaks?* → Contract. *Which actions/designs does it
   forbid or shape?* → Policy. *If false, is it an incident regardless of
   what changed?* → Invariant. If none fit, you are probably describing
   mechanism, not intent — stop; mechanism belongs in transforms/templates.
2. **Intent states WHY, never HOW.** No device names, no config stanzas, no
   protocol knobs in `IntentDefinition.description`. If deleting the
   sentence would only change how the network is built, it is not intent.
3. **Never create an intent without at least one contract**, and never a
   contract without an intent (the schema forbids the latter).
4. **Never put a priority anywhere except the intent.**
5. **Never create a waiver without `expires_at`**, never point it at a
   contract (targets are rules: policies/invariants), and never set
   `requested_by` and `approved_by` to the same owner.
6. **Prefer a waiver over `enabled: false`** — disabling a policy or
   invariant is fleet-wide and permanent-until-remembered; a waiver is
   scoped and expires.
7. **Reuse before creating**: query the generic first; a new policy that
   restates an existing one with different words is a review finding.
8. **Observability rides two patterns**: per-service observability terms are
   objectives inside the contracts of the intent they observe (see
   `cust-c-visibility` in the worked example in
   `docs/architecture/intent-model.md`); fleet-baseline observability
   (streaming coverage, freshness floors) is its own intent with
   `domain: observability`.
9. **Names are API**: lowercase-kebab, stable, meaningful — they become
   `derives_from` URIs, dashboards and audit trails.
10. **Everything through a branch + proposed change.** No direct-to-main
    mutations, human or agent.

## Constraints owed as checks (not yet machine-enforced)

The schema cannot express these; they belong in `infrahub/checks/` and are
review findings until those land:

- an `IntentDefinition` with zero contracts;
- an `IntentWaiver` with both or neither of `waived_policy` /
  `waived_invariant`, with no subject (no subject relationship **and** no
  `subject_scope`), or merged without `approved_by`;
- duplicate `IntentObjective` names within one contract, wherever the
  server-side uniqueness constraint is not enforced;
- `scope: domain` with an empty `domains` list, or `scope: intent` with no
  `intents` links;
- expired waivers still being honored (consumers must check `expires_at`).

## Status

The model is ADR-0015 (**proposed**) — field experience with these kinds is
exactly the feedback that ADR wants. `OpsPlanRecord` (the other file here)
is accepted and in production use by the orchestrator's feedback loop.
