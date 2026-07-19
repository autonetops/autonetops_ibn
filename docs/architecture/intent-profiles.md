# Intent profiles: how a customer defines their intent layer

This document is for a new customer's network-automation team and the
platform engineers onboarding them. It explains where each part of a
customer's intent layer is authored, what a policy pack is, how the pack
binds to the engine at plan time and dispatch time, and — the part that
matters most — what no pack can ever express. The vocabulary is
ADR-0015's, modeled in full in `intent-model.md`; the decision this
document walks through is ADR-0016; the auto-approval machinery it
extends is ADR-0014.

## 1. The contract, in one sentence

A customer's intent layer is **their Infrahub SoT** (intents and
instruments as typed kinds inheriting the `Intent*` generics) plus **one
policy pack** (a directory containing `profile.yaml`, pointed at by the
existing `IBN_POLICIES_DIR`, living in the customer's SoT repo under
CODEOWNERS); the planner and orchestrator remain one engine that loads
exactly one resolved pack per run, records its identity in every Plan,
and at dispatch re-derives every authorization under the *current* pack
with tighten-only semantics on top of a hard-coded safety floor no pack
can express.

Everything below unpacks that sentence.

## 2. Two authoring surfaces

| Surface | Contains | Reviewed by | Why there |
|---|---|---|---|
| **Customer's Infrahub SoT** | `IntentDefinition` roots; typed **contracts** (`inherit_from: [IntentContract]`); **network-subject policies** and **invariants** (typed kinds inheriting `IntentPolicy`/`IntentInvariant`); **waivers**; `OpsChangeWindow` (operational policy that is *scheduling data*, ADR-0013); devices and control points | intent owners, via branches + proposed changes + `infrahub/checks/` | intent-plane data; the generics keep platform queries customer-agnostic |
| **Policy pack** (`IBN_POLICIES_DIR`) | Operational policies the engine consumes at decision time: `profile.yaml` (identity + bindings + thresholds + floors), `canary_strategies.yaml`, `change_classes.yaml`, `delivery_preferences.yaml`, `rate_limits.yaml`, golden test fixtures | rollout approvers, via pack CODEOWNERS in the customer's SoT repo | must be file-versioned, checksummable, and identical at plan and dispatch (ADR-0014 same-source discipline) |

**The dividing rule (normative):** if the engine reads it to shape or
gate a Plan, it is pack data; if it describes the network or when the
network may change, it is SoT data. `OpsChangeWindow` stays in the SoT
because a window is *when the network may change*; thresholds, floors
and change classes are pack data because the engine reads them to shape
and gate Plans. (The owed `inherit_from: [IntentPolicy]` migration for
`OpsChangeWindow` is recorded in `infrahub/schemas/README.md` — the kind
is provisioned into customer Infrahub instances, not defined in this
repo.)

## 3. How the instruments bind, per customer

ADR-0015 defines the instrument kinds; this matrix is where each one
lives and bites in a customer deployment:

| Instrument (ADR-0015) | Authored as | Binds at | Engine mechanism |
|---|---|---|---|
| Contract | SoT typed kind ← `IntentContract` | stage gates + continuous | compiled to `ContractExpectations`, frozen into the bundle, evaluated by the validator (`validator.expectations_pass`) |
| Policy, subject=network | SoT typed kind ← `IntentPolicy` | intent merge time | `infrahub/checks/policy_*` merge gates in *their* Infrahub |
| Policy, subject=operational, timing | SoT `OpsChangeWindow` | timeline + re-checked live at dispatch | `orchestrator/windows.py` |
| Policy, subject=operational, rollout-shaping | **pack files** (strategies, classes, delivery, thresholds, floors, bindings, limits) | plan compile + dispatch re-verification | `load_profile()` → planner pipeline; ADR-0014 re-derivation |
| Invariant | SoT typed kind ← `IntentInvariant` | merge-time projections + continuous | `infrahub/checks/invariant_*` in *their* Infrahub; validator |
| Waiver | SoT `IntentWaiver` | wherever its target bites | consumers compare `expires_at` to now (waiver-aware *planning* is deferred, §9) |
| Priority | `IntentDefinition.priority` only | decision time | `orchestrator/priority.py` → emergency eligibility |

How a customer adds an operational-policy kind without engine changes:
they may create any SoT kind inheriting `IntentPolicy` — it is
queryable, reviewable and waivable like any instrument — but it becomes
*executable* only by mapping onto one of the engine's fixed decision
points — classify, match, stage, approve, deliver, schedule, abort,
admit — via the pack sections that parameterize them. **The profile
parameterizes decision points; it never adds them.** A need no pack
section can express is an engine ADR, never a fork.

### Fixed vocabulary vs customer-extensible

**Mandatory (the conformance floor, checked by `validate-pack` and
Infrahub checks):** typed intent kinds MUST inherit the generics — a
non-inheriting kind is invisible to the engine, by design. Every
contract has exactly one parent intent; every compiled check cites
`derives_from: infrahub://...`. Every pack in profile mode has a valid
`profile.yaml`; strategies cover all three blast classes; every HIGH
path has a named human (floor F9). Priority lives only on
`IntentDefinition`; compliance rolls up worst-of; waivers have hard
expiry.

**Extensible without engine changes:** any number of typed
contract/policy/invariant kinds; any pack content within the schema —
own strategies (from the closed selector set), own change classes (with
mandatory golden tests), thresholds, floors, platform/artifact/rollback
bindings, abort criteria, approver names, `sot:` paths, windows,
waivers, domain taxonomy.

**Explicitly NOT extensible (engine release + ADR required):** the
canary selector vocabulary, `Gate.kind` values, change-class
content-format matchers, the `ContentFormat` / `ControlPointKind` /
`BlastRadiusClass` enums, executor verbs, rollback well-known names,
and the enforcement points themselves. A pack naming an unknown value
fails at **pack load**, never at plan build. A customer cannot add a
new *kind of decision*; they can only parameterize the decisions the
engine makes.

## 4. The pack, walked through

A pack is any directory containing `profile.yaml`. No registry, no new
artifact type, no new env var: `IBN_POLICIES_DIR` points at the pack
root, exactly as it points at `planner/policies/` today. The builtin
defaults are themselves a pack shipped inside the planner wheel,
addressable as `builtin:baseline` — so provenance is never blank, even
with no policies dir at all.

### The example: customer "Meridian"

60 devices, region = DC hall, SoT spells platforms `"Juniper JunOS"`,
artifact definition named `device-config`:

```yaml
# contracts/profile/v1 — customer "Meridian": 60 devices, region = DC hall,
# SoT spells platforms "Juniper JunOS", artifact definition is "device-config".
profile_version: 1                    # file-format contract (const, like Plan contract_version)
meta:
  tenant: meridian                    # tenant identity; immutable for the pack's life
  name: meridian-production
  version: "1.4.0"                    # customer-authored semver, bumped under review
  conformance: full                   # baseline | tuned | full (see below)
  owner: neteng-rollout@meridian.example
  description: Meridian production risk posture, JunOS/IOS-XE estate.
extends: builtin:baseline             # or null (from scratch; every mandatory section required)
requires_planner: ">=0.1,<0.2"        # PEP 440 pin on engine __version__; checked at load AND dispatch

sot:
  intent_model_version: "1.0"         # which intent_model.yml generics version their schema implements
  default_base_branch: main
  device_kind: DcimGenericDevice      # inline-fragment target of the artifact query
  role_path: role__value              # attribute traversal:      role { value }
  platform_path: platform__node__name__value   # relationship traversal
  region_path: site__node__region__value       # declaring it populates region in blast radius

blast_radius:                         # review-plane section: file-only, wholesale replacement
  thresholds:
    low_max_devices: 5                # Meridian's "low" is bigger than the lab's
    high_min_devices: 25
    high_min_regions: 2               # region := DC hall
  # class names/ordering low<moderate<high are engine-fixed (floor F13); ladder order validated

approvals:                            # review-plane section: file-only, union/tighten-only merge
  floors:                             # WHO must approve per blast class — floor, never ceiling
    low: []
    moderate: [meridian-netops]
    high: [meridian-netops, meridian-change-board]

platforms:                            # per-key merge over baseline; keys EXACTLY as their SoT spells them
  "Juniper JunOS": { driver: junos, rollback: commit_confirmed }
  "Cisco IOS-XE":  { driver: iosxe, rollback: manual }   # explicit, reviewed pin (floor F10)
  # platform seen in a diff but unbound here => plan-time error (never a guessed driver)

artifacts:                            # wholesale section replacement (no per-key merge)
  definitions:
    device-config:   { content_format: cli-text }
    wan-openconfig:  { content_format: openconfig-json }
  # definition seen in a diff but absent here => plan-time error, never assumed cli-text

rollback:
  confirm_timeout_minutes: 15

abort_criteria:                       # replaces the baseline's abort criteria wholesale
  - validator gate fails on any canary stage
  - any step rollback is triggered
  - manual abort by Meridian NOC

files:                                # which sibling files this pack provides; listed => MUST exist and validate
  canary_strategies: canary_strategies.yaml
  change_classes: change_classes.yaml
  rate_limits: rate_limits.yaml       # validated; Plan still reports rate_limits: "not_evaluated"
```

A minimal customer is complete and valid at `conformance: baseline` in
about ten lines: `profile_version`, `meta` (tenant/name/version),
`extends: builtin:baseline`, `blast_radius.thresholds`,
`abort_criteria`. Everything else inherits.

### Directory layout

```
customer-sot-repo/policy-pack/           # IBN_POLICIES_DIR=/data/sot-repo/policy-pack
├── profile.yaml
├── canary_strategies.yaml               # today's shape, now pydantic-validated
├── change_classes.yaml                  # ADR-0014 shape, unchanged
├── delivery_preferences.yaml            # optional; omitted = inherit baseline
├── rate_limits.yaml                     # optional; validated, engine-ignored (honest)
├── tests/change_classes/
│   ├── interface-descriptions.match.yaml    # {artifact_definition, content_format, before, after}
│   └── interface-descriptions.refuse.yaml
└── CODEOWNERS                           # rollout approvers own this directory
```

The pack lives inside the customer's SoT repo, cloned by the existing
`sotRepo.gitUrl` init container: pack changes ride the customer's
existing repo review (CODEOWNERS on `policy-pack/` is ADR-0014's
"editing is the approval act", per customer), and plan time and dispatch
time read the same checkout. No second clone container.

### Layering and merge semantics

Exactly two layers: `builtin:baseline` ← customer pack. `extends: null`
opts out, and then every mandatory section must be present. No chains,
no relative-path parents, no tombstones. The loader enforces:

| Content | Rule |
|---|---|
| Scalar/mapping sections: `blast_radius`, `artifacts`, `rollback`, `sot`, `abort_criteria` (list) | **wholesale section replacement** — a section present in the child replaces the parent's entirely; omitted = inherited. Auditable by reading one file. |
| `platforms`, `delivery_preferences` per-platform entries | **per-key merge**; a child key replaces the whole parent entry, never field-merges |
| `canary_strategies` `strategies[]` | merge **by `name`**: same name = full replacement (a half-merged strategy is a safety hazard); new names add; `enabled: false` removes an inherited strategy |
| `approvals.floors` | **union only** — a child adds approvers, never removes a parent's; `null` illegal on any safety field. A lower bar than baseline is unrepresentable, not merely invalid. |
| `change_classes` | **no layering, ever.** Baseline ships zero classes (CI-pinned); the customer file is the sole source. Auto-approval authority can never originate from the platform. |

### Conformance levels

`meta.conformance: baseline | tuned | full` (default `tuned`); a pack
may not use sections above its declared level. `baseline` allows
`meta`/`extends`/`blast_radius`/`abort_criteria` only; `tuned` adds
`approvals`, `platforms`, `artifacts`, `rollback`, `files`; `full` adds
`sot` overrides beyond `default_base_branch`. The point is that a
"small" customer's pack cannot silently grow unreviewed surface — using
a new section is a visible, reviewed level bump.

### The three identity numbers

Never conflated:

1. `profile_version: 1` — the file-format contract, like the Plan's
   `contract_version`. Changing it requires `contracts/profile/v2/` and
   an ADR.
2. `meta.version` — the pack's content semver, authored by the
   customer, bumped under review.
3. **The checksum** — never authored. The loader computes
   `sha256` over the *fully resolved* profile (post-`extends`,
   post-merge, change classes parsed in) serialized as canonical JSON.
   Identity from bytes, not claims; formatting-insensitive; the value
   every Plan records and dispatch compares.

## 5. Validation: `validate-pack`

`autonetops-planner validate-pack <dir> [--infrahub-url U
--infrahub-token T]` is the pack contract's teeth — the `policy-validate`
CI job, run in the customer's pack CI and in platform CI against
`builtin:baseline` and `planner/policies/`. The pydantic models are
canonical (`extra="forbid"` everywhere); `export-schema --contract
profile` emits `contracts/profile/v1/profile.schema.json`,
drift-checked exactly like Plan v1. Gates, in order, all fatal:

1. `profile.yaml` parses and validates; `requires_planner` satisfiable;
   `extends` resolves (only `builtin:baseline` or `null`); the
   conformance level is respected.
2. Every file listed under `files:` exists and validates against its
   model; unknown keys are errors (this kills the `applies_to_blast:`
   typo class).
3. Closed-vocabulary membership: every `stage.select` is one of
   `one_target | one_per_role | remainder`; every `stage.gate` is a
   `Gate.kind` value; every blast-class reference is valid; every
   `rollback` is an engine rollback strategy; every delivery protocol
   is engine vocabulary; every regex compiles; `low_max_devices <
   high_min_devices` (the ladder validator — a profile cannot invert
   the ladder). F10 holds by construction: there is no global protocol
   order — `cli` is only ever reachable through an explicit,
   per-platform preference list in a reviewed pack file.
4. Cross-references: every `class.canary_strategy` names a resolved
   strategy; resolved strategies cover all three blast classes (what is
   a `LookupError` at plan time today becomes a load-time error); and
   **F9**: every HIGH-applicable strategy has non-empty effective
   approvals (`requires_approvals` united with `floors.high`) unless
   HIGH auto-execution is reachable only via a reviewed change class
   with `max_blast_radius: high` — itself golden-test-guarded and
   customer-authored, since baseline ships none.
5. **Golden change-class fixtures, mandatory:** each enabled change
   class must have `tests/change_classes/<name>.match.*` and
   `<name>.refuse.*` fixtures, and `classify_changes` must match and
   refuse them respectively. A class without both fixtures is invalid —
   an error, not a warning. The auto-approval surface is the one place
   a warning is insufficient.
6. With `--infrahub-url` (advisory in pack CI, mandatory at onboarding,
   re-runnable on demand): `sot.device_kind` is queryable with the
   declared paths, and every `artifacts.definitions` key exists as a
   CoreArtifact definition. Drift is a reported finding, never a silent
   divergence. (Checking that the `Intent*` generics of
   `sot.intent_model_version` are loaded and every typed kind inherits
   one is part of the onboarding checklist; automating it into this
   gate is owed.)

## 6. Execution-layer binding

### At plan time

The orchestrator's build phase calls `load_profile(IBN_POLICIES_DIR)`
once and passes the one resolved profile through the whole pipeline:

- blast radius is computed under the pack's thresholds; `region` is
  populated when `sot.region_path` is declared;
- drivers and rollback come from `platforms:` bindings — an unbound
  platform is a plan-time error, never a guessed driver;
- artifact formats come from `artifacts.definitions` — an unknown
  definition is a plan-time error, never an assumed cli-text;
- **effective stage approvals** = the strategy's `requires_approvals`
  united with `floors[classification]`, written into the plan;
- the plan records `policy_evaluation.profile: ProfileRef`
  (tenant, name, version, checksum, source) and the bundle gains
  `plans/<id>/profile.lock.yaml` — the full resolved profile, frozen
  for audit and re-derivation, **never authority**;
- `deterministic_id` still hashes only `source + stages`: same diff,
  same id, regardless of pack version. Provenance is metadata, not
  identity;
- the SoT `OpsPlanRecord` carries
  `profile_name`/`profile_version`/`profile_checksum`, so "which policy
  version produced every change last quarter" is a SoT query.

### At dispatch: tighten-only, always

Dispatch loads the *current* pack from the same `IBN_POLICIES_DIR`
(ADR-0014's same-source discipline, unchanged). Frozen bundle bytes are
testimony; the current pack is judge; verdicts only tighten:

| Check | Rule |
|---|---|
| Pre-approval | re-classified from frozen `content_base/` + `content/` bytes under the **current** pack's change classes; a class disabled, removed or tightened retroactively kills auto-approval for already-planned bundles |
| Approval bar | floor = union(frozen plan's effective approvals, current pack's strategy-by-name approvals, current floors for the effective blast class); a vanished strategy injects `UNVERIFIABLE`, but the floors provide a bar even then |
| Blast radius | re-classified from the frozen plan's recorded device/region counts under **current** thresholds; effective class = max(pinned, recomputed) — the pinned class is a floor, never a ceiling |
| Profile drift | checksum mismatch between the recorded `ProfileRef` and the current pack is **recorded** (`profile_drift` in `evidence.jsonl` + decision reasons) and dispatch proceeds — the rows above already re-prove everything that matters under the current pack |
| Bad profile | profile invalid or missing where the plan records one, tenant mismatch, or `requires_planner` unsatisfied → `UNVERIFIABLE` on all pre-approval claims and a fail-closed approval hold (exit 4); never a silent baseline fallback |
| Tenant guard | with `IBN_TENANT` set, load refuses a profile whose `meta.tenant` differs and dispatch refuses a bundle whose recorded tenant differs — cross-tenant bundle replay is a loud failure |

Two things never happen at dispatch: frozen choreography is never
rewritten (stages, soak, selectors, gates, drivers, protocols and
rollback specs are spent at plan time — a pack that would shape them
differently gets a superseding Plan, surfaced via the drift record),
and windows are never read from the lock (they come **live from the
SoT**, so a freeze created after planning MUST bite; SoT unreachable
means wait). The executor and validator are byte-for-byte unchanged;
the profile never crosses the executor boundary.

## 7. The safety floor: what no profile can express

Fifteen rules, engine code with tests, reachable by no `profile.yaml`
field. Every one is a sentence a customer can be given verbatim:

- **F1** Removals never auto-deploy — removed targets are reporting,
  never steps; removals veto pre-approval; decommission is always an
  explicit human decision.
- **F2** Classification fails closed — unmatched hunks, unfetchable or
  unparseable bytes, unknown formats, added artifacts, mixed classes,
  over-ceiling blast, or an emergency in play all mean no pre-approval;
  a profile can only *narrow* what auto-approves.
- **F3** Pre-approval removes exactly one thing — the human plan-review
  step; windows, gates, soak, evidence and the `OpsPlanRecord` apply
  unchanged.
- **F4** Authority comes from bytes, tighten-only — recorded decisions
  and the `ProfileRef` are claims; dispatch re-derives from checksummed
  frozen content under the current pack, and `UNVERIFIABLE` is
  unsatisfiable by construction.
- **F5** Every payload is checksum-verified before touching a device —
  a mismatch aborts the plan.
- **F6** `rollback_failed` always aborts and pages — it is not a knob.
- **F7** Unverifiable is never a pass — an unobservable just-changed
  device fails its gate; stale telemetry is unknown; a missing driver
  is `skipped`, which is not ok.
- **F8** Emergency is a named override, never a mode — `--emergency`
  AND intent-inherited `critical` priority; a pack cannot mint priority
  or pre-authorize emergencies.
- **F9** HIGH blast radius always has a named human somewhere —
  `validate-pack` errors otherwise; no configuration reaches "high
  blast radius, nobody ever looked".
- **F10** The never-by-default ladder holds (ADR-0012) — CLI
  screen-scraping and `manual` rollback are only reachable via
  explicit, reviewed per-platform pins.
- **F11** Plans are immutable and content-addressed — merge is the
  execution trigger; a changed rollout is a superseding Plan; profile
  metadata never enters `deterministic_id`.
- **F12** Waivers expire — hard `expires_at`, schema-required; no pack
  or SoT kind mints non-expiring waivers.
- **F13** Vocabularies are closed — the `low<moderate<high` ladder and
  its ordering, gate kinds, selectors, matchers, verbs, content formats
  and rollback names are engine vocabulary; thresholds move, the ladder
  does not; packs select among engine entries, never define them.
- **F14** There is no silent profile — an unloadable, invalid or
  tenant-mismatched pack stops planning and holds dispatch; unknowns in
  strict mode error; `builtin:baseline` ships zero change classes
  (CI-pinned).
- **F15** The review-plane rule — approval floors, blast thresholds and
  change classes are pack-file-only; SoT-side policy reads (windows
  today; anything future) come from the **default branch only**, never
  the candidate branch under evaluation; and no per-customer code path
  exists anywhere — a need the profile cannot express escalates to an
  ADR, not a fork.

The review-plane rule deserves its full statement, because it decides
every future "should this move to the SoT?" debate:

> An operational policy may ever leave pack files for the SoT if and
> only if its worst-case misconfiguration cannot remove a human from
> the loop or widen what executes unattended.

A bad change window opens a *time*; a bad approval floor removes a
*human*. That is why windows live in the SoT and floors never will,
until an RBAC substrate changes the argument.

## 8. Onboarding customer #2, end to end

Meridian again, from zero to first plan:

1. **Their Infrahub.** A dedicated per-tenant stack (the decided
   posture; shared Infrahub is a deferral). Load the `Intent*` generics
   matching `sot.intent_model_version`, then their typed kinds —
   contracts, network policies, invariants — each with
   `inherit_from:` the matching generic. Their device schema stays
   theirs: `DcimGenericDevice`, `"Juniper JunOS"` spelling and all; the
   pack's `sot:` section is what makes it queryable.
2. **Their pack, in their SoT repo.** `policy-pack/` at the repo root:
   the `profile.yaml` from §4, their `canary_strategies.yaml` and
   `change_classes.yaml` with match/refuse fixtures, and a CODEOWNERS
   entry giving rollout approvers ownership of the directory.
3. **Their CI.** `autonetops-planner validate-pack policy-pack/` on
   every pull request touching the pack (gates 1–5), plus
   `--infrahub-url` advisory runs; at onboarding the `--infrahub-url`
   run is mandatory and must be clean.
4. **The deployment.** The existing `sotRepo.gitUrl` init container
   already clones their SoT repo; set
   `IBN_POLICIES_DIR=/data/sot-repo/policy-pack` and
   `IBN_TENANT=meridian`. No new required parameters, no second clone,
   no engine build.
5. **First plan.** An intent edit merges in their Infrahub; the
   orchestrator renders, diffs, and builds a plan under
   `meridian-production@1.4.0` — blast radius under *their* thresholds,
   drivers from *their* platform spellings, approvals from *their*
   floors — with the `ProfileRef` in `plan.yaml`, the resolved profile
   in `profile.lock.yaml`, and the three profile fields on the
   `OpsPlanRecord` beside their intent.

The engine binary that did this is the same one running the lab. The
only difference between customers is data under their own review.

## 9. Deferrals, with triggers

Deliberately not built, each with the named condition that reopens it:

| Deferred | Trigger |
|---|---|
| Contract-compilation registry (the `IntentRoutingContract` hardcode) | a second contract kind in any customer SoT |
| New selectors (`one_per_group`, `percentage`, `prefer_tagged`), gate kinds, matchers — incl. the ietf-xml matcher | two customers need the same new kind; engine releases gated by `requires_planner` |
| `ContentFormat` / `ControlPointKind` / `BlastRadiusClass` extension | a customer format/tier need two packs share |
| Full Infrahub query generalization (`affected_devices`, control-point kinds, arbitrary fragments) | ADR-0011 SoT capability/control-point records landing |
| Rate-limit enforcement beyond per-class `max_plans_per_hour` | the ADR-0004 broker / Plan-API stage forces a real counter |
| SoT-resident operational policy families + lock/snapshot machinery | SoT-queryable "what rules are in force" demand + the RBAC/Plan-API substrate; F15 pre-decides what may ever migrate |
| Packs as OCI/registry artifacts; pack signing; digest tripwire | packs distributed outside the customer's SoT repo, or customer-run workers (ADR-0009) |
| RBAC replacing CODEOWNERS | Plan API + approval UI |
| Multi-layer overlays (env/region/BU packs) | a partner/reseller channel needing baseline-of-baselines |
| Shared-Infrahub tenancy + scoped `(target, definition)` identity | an evidence-backed shared-Infrahub ADR |
| Waiver-aware planning (waivers relaxing pack policy at decision time) | a concrete customer waiver use-case at a planner decision point — deliberately excluded until then, because SoT data loosening pack decisions inverts tighten-only |

One consequence worth stating plainly: until the ietf-xml matcher
lands, NETCONF-native customers get no pre-approval — their changes all
take the normal approval path. That is a documented limitation, and the
fail-closed rule (F2) stands.
