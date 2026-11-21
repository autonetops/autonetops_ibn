# Extension checklists

Paths: `IBN/` = `autonetops_ibn`, `IH/` = `autonetops_infrahub`.

Everything is authored on a branch and merged through a Proposed Change, by people and agents
alike. Pick the narrowest change that does the job: data before attributes, attributes before
kinds, kinds before concepts.

Contents: A. new intent (data) · B. typed contract kind · C. typed invariant kind ·
D. network policy · E. operational policy · F. waiver · G. domain · H. new concept ·
I. review checklist

## A. New intent (data only, no schema change)

Derive the tree first (`SKILL.md` § 7). Then:

1. **Root fields**: `name` (per `naming.md`), `domain` (one value from the starter set),
   `owner`, `priority`, `tenant` (required for anything tenant-relative such as no-leak or
   prefix authorization), `ticket`. Use `critical` priority sparingly because it gates
   emergency eligibility.
2. **At least one contract**, each with its `intent` and a `consumer`. Typed kind when the
   terms render config or expectations; `IntentGenericContract` + `IntentObjective` nodes
   otherwise. Anchor contracts to SoT objects (devices, prefixes, zones), never to names typed
   as text.
3. **In force already.** Query `IntentPolicy` and `IntentInvariant`: which global and
   domain-scoped ones apply? Link intent-scoped ones explicitly. Create a new one only if none
   states the condition.
4. **Groups.** Add contracts to the target groups that `IH/.infrahub.yml` consumers read
   (`routing_contracts`, `observability_contracts`, `intent_tenants`, …). Without group
   membership no check or artifact runs for them, and nothing warns you.
5. Branch → Proposed Change → checks pass → artifacts render (config **and** expectations) →
   plan (`ibn-orchestrate plan`) → review the plan.

Fields, enum values and the SDK / GraphQL mechanics are in [primitives.md](primitives.md).

### Worked tree

Request: "Customer C's sites get private L3VPN connectivity, their apps stay reachable from
EMEA corp, and nothing of theirs ever reaches a public peer." Condensed shape, not a load
format. Names and values are the seed's; the slicing follows the model (the seed splits this
into several intents, see [status.md](status.md)). The waiver is illustrative.

```yaml
intent:
  name: custc-l3vpn-connectivity
  domain: connectivity
  description: >-
    Customer C sites exchange routes privately over our L3VPN; only authorized
    prefixes are announced and they never reach a public peer.
  owner: customer-success-emea
  priority: high
  tenant: customer-c

contracts:                                   # ACHIEVED BY (owned)
  - kind: IntentRoutingContract              # compiles config + expectations
    name: custc-ce-to-pe
    consumer: customer-c
    role: customer_edge
    peer_asn: 65123
    afi_safis: [ipv4-unicast, ipv6-unicast]
    max_prefixes_ipv4: 200
    zone: corp-emea
    pe_devices: [pe-emea-01, pe-emea-02]
    ce_devices: [ce-custc-01, ce-custc-02]
    allowed_prefixes: [10.84.0.0/16, 2001:db8:84::/48]
    export_deny_zones: [internet-peers, transit]
  - kind: IntentReachabilityContract         # compiles nothing yet
    name: custc-apps-reachable-from-emea-corp
    consumer: customer-c
    from_zone: corp-emea
    to_prefixes: [10.84.0.0/16]
    max_convergence_seconds: 30
  - kind: IntentReliabilityContract          # compiles nothing yet
    name: custc-reliability
    consumer: customer-c
    min_pe_attachments: 2
  - kind: IntentObservabilityContract        # compiles collectors + alert rules
    name: custc-service-signals
    consumer: noc-emea                       # another consumer, same intent
    signals:
      - name: custc-bgp-session-state
        signal: bgp_session_state
        condition: "down_for > 60s"
        severity: sev2
        watches: custc-ce-to-pe

in_force_already:                            # GOVERNED BY / GUARANTEED BY, nothing to author
  - ebgp-max-prefix-required                 # network policy, scope: domain
  - emea-standard-maintenance                # OpsChangeWindow
  - fleet-oob-cabled                         # invariant, scope: global

linked_invariants:                           # scope: intent
  - {kind: IntentNoLeakInvariant, name: custc-no-leak, severity: critical}
  - {kind: IntentPrefixAuthorizationInvariant, name: custc-prefix-authorization, severity: major}
  - {kind: IntentRedundancyInvariant, name: custc-redundancy-floor, severity: major}

waivers:                                     # TEMPERED BY
  - name: custc-site2-single-homed
    waived_invariant: custc-redundancy-floor
    subject_contract: custc-ce-to-pe
    subject_scope: emea-pop-b
    reason: second circuit on order; removed when the carrier delivers
    requested_by: customer-success-emea      # the subject's owner
    approved_by: backbone-engineering        # the target's owner, a different party
    expires_at: 2027-01-31T00:00:00Z

not_authored:                                # derived or fact
  - BGP sessions                             # derived from the contract + cabling
  - VRF CUSTC-PROD, RD/RT, prefixes          # IPAM facts
  - device config, expectations              # compiled
```

## B. New typed contract kind

1. Confirm no existing kind fits with an extra attribute. ADR first if the kind introduces a
   new artifact class. The engine reads `IntentRoutingContract` only (step 9). ADR-0016
   § 13.1 defers the general fix, a contract-compilation registry, to its own ADR, and a
   second contract kind that must gate a stage is its trigger.
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
9. Engine: `IBN/orchestrator/src/autonetops_orchestrator/priority.py` (plans touching this
   kind's devices inherit the intent's priority) and `render_source.py` (its expectations
   reach the stage gate). Both read routing contracts only today.
10. Signals that `watch` it, where it should page.
11. Golden tests: intent → rendered output per platform. Golden diffs are acknowledged in
    review, never regenerated blindly. No harness exists yet, so the first kind to need one
    builds it.

## C. New typed invariant kind

1. Confirm it is an invariant: false = incident regardless of what changed, and it can become
   false without an SoT change. A pure design rule is a network policy (D).
2. Schema: a node `Intent<Condition>Invariant` with `inherit_from: [IntentInvariant]`,
   `generate_profile: false`. Description phrased "X must / never Y". Give it the typed
   attributes that parameterize the condition (which zones, which floor, which capability),
   so one authored value tunes every surface.
3. Decide `severity`: `critical` (projection blocks, live violation pages), `major`
   (projection blocks), `warning` (reports only). In the check that is `log_error` for the
   first two and `log_info` for `warning`.
4. Decide `scope`. Prefer `global` or `domain` over one copy per tenant; per-subject
   differences are what waivers and typed attributes are for.
5. **Merge projection**: `IH/queries/<snake>.gql` + `IH/checks/invariant_<type>.py`
   (`<Camel>Check(InfrahubCheck)`):
   - resolve applicability across all three scopes (global, domain, linked), not just
     `intent → invariants`, and skip an invariant with `enabled: false`;
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
   Promote to a typed kind inheriting `IntentPolicy` when it needs parameters.
3. Write the `description` so a reviewer could apply it without asking.
4. **Land the check in the same change**: `IH/checks/policy_<requirement>.py`, registered in
   `IH/.infrahub.yml`. Same loud-failure behavior as invariant checks (vacuous, unverifiable,
   waiver-aware).
5. `scope: domain` needs a non-empty `domains`; `scope: intent` needs at least one link. A
   scope that matches nothing makes the policy vacuous.

## E. Operational policy

Dividing rule (ADR-0016): if the engine reads it to shape or gate a plan, it is pack data;
if it says when the network may change, it is SoT data.

- **Change windows and freezes** → `OpsChangeWindow` in the SoT (`IH/schemas/operations.yml`),
  `subject: operational`. Recurring (days + `start_utc` + `duration_minutes`) or absolute
  (`starts_at` / `ends_at`). Empty device scope means every device.
- **Blast-radius thresholds, canary strategies, change classes, approval floors, delivery
  preferences, rate limits, platform → driver bindings** → the policy pack
  (`IBN_POLICIES_DIR`; reference pack in `IBN/planner/policies/`, baseline in
  `IBN/planner/src/autonetops_planner/packs/baseline/`). Validate with
  `autonetops-planner validate-pack <pack dir>`.
- A new change class ships a `.match.yaml` **and** a `.refuse.yaml` golden fixture, or it is
  invalid.
- The profile parameterizes the engine's decision points; it never adds one. A need no pack
  section can express is an engine ADR.
- Never as code constants, and never as CLI flags that silently override reviewed data.
- `IBN/planner/policies/change_windows.yaml` is a retired pointer. Windows are SoT data.

## F. Waiver

1. Target a **policy or an invariant** (`waived_policy` xor `waived_invariant`), never a
   contract. Only SoT objects can be targeted: pack policy (canary strategies, change classes,
   approval floors, delivery preferences) can't be waived, by decision (ADR-0016 § 13.11).
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
mechanism (`collection` is a mechanism). Add it to the starter table in
`IBN/docs/architecture/intent-model.md` and to the `domain` row in
[primitives.md](primitives.md), so `scope: domain` policies and invariants can target it.

## H. New concept (rare)

A new word in the vocabulary (a fifth instrument, a new derived or observed term, a new
enforcement point) is an ADR superseding or extending 0015, plus updates to
`intent-model.md`, the schema README and this skill in the same change. Check
[use-case-patterns.md](use-case-patterns.md) first: its "concept gaps" list records the
candidates already identified, so extend that discussion instead of starting a parallel one.

## I. Review checklist

Red flags in a change that touches intent:

- Intent named after a mechanism or vendor (`custc-bgp-config`, `eos-acl`), or with zero contracts.
- Intents split per domain for one outcome with the same owner and priority.
- A per-tenant copy of an invariant or policy that could be one with `scope: domain`.
- A network policy with no merge check; an invariant with neither projection nor expectation.
- Config artifact without a sibling expectation; artifact or verdict without the trace metadata.
- `Text` where a relationship or `Dropdown` fits; thresholds hardcoded in a check or transform.
- Vendor conditionals in intent logic; a mechanism knob stored as a SoT fact and edited by hand.
- Priority anywhere but the intent; windows, canary strategies or approval bars as code or CLI flags.
- `enabled: false` or an un-expiring exception where a scoped waiver belongs; a waiver aimed at a contract; `requested_by == approved_by`.
- Missing or stale evidence counted as pass.
- Rejected words used for authored intent: "rule", "SLA", "constraint", "exception", "realm", "suspended".
