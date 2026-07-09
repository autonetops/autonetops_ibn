# deployer/

The deployer **executes a Plan and nothing else**. It never decides *what*
to change (Infrahub) or *whether/when* it is safe (planner). Input: a Plan
document. Output: an execution report.

```
deployer/
  src/               # deployer implementation
  workflows/         # executable change workflows (push config, rotate auth, apply ACL)
  adapters/          # transport isolation — one directory per protocol
    gnmi/
    netconf/
    ssh/
    vendor_api/
  rollback/          # vendor transactional semantics, isolated and tested
    # junos: commit confirmed
    # iosxr: commit confirm / commit replace caveats
    # eos:   checkpoints
  tests/
```

## Design rules

1. **Rollback is a first-class concept**, not an afterthought. Vendor commit
   semantics live in `rollback/`, tested independently — never sprinkled
   through workflow code.
2. **Adapters isolate transports.** Workflow logic must not know whether a
   device speaks gNMI or NETCONF.
3. **Every step is gated.** The deployer halts a canary stage when the Plan's
   validation checkpoint fails, and executes the step's rollback strategy.
4. **Evidence out.** Every step emits what was actually committed (diffs,
   timestamps, transport-level proof) for the validator and audit trail.
5. Device write credentials exist **only** here (secrets design: ADR backlog).
