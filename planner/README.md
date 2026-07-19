# planner/

Planning is **policy**; deployment is **execution**. The planner answers
*"is this change safe, and in what order do we make it?"* — without touching a
device. It is a pure function over data: given candidate artifacts, deployed
state and an **intent profile**, it emits a **Plan**
(`contracts/plan/v1/plan.schema.json`, ADR-0003).

One engine, N customers (ADR-0016): every per-customer fact — blast
thresholds, approval floors, platform/artifact bindings, canary strategies,
change classes, delivery preferences, SoT query paths — is data in a
**policy pack**, never code. A pack is any directory containing
`profile.yaml`; `--policies-dir` / `IBN_POLICIES_DIR` points at it. No pack
configured means the shipped `builtin:baseline` pack applies (bit-identical
to the historic defaults, with provenance); a dir *without* `profile.yaml`
is legacy mode (lenient, deprecated, every fallback recorded).

```
planner/
  pyproject.toml               # package: autonetops-planner (Python >= 3.11)
  src/autonetops_planner/
    models.py                  # Plan contract (pydantic; JSON Schema generated from here)
    profile.py                 # intent profiles: pack loading, merge, validation (ADR-0016)
    packs/baseline/            # builtin:baseline - the engine defaults as a real pack
    artifact_source.py         # Infrahub + static-fixture artifact readers (SoT paths from the pack)
    diffing.py                 # candidate vs deployed artifacts -> ChangeSet
    blast_radius.py            # affected devices/roles/regions -> low|moderate|high
    policies.py                # legacy-mode loaders + builtin constants (mirrored by packs/baseline)
    change_classes.py          # pre-approved change classes (ADR-0014): content-aware classification
    plan_builder.py            # ChangeSet + strategy + profile -> staged Plan
    cli.py                     # autonetops-planner plan | validate-pack | export-schema
  policies/                    # the REFERENCE pack (extends builtin:baseline) baked into the image
    profile.yaml
    canary_strategies.yaml
    change_classes.yaml
    delivery_preferences.yaml
    rate_limits.yaml
    tests/change_classes/      # mandatory golden match/refuse fixtures per change class
  tests/
```

## Usage

```bash
pip install -e planner[dev]

# offline / test mode (builtin:baseline profile)
autonetops-planner plan --base main --candidate <branch> \
  --fixture planner/tests/fixtures/artifacts.json -o plan.yaml

# against Infrahub, under a customer pack (INFRAHUB_ADDRESS /
# INFRAHUB_API_TOKEN / IBN_POLICIES_DIR / IBN_TENANT also work)
autonetops-planner plan --candidate <branch> \
  --infrahub-url https://infrahub.example --infrahub-token $TOKEN \
  --policies-dir /data/sot-repo/policy-pack

# the pack CI gate: schema, closed vocabulary, cross-references,
# golden change-class fixtures, optional live-SoT conformance
autonetops-planner validate-pack planner/policies

# regenerate contract schemas after model changes (CI checks drift)
autonetops-planner export-schema --contract plan
autonetops-planner export-schema --contract profile
```

## Responsibilities

- Diff candidate vs. deployed artifacts (by Infrahub storage checksum).
- Compute and annotate **blast radius** under the profile's thresholds —
  this drives the approval bar.
- Classify diffs against the pack's pre-approved change classes
  (ADR-0014); fail-closed, golden-fixture-guarded.
- Order steps into canary stages with validation checkpoints and abort
  criteria; record the effective approval bar (strategy + blast-class
  floors) and the profile's identity in the Plan.
- In strict profile mode, **refuse to guess**: an unbound platform or
  artifact definition is a PlanBuildError naming every gap. (Window/rate-
  limit evaluation: windows live in the SoT per ADR-0013; rate limits are
  validated pack data reported as `not_evaluated`, honestly.)
- Artifact **removals never become deploy steps** — they land in
  `removed_targets` for an explicit decommission decision.

## Non-responsibilities

- Never talks to devices.
- Never renders or mutates configs — artifacts are consumed as-is.
- Never auto-approves: the Plan lands as a PR under `plans/` (ADR-0003);
  pre-approval only ever comes from the customer's own reviewed change
  classes (`builtin:baseline` ships zero, CI-pinned).
