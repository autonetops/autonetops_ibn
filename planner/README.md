# planner/

Planning is **policy**; deployment is **execution**. The planner answers
*"is this change safe, and in what order do we make it?"* — without touching a
device. It is a pure function over data: given candidate artifacts, deployed
state and policies, it emits a **Plan** (see
`docs/architecture/component-contracts.md` §3).

```
planner/
  src/               # planner implementation (language/framework: see ADR backlog)
    diffing/         # candidate artifacts (Infrahub branch) vs deployed state
    blast_radius/    # affected devices / regions / tenants / contracts
    dependency/      # ordering constraints (underlay before overlay, RRs first…)
    safety/          # policy evaluation engine
  policies/          # organizational constraints as DATA — auditable, reviewable
    change_windows.yaml
    canary_strategies.yaml
    rate_limits.yaml
  tests/
```

## Responsibilities

- Diff candidate vs. deployed artifacts (by Infrahub storage checksum).
- Compute and annotate **blast radius** — this drives the approval bar.
- Order steps into canary stages with validation checkpoints and abort criteria.
- Enforce policies: change windows/freezes, per-region rate limits, canary
  strategy selection.

## Non-responsibilities

- Never talks to devices.
- Never renders or mutates configs — artifacts are consumed as-is.
- Never auto-approves: the Plan is an input to a human/CI approval gate.
