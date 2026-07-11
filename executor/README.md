# executor/

The **execution-layer role** (ADR-0010): the only component that touches the
network. One architecture over three southbound classes — direct NOS, API
vendors, controllers — via the **control-point model** (ADR-0011).

```
executor/
  drivers/             # platform drivers implementing the executor verbs
    nokia_srlinux/     # Phase 1 — gNMI-native; containerlab CI workhorse
    juniper_junos/     # Phase 1 — NETCONF; commit-confirmed gold standard
    arista_eos/        # Phase 1 — eAPI/gNMI; api-style path + checkpoints
                       # Phase 2: first cloud/API-vendor driver (estate-driven)
                       # Phase 3: first controller driver (Apstra/CVP/NSO/...)
  transports/          # protocol primitives drivers compose (ADR-0008 libraries)
    gnmi/              # pygnmi
    netconf/           # ncclient
    ssh/               # scrapli
    http/              # httpx — API vendors and controllers
  tests/               # verb-contract tests + containerlab integration per driver
```

## The verb contract

Every driver implements the same verbs, each returning structured Evidence:

```
get_facts | snapshot | dry_run -> Diff | apply -> PendingChange | confirm | rollback
```

And declares its **capability matrix** (transactional, supports_dry_run,
supports_confirm, supports_snapshot, atomicity: per_device|domain), which the
planner consumes to pick rollback/canary strategies (ADR-0011). Rollback is a
driver capability — vendor transactional semantics live inside each driver,
not in workflow code.

## Rules

1. No orchestrator/Prefect imports — enforced in CI (ADR-0009).
2. One verb call = one control-point operation. Concurrency, ordering and
   batching belong to the Plan + orchestrator.
3. Serializable inputs/outputs only (pydantic): the API is designed as if
   remote from day one, so promotion to a device-gateway service (ADR-0009
   triggers) is mechanical.
4. Device credentials exist only here.
5. A driver without integration tests and a capability declaration does not
   merge. Package: `autonetops-executor`.
