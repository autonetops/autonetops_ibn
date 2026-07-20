# 0017 — Vocabulary alignment with the lab's workshop ontology

- Status: proposed
- Date: 2026-07-19

## Context

The companion SoT repo's Workshop 2 ("Intent-Based Networking: the theory,
the operation, the road to scale") defines its own intent ontology — realm,
intent, policy, contract, invariant, expectation, tenant, zone, capability —
anchored to the lab's InfraHub kinds (`IntentRealm`, `IntentIntent`,
`IntentPolicy`-as-bundle, per-realm contract subtypes, `IntentInvariant`
with `invariant_type`/`blocking|warning`). It is a strong document: its
control loop, design laws, adoption stages and enforcement machinery
describe *this* platform accurately, and roughly 80% of its vocabulary is
ours under different section headings.

The remaining 20% conflicts, and both repos are being opened to external
adopters who will build on these words (ADR-0015's own warning). Two
ontologies for one platform is how every integration meeting starts with
ten minutes of disambiguation. This ADR records the negotiated common
ground: what each side adopts, what each side renames, and why — term by
term, best option winning, tie broken by which definition preserves an
enforcement distinction the other erases.

## Decision

### D1. "Policy" stays a rule instrument; the HOW-bundle flattens

The deepest conflict. The workshop defines **policy** as *how an intent is
realized*: a named bundle of contracts plus the invariants guarding them,
"the swap point" between WHAT and HOW. ADR-0015 defines **policy** as a
*standing rule constraining how outcomes may be realized* (network or
operational subject) — and explicitly flattened the lab's
contract → policy → intent chain, freeing the word for rule instruments.

ADR-0015's meaning wins, for the reason it already recorded: the
policy/invariant distinction decides the *enforcement point* (refuse the
action vs detect the state), and that is the most operationally useful
thing the vocabulary does. "Policy" as a bundle erases it, and collides
with the industry's own usage (admission policy, change-management policy)
that operational policies deliberately borrow.

What the workshop's bundle actually provides is answered without it:

- *The swap point.* Contracts **are** the realization. Swapping HOW —
  different attachment design, protocol, vendor approach — is retiring
  contracts and attaching new ones under the same intent; the intent
  (WHAT) does not move, which is the property the workshop wanted from
  the bundle. If a named grouping of contracts ever proves necessary,
  it gets a new word (working name: *realization*) and its own ADR —
  it will not be "policy".
- *The `enforcement: design_time | runtime | full` field.* Derived, not
  authored: invariants gate merges (their design-time projections),
  contracts are watched at runtime (their compiled expectations), and
  the enforcement matrix in `intent-model.md` states where every
  instrument bites. An authored field can contradict the attached
  instruments; a derived fact cannot. The field is dropped.

Owed on the lab side (already recorded in ADR-0015's consequences, now
made concrete): contracts link straight to their intent;
`IntentRoutingContract` gains `inherit_from: [IntentContract]`; the
grouping `IntentPolicy` kind retires; rule-shaped policy content
(no-Friday-changes, max-prefix-required) becomes `IntentPolicy` rule
instruments per `infrahub/schemas/intent_model.yml`.

### D2. Realm folds into `domain` — attribute, not node kind

The workshop's **realm** (`IntentRealm`, a node kind: routing,
reachability, security, observability, reliability, compliance,
performance) and our **domain** (a free-form attribute on the Intent,
ADR-0015 decision 3) are the same concept. The attribute form wins: the
taxonomy must grow without a schema migration, and nothing a realm node
provides — per-realm contract subtypes, per-realm invariant kinds —
actually requires a node (typed kinds inherit the generics regardless of
what tag the parent intent carries).

Domain *values* are customer data (each tenant's Infrahub carries its own
taxonomy — exactly the ADR-0016 posture), so both starter sets are legal.
The recommended mapping, so the two repos read as one:

| Workshop realm | This repo's domain | Note |
|---|---|---|
| `routing` | `routing` | identical |
| `security` | `security` | identical |
| `observability` | `observability` | identical |
| `compliance` | `compliance` | identical |
| `reliability` | `resilience` | one word chosen; `resilience` says the property, not the wish |
| `performance` | `capacity` | ours covers utilization ceilings, latency budgets, QoS promises |
| `reachability` | *(not a domain)* | an **objective kind** inside contracts (ADR-0015 decision 3): promoting it scatters one intent's terms across two intents |

### D3. Invariants: one authored object, two enforcement surfaces

The workshop restricts **invariant** to the merge surface ("compiled into
a merge-gating check", evaluated over the SoT graph on every Proposed
Change) and gives the runtime surface entirely to expectations. ADR-0015
defines the invariant as a **condition on network state evaluated
continuously**, with merge-time *projections* as a derived, second
surface.

ADR-0015's framing subsumes the workshop's, and the workshop's own
example proves it needs to: `no_leak` is violated the moment customer
routes reach the peering zone — an incident *regardless of what merged
recently* — which is precisely the classifying question that makes it an
invariant. The workshop already compiles the runtime half ("forbidden
exports absent") as an expectation; under the common vocabulary that
expectation **derives from the invariant**, not from a contract, so the
finding cites the right authority. The workshop's excellent
invariant-vs-expectation table stays true with one relabel: its left
column is the invariant's *merge-time projection*; its right column is
compiled expectations (from contracts *and* invariants).

Adopted from the workshop in return: **`invariant_type` as typed kinds.**
`no_leak`, `prefix_authorization`, `redundancy`, `capability_present`,
`oob_reachability`, … become domain-typed kinds inheriting
`IntentInvariant` — exactly the generics pattern contracts already use,
and better than a free enum on the generic (each type carries its own
natural attributes: which zones, which floor, which capability).

### D4. Severity: `warning | major | critical`; "blocking" is a check property

The workshop's invariant severity is `blocking | warning` — an
*enforcement consequence*. Ours is `warning | major | critical` — *what a
violation is worth when it happens*. Ours wins because one invariant has
two enforcement surfaces (D3) and "blocking" only describes one of them:
a continuous evaluation cannot "block", it pages. Whether a merge-time
projection blocks or reports is a property of the **check**, derived from
severity: `critical` and `major` projections block, `warning` projections
report. The workshop's two values map losslessly: `blocking → major` (or
`critical` where an incident would page), `warning → warning`.

### D5. Tenant, Zone, Capability adopted as the supporting vocabulary

The workshop's WHO / WHERE / WITH-WHAT kinds are adopted into
`intent-model.md` as *recommended supporting kinds* of a customer intent
layer:

- **Tenant** — WHO an intent serves, as a first-class kind. Our
  contracts already carry `consumer`; a tenant kind is the structured
  form, and tenant-relative invariants (no-leak, prefix authorization)
  are meaningless without it.
- **Zone** — WHERE, as a named region contracts can reference without
  enumerating devices.
- **Capability** — WITH WHAT each platform can participate: the
  switchboard between intent and mechanism. This is the SoT-side data
  ADR-0011/0012 have been waiting on: collectors selected off it,
  renderer arms gated on it, `capability_present` invariants checking
  it, and — when capability records land — the planner's protocol
  selection and the executor's driver resolution reading it instead of
  the interim pack `platforms:` bindings (the ADR-0016 deferral keeps
  its trigger).

All three are **controlled vocabularies**, never free text — adopted as
stated, it is the same law as ours ("machines branch on these values;
free text is undefined behavior").

### D6. Expectation discipline adopted verbatim

Four rules from the workshop join the Expectation entry in
`intent-model.md`, because they are the difference between expectations
that prove and expectations that spam:

1. **Ranges, never exact values** (`route_count <= 200`, not `== 173`).
2. **Forbidden behavior is stated explicitly** — you cannot prove a
   negative you never wrote down.
3. **The collector is derived from capability, never chosen by hand**
   (`observedVia: gnmi` because the platform claims `gnmi`).
4. **Freshness is part of the proof** — stale evidence is no evidence;
   a dead collector reads as *unknown*, never as *fine*.

### D7. The three axes table adopted

Priority (on the intent: business importance, flows down), severity (on
the invariant/signal: cost of a violation), blast radius (on the plan:
size of a change; on the window: a ceiling) — three questions, three
objects, never conflated. The workshop states it best; `intent-model.md`
gains the table with our vocabularies in the cells.

### D8. Small alignments, both directions

- **Intent fields**: `statement` ≈ our `description` (keep `description`;
  the workshop's "one human sentence" guidance is good practice, not a
  schema change). `ticket` (provenance link) is a harmless, useful
  addition — recorded as a candidate attribute for the next
  `intent_model.yml` revision, not added silently.
- **Intent status**: the workshop's `suspended` is an un-expiring
  off-switch — the exact failure mode ADR-0015 built **waivers** to
  prevent. Recommended mapping: suspend an intent's enforcement with a
  time-boxed waiver on its instruments (or `deprecated` when it is
  really on the way out); no `suspended` status.
- **Waivers and Objectives** exist only on our side; the workshop should
  adopt both (its blocking no-leak/redundancy gates need waivers, or
  every sanctioned exception becomes an unmergeable branch or an eternal
  red light).
- **Kind naming**: `IntentIntent` stutters; `IntentDefinition` (namespace
  `Intent`, name `Definition`) is the recorded form.
- **Workshop cheat sheet**: dispatch exits `4` for missing approvals
  (`3` for waiting on a window) — the table showing approvals under
  exit `2` predates ADR-0014's watch-hold semantics.

## Consequences

- `docs/architecture/intent-model.md` gains: the supporting vocabulary
  (tenant/zone/capability), the expectation discipline, the three-axes
  table, and the realm→domain mapping in the Domains section. No
  definition from ADR-0015 changes — this ADR adds and maps, it does not
  supersede.
- `infrahub/schemas/intent_model.yml` owes (next revision, reviewed):
  typed invariant starter kinds (D3) and the `ticket` attribute (D8);
  nothing lands silently with this ADR.
- The lab/workshop side owes: the policy-level flattening and
  `inherit_from` migrations (D1, already owed by ADR-0015), severity
  remap (D4), realm-kind retirement in favor of the domain attribute
  (D2), waiver + objective adoption and the exit-code correction (D8).
- ADR-0016 is unaffected: everything here is intent-plane vocabulary
  (the customer's Infrahub surface); the pack contract and the engine's
  closed vocabularies do not change.
- The enforcement matrix remains the single answer to "where does each
  word bite" — the workshop's tables are views of it, and any future
  divergence between the two repos' vocabularies is a review finding
  against this ADR.
