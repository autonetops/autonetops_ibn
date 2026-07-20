# 0016 — Intent profiles: one engine, per-customer policy packs

- Status: proposed
- Date: 2026-07-19

## Context

One engine must serve N customers, and today it cannot: every per-customer
fact is a Python constant. Blast-radius thresholds, the
`platform.lower()`-equals-driver guess, the cli-text fallback for unknown
artifact definitions, abort criteria, strategy approval names — all
hardcoded, all lab-shaped. `blast_radius.py` and `plan_builder.py` both
promise a fix "once the policy schema settles". This ADR settles it.

ADR-0014 established the discipline the answer must extend, never bend:
policy is reviewed file data, read from one source
(`IBN_POLICIES_DIR`) at both plan time and dispatch time, and every
authorization is re-derived from frozen bundle bytes under the *current*
policy, tighten-only. ADR-0015 named the instrument kinds and classified
canary strategies, change classes, thresholds and approval bars as
*operational policies*. What remained open: where does customer #2 author
each instrument, what exactly is a "policy pack", and how does one engine
bind to N packs without a code fork.

## Decision

1. **The contract, in one sentence.** A customer's intent layer is *their
   Infrahub SoT* (intents and instruments as typed kinds inheriting the
   `Intent*` generics) plus *one policy pack* (a directory containing
   `profile.yaml`, pointed at by the existing `IBN_POLICIES_DIR`, living
   in the customer's SoT repo under CODEOWNERS). The planner and
   orchestrator remain one engine that loads exactly one resolved pack per
   run, records its identity in every Plan, and at dispatch re-derives
   every authorization under the *current* pack with tighten-only
   semantics on top of a hard-coded safety floor no pack can express.

2. **Two authoring surfaces, fixed division of labor.**

   | Surface | Contains | Reviewed by |
   |---|---|---|
   | Customer's Infrahub SoT | `IntentDefinition` roots; typed contracts, network-subject policies, invariants, waivers (kinds inheriting the `Intent*` generics); `OpsChangeWindow`; devices and control points | intent owners, via branches + proposed changes + `infrahub/checks/` |
   | Policy pack (`IBN_POLICIES_DIR`) | Operational policies the engine consumes at decision time: `profile.yaml`, `canary_strategies.yaml`, `change_classes.yaml`, `delivery_preferences.yaml`, `rate_limits.yaml`, golden test fixtures | rollout approvers, via pack CODEOWNERS in the customer's SoT repo |

   **Dividing rule (normative):** if the engine reads it to shape or gate
   a Plan, it is pack data; if it describes the network or when the
   network may change, it is SoT data. `OpsChangeWindow` stays in the SoT
   (ADR-0013); its owed `inherit_from: [IntentPolicy]` migration is
   recorded in `infrahub/schemas/README.md`.

   A customer may create any SoT kind inheriting `IntentPolicy`
   (queryable, reviewable, waivable), but it becomes *executable* only by
   mapping onto one of the engine's fixed decision points — classify,
   match, stage, approve, deliver, schedule, abort, admit — via the pack
   sections that parameterize them. **The profile parameterizes decision
   points; it never adds them.** A need no pack section can express is an
   engine ADR, never a fork.

3. **The policies dir IS the pack.** No new artifact type, registry, or
   env var. A pack is any directory containing `profile.yaml`;
   `IBN_POLICIES_DIR` / `--policies-dir` semantics are unchanged. The
   builtin defaults living today as Python constants become a real
   shipped pack, `planner/src/autonetops_planner/packs/baseline/`
   (data files in the wheel), addressable as `builtin:baseline`. The
   silent code-fallback path dies: "no policies dir" means "load
   `builtin:baseline`" — which has a name, version and checksum, so
   provenance is never blank. A dir *without* `profile.yaml` is **legacy
   mode**: today's per-file lenient semantics preserved verbatim, each
   fallback recorded in the new `assumptions` field and echoed at plan
   time.
   One new *optional* env var only: `IBN_TENANT` (decision 10).

4. **Pack identity is three numbers, never conflated.**
   - `profile_version: 1` — file-format contract; changing it requires
     `contracts/profile/v2/` plus an ADR.
   - `meta.version` — pack content semver, authored by the customer,
     bumped under review.
   - **checksum** — never authored. Computed by the loader as sha256 over
     the *fully resolved* profile (post-`extends`, post-merge, change
     classes parsed in) serialized as canonical JSON. Identity from
     bytes, not claims; the value the Plan records and dispatch compares.

5. **Layering: exactly two layers, boring merge rules.**
   `extends: builtin:baseline` or `extends: null` (from scratch; every
   mandatory section then required). No chains, no relative-path parents,
   no tombstones; strategy removal is spelled `enabled: false`. Loader-
   enforced rules:

   | Content | Rule |
   |---|---|
   | `blast_radius`, `artifacts`, `rollback`, `sot`, `abort_criteria` | wholesale section replacement; omitted = inherited |
   | `platforms`, `delivery_preferences` entries | per-key merge; a child key replaces the whole parent entry, never field-merges |
   | `canary_strategies` `strategies[]` | merge by `name`: same name = full replacement; new names add; `enabled: false` removes |
   | `approvals.floors` | union only — a child adds approvers, never removes; `null` illegal on any safety field |
   | `change_classes` | no layering, ever. Baseline ships **zero** classes (CI-pinned); the customer file is the sole source of auto-approval authority |

6. **Conformance levels.** `meta.conformance: baseline | tuned | full`
   (default `tuned`); a pack may not use sections above its level.
   `baseline` = `meta`/`extends`/`blast_radius`/`abort_criteria` only;
   `tuned` adds `approvals`, `platforms`, `artifacts`, `rollback`,
   `files`; `full` adds `sot` overrides beyond `default_base_branch`.
   A "small" customer's pack cannot silently grow unreviewed surface.

7. **`validate-pack` is the contract's teeth** — the long-promised
   `policy-validate` CI job, run in customer pack CI and platform CI.
   Gates, in order, all fatal: (1) `profile.yaml` validates,
   `requires_planner` satisfiable, `extends` resolves, conformance
   respected; (2) every listed file exists and validates, unknown keys
   are errors; (3) closed-vocabulary membership — selectors, gate kinds,
   blast classes, rollback names, compilable regexes, the threshold
   ladder (`low_max_devices < high_min_devices`); (4) cross-references —
   every named strategy resolves, strategies cover all three blast
   classes, every classification-reachable HIGH strategy has non-empty
   effective approvals (floor F9; class-only strategies with
   `applies_to_blast_radius: []` are exempt — reachable solely via a
   reviewed, customer-authored change class, whose review is the human
   look);
   (5) **golden tests, mandatory**: each enabled change class must ship a
   `.match.yaml` and a `.refuse.yaml` fixture that `classify_changes`
   matches and refuses respectively — a class without both is invalid,
   not warned; (6) with `--infrahub-url` (runs only when credentials are
   provided, fatal when it runs; required clean at onboarding):
   `sot.device_kind` queryable with the declared paths, artifact
   definitions exist (generic-inheritance automation owed to this gate;
   until then it is the onboarding checklist).

   Enforcement split: gates 1–4 run inside `load_profile` itself, so
   every plan and dispatch enforces them; gates 5–6 run in
   `validate-pack` (the pack's CI) — which is why golden fixtures are a
   merge gate on the pack, not a runtime check.

8. **The review-plane rule** (loader-enforced): *an operational policy
   may ever leave pack files for the SoT if and only if its worst-case
   misconfiguration cannot remove a human from the loop or widen what
   executes unattended.* Change classes, approval floors and
   blast-radius thresholds parameterize who approves, what skips
   approval, and how much counts as small — they stay in pack files
   under CODEOWNERS until RBAC replaces CODEOWNERS, and there is no
   profile syntax to source them elsewhere. Windows are the precedent
   proving the split: a bad window opens a *time*, never removes a
   *human*, and dispatch re-checks it fail-closed.

9. **Provenance is recorded everywhere, authoritative nowhere.** Every
   Plan records `policy_evaluation.profile: ProfileRef` (tenant, name,
   version, checksum, source) — additive v1 change, same precedent as
   `pre_approved`; `deterministic_id` still hashes only
   `source + stages`, so provenance is metadata, not identity. Every
   bundle gains `plans/<id>/profile.lock.yaml` (the full resolved
   profile) — for audit and re-derivation, never authority. The SoT
   `OpsPlanRecord` gains `profile_name`/`profile_version`/
   `profile_checksum`, so "which policy version produced every change
   last quarter" is a SoT query.

10. **Dispatch re-verification: ADR-0014 extended, never bent.** Frozen
    bundle bytes are testimony; the *current* pack is judge; verdicts
    only tighten:
    1. *Pre-approval*: `verify_pre_approval` re-classifies frozen bytes
       under the current pack's change classes. A class disabled,
       removed or tightened retroactively kills auto-approval for
       already-planned bundles; the kill switch now includes "ship a new
       pack version".
    2. *Approval bar*: floor = union(frozen plan's effective approvals,
       current pack's strategy-by-name approvals, current pack floors
       for the effective blast class). A strategy that vanished from the
       current pack injects `UNVERIFIABLE` when a pre-approval claim
       failed re-verification (ADR-0014's scope: a claim that cannot be
       checked); on an unclaimed, human-approved plan it is surfaced as
       a note while the floors and the recorded bar still apply.
    3. *Blast re-tightening*: classification is recomputed from the
       frozen plan's recorded device/region counts under current
       thresholds; effective class = max(pinned, recomputed). The
       pinned class is a floor, never a ceiling.
    4. *Profile drift is recorded, never blocking by itself*: checksum
       mismatch appends a `profile_drift` record to `evidence.jsonl`
       and the decision reasons, then proceeds — rules 1–3 already
       re-prove everything that matters under the current pack.
    5. *Fail-closed on bad profile*: profile invalid or missing where
       the plan records one, tenant mismatch, or `requires_planner`
       unsatisfied → `UNVERIFIABLE` on all pre-approval claims and
       refusal of immediate dispatch (exit-4 approval-hold semantics).
       Never a silent baseline fallback.
    6. *Frozen choreography is never rewritten*: stages, soak,
       selectors, gates, drivers, protocols and rollback specs are
       spent at plan time; a pack that would shape them differently
       gets a superseding Plan (ADR-0003), surfaced via the drift
       record. Windows still come live from the SoT, never the lock —
       a freeze created after planning MUST bite.
    Tenant guard: when `IBN_TENANT` is set, load refuses a profile
    whose `meta.tenant` differs and dispatch refuses a bundle whose
    recorded tenant differs — cross-tenant bundle replay becomes a loud
    failure, not a quiet execution.

11. **The safety floor: what never varies per customer.** Engine code
    with tests; no `profile.yaml` field reaches any of these:
    - **F1** Removals never auto-deploy; decommission is always an
      explicit human decision.
    - **F2** Fail-closed classification: unmatched hunk, unfetchable or
      unparseable bytes, unknown format, added artifacts, mixed classes,
      over-ceiling blast, emergency in play → no pre-approval. A profile
      can only narrow what auto-approves.
    - **F3** Pre-approval removes exactly one thing — the human
      plan-review step; windows, gates, soak, evidence, `OpsPlanRecord`
      apply unchanged.
    - **F4** Authority from bytes, tighten-only; recorded decisions and
      `ProfileRef` are claims; `UNVERIFIABLE` is unsatisfiable.
    - **F5** Every payload checksum-verified before touching a device;
      mismatch aborts the plan.
    - **F6** `rollback_failed` always aborts and pages; not a knob.
    - **F7** Unverifiable is never a pass; missing driver → `skipped`,
      which is not ok.
    - **F8** Emergency is a named override, never a mode; a pack cannot
      mint priority or pre-authorize emergencies.
    - **F9** HIGH blast radius always has a named human somewhere;
      load-time error otherwise (a class-only strategy's human is the
      change-class review itself).
    - **F10** Never-by-default ladder (ADR-0012): CLI screen-scraping
      and `manual` rollback only via explicit, reviewed per-platform
      pins.
    - **F11** Plan immutability and content-addressed identity; profile
      metadata never enters `deterministic_id`.
    - **F12** Waivers expire; hard `expires_at`, schema-required.
    - **F13** Closed vocabularies: the `low<moderate<high` ladder and
      its ordering, gate kinds, selectors, matchers, verbs, content
      formats, rollback names — thresholds move, the ladder does not.
    - **F14** No silent profile: an unloadable, invalid or
      tenant-mismatched pack stops planning and holds dispatch;
      `builtin:baseline` ships zero change classes (CI-pinned).
    - **F15** Review-plane rule (decision 8); SoT-side policy reads come
      from the default branch only, never the candidate branch under
      evaluation; no per-customer code path exists anywhere.

12. **Rejected** (each considered, each closed):
    - *Gate-name registry resolved at dispatch* — a known-but-remapped
      gate name converts an approved `manual` gate into an automated one
      via a later pack edit: a loosening of an approved plan by mutable
      data. `Gate.kind` stays the closed
      `Literal["validator.expectations_pass", "manual"]`, frozen into
      the bundle at plan time; pack gate strings are validated against
      the closed set at pack load. No `Gate.name`, no widening.
    - *Assume cli-text for unknown artifact definitions in profile
      mode* — a definition seen in a diff but absent from the pack's
      `artifacts:` section is a plan-time error. The `assumptions` field
      may only record non-safety fallbacks; it can never record a format
      guess in profile mode. Legacy/builtin mode keeps today's fallback,
      now recorded — status quo plus provenance, never worse.
    - *New env var* (`IBN_PROFILE_DIR`/`IBN_PROFILE`) — zero deployment
      churn, zero precedence rules; `IBN_POLICIES_DIR` already carries
      the ADR-0014 same-source discipline.
    - *Platform aliases* — `platforms:` keys are spelled exactly as the
      customer's SoT spells them (`"Juniper JunOS":` is a legal key);
      one platform spelled two ways gets two entries.
    - *Multi-layer chains and tombstones* — the largest untested
      surface for the least demonstrated need; removal is `enabled:
      false`, depth is two, forever until a superseding ADR.

13. **Deferred**, with named triggers:
    1. Contract-compilation registry (the `IntentRoutingContract`
       hardcode in `render_source.py`/`priority.py`) — own ADR; trigger:
       a second contract kind in any customer SoT. No `compilers:`
       section is reserved.
    2. New selector/gate/matcher vocabulary (incl. `one_per_group`,
       `percentage`, `prefer_tagged`, the ietf-xml matcher, new gate
       kinds) — engine releases gated by `requires_planner`; trigger:
       two customers need the same new kind. Until the ietf-xml matcher
       lands, NETCONF-native customers get no pre-approval — a
       documented limitation; fail-closed stands.
    3. `ContentFormat`/`ControlPointKind`/`BlastRadiusClass` extension —
       engine version bump + contract ADR; trigger: a customer
       format/tier need two packs share.
    4. Full Infrahub query generalization (`affected_devices`,
       control-point kinds, arbitrary fragments) — trigger: the
       ADR-0011 SoT capability/control-point records landing.
    5. Rate-limit enforcement beyond per-class `max_plans_per_hour` —
       packs may author `rate_limits.yaml`, validated, engine-ignored;
       Plans stay honest with `not_evaluated`; trigger: the ADR-0004
       broker / Plan-API stage forces a real counter.
    6. SoT-resident operational policy families + lock/snapshot
       machinery — the review-plane rule (F15) pre-decides what may
       ever migrate; trigger: a customer needs SoT-queryable "what
       rules are in force" and the RBAC/Plan-API substrate exists.
    7. Packs as OCI/registry artifacts, pack signing, the
       `profiles-seen.json` digest tripwire — git review of the pack in
       the customer's SoT repo covers the current threat model; trigger:
       packs distributed outside the customer's SoT repo, or
       customer-run workers (ADR-0009).
    8. RBAC replacing CODEOWNERS as approval authority — approver
       strings stay strings matched by `--approve`; trigger: Plan API +
       approval UI.
    9. Multi-layer overlays (env/region/BU packs) — per-environment
       deltas are per-deployment pack refs; trigger: a partner/reseller
       channel needing baseline-of-baselines.
    10. Shared-Infrahub tenancy + scoped `(target, definition)`
        identity — dedicated-per-tenant stacks are the decided posture;
        trigger: an evidence-backed shared-Infrahub ADR.
    11. Waiver-aware planning (waivers relaxing pack policy at decision
        time) — deliberately excluded: letting SoT data loosen pack
        decisions inverts tighten-only; trigger: a concrete customer
        waiver use-case at a planner decision point.

## Consequences

- **Planner**: new `profile.py` (models, two-layer resolve, checksum,
  `load_profile`, legacy adapter); the constants are transcribed into
  `packs/baseline/` and pinned equal by a golden test, so every existing
  import site survives unchanged; `build_plan` gains one optional keyword-only
  `profile` parameter — `profile=None` is exact current behavior; in
  profile mode the `platform.lower()` driver guess and the cli-text
  fallback are deleted (unbound platform / unknown definition =
  plan-time error); `artifact_source` renders its inline fragment from
  the pack's `sot:` paths, and `region` is finally populated when
  `region_path` is declared. CLI: `plan` loads one profile;
  `validate-pack` and `export-schema --contract plan|profile` are new;
  the Plan schema change (`profile` + `assumptions`, nullable) is
  additive v1.
- **Orchestrator**: `_build` and `_dispatch` both call `load_profile`
  on the same `IBN_POLICIES_DIR` (ADR-0014 same-source, unchanged);
  bundles gain `profile.lock.yaml`; `preapproval.py` gains the
  floors-union and blast re-tightening; the CLI dispatch phase gains
  the `profile_drift` evidence record, tenant guard and exit-4 hold on
  a bad profile (`dispatch.py` itself is untouched); `feedback.py` +
  `infrahub/schemas/ops_plan_record.yml` gain the three profile
  attributes.
- **Executor**: byte-for-byte unchanged except
  `SotInventory.driver_for` accepting injected platform bindings
  (fail-closed default unchanged). The profile never crosses the
  executor boundary; ADR-0009 is untouched.
- **CI**: the `policy-validate` slot in `.github/workflows/ci.yaml` is
  finally a real job — `validate-pack` on `planner/policies/` plus a
  `load_profile(None)` self-check of `builtin:baseline` (the baseline's
  reserved `_platform` tenant means it is loaded, never validated as a
  customer pack); new tests pin merge rules, checksum stability,
  the ladder validator, legacy parity, builtin==today, and
  zero-baseline-change-classes.
- **Deployment**: the customer pattern is
  `IBN_POLICIES_DIR=/data/sot-repo/policy-pack` — the existing
  `sotRepo.gitUrl` init container already clones it; no second clone,
  no new required parameters; `IBN_TENANT` is optional. The platform
  image keeps `builtin:baseline` in the wheel and `planner/policies/`
  (now with a `profile.yaml`, `name: autonetops-reference`) as the
  image-baked default pack.
- **Legacy-mode guarantee**: a policies dir without `profile.yaml`
  behaves bit-identically to today (pinned by golden test), with every
  fallback recorded in `assumptions`. Rolling back the whole feature is
  "don't add a profile.yaml". Removal of legacy mode is a future major.
  Two deliberate carve-outs from bit-identical: bare `srlinux` now maps
  to `snapshot_revert` like `nokia_srlinux` (same NOS, same driver; it
  previously fell to `manual` by omission — this also changes the
  content-addressed id of plans touching that spelling), and a
  *nonexistent* policies dir is now a hard error instead of quietly
  loading builtin defaults (F14: a failed SoT clone must never
  evaporate the policy surface without a sound).
- The "once the policy schema settles" promises in `blast_radius.py`
  and `plan_builder.py` are discharged; `compute_blast_radius`'s
  unplumbed thresholds parameter is finally plumbed.
- **The vocabulary of ADR-0015 is unchanged.** This ADR adds no
  instrument kind and renames nothing — it only decides *where* each
  instrument kind is authored and *how* it binds to the engine. The
  full customer-facing model lives in
  `docs/architecture/intent-profiles.md`.
