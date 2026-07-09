# simulations/

"It worked in staging" is not a strategy. Networks fail in interactions —
route-reflector divergence, partial link failure, policy interaction across
domains. Simulations turn those into regression tests.

```
simulations/
  containerlab/
    fabrics/           # reusable lab fabrics (leaf/spine, edge)
  golden-topologies/   # incident history encoded as reproducible scenarios
    # e.g. rr-divergence/, route-leak/, partial-failure/
  expectations/        # expectation checks that must hold per scenario
```

## The incident → regression pipeline

A mature IBN program treats major incidents like software bugs:

1. **Reproduce** the incident in a minimal containerlab topology.
2. **Encode** it under `golden-topologies/<name>/`.
3. **Add** an expectation test that fails while the bug exists.
4. **Prevent recurrence** by wiring the scenario into the CI simulation gate.

## CI usage (target state)

CI spins a golden topology, deploys candidate artifacts from an Infrahub
branch, runs the validator against the lab's telemetry, and blocks merge on
expectation failure. Sizing/runtime budget: to be defined with the first
scenario.
