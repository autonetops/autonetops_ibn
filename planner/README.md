# planner/

Planning is **policy**; deployment is **execution**. The planner answers
*"is this change safe, and in what order do we make it?"* — without touching a
device. It is a pure function over data: given candidate artifacts, deployed
state and policies, it emits a **Plan**
(`contracts/plan/v1/plan.schema.json`, ADR-0003).

```
planner/
  pyproject.toml               # package: autonetops-planner (Python >= 3.11)
  src/autonetops_planner/
    models.py                  # Plan contract (pydantic; JSON Schema generated from here)
    artifact_source.py         # Infrahub + static-fixture artifact readers
    diffing.py                 # candidate vs deployed artifacts -> ChangeSet
    blast_radius.py            # affected devices/roles/regions -> low|moderate|high
    policies.py                # canary strategies etc. loaded from policies/ (data, not code)
    plan_builder.py            # ChangeSet + strategy -> staged Plan
    cli.py                     # autonetops-planner plan | export-schema
  policies/                    # organizational constraints as DATA — auditable, reviewable
    change_windows.yaml
    canary_strategies.yaml
    rate_limits.yaml
  tests/
```

## Usage

```bash
pip install -e planner[dev]

# offline / test mode
autonetops-planner plan --base main --candidate <branch> \
  --fixture planner/tests/fixtures/artifacts.json -o plan.yaml

# against Infrahub (INFRAHUB_ADDRESS / INFRAHUB_API_TOKEN also work)
autonetops-planner plan --candidate <branch> \
  --infrahub-url https://infrahub.example --infrahub-token $TOKEN

# regenerate the Plan JSON schema after model changes (CI checks drift)
autonetops-planner export-schema
```

## Responsibilities

- Diff candidate vs. deployed artifacts (by Infrahub storage checksum).
- Compute and annotate **blast radius** — this drives the approval bar.
- Order steps into canary stages with validation checkpoints and abort criteria.
- Enforce policies: change windows/freezes, per-region rate limits, canary
  strategy selection. (Window/rate-limit evaluation: not yet implemented —
  reported as `not_evaluated` in the Plan, honestly.)
- Artifact **removals never become deploy steps** — they land in
  `removed_targets` for an explicit decommission decision.

## Non-responsibilities

- Never talks to devices.
- Never renders or mutates configs — artifacts are consumed as-is.
- Never auto-approves: the Plan lands as a PR under `plans/` (ADR-0003).
