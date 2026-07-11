# executor/

The **execution-layer role** (ADR-0010): the only component that touches the
network. One architecture over three southbound classes — direct NOS, API
vendors, controllers — via the **control-point model** (ADR-0011).

```
executor/
  pyproject.toml                    # package: autonetops-executor
  src/autonetops_executor/
    models.py                       # Evidence, CapabilityMatrix, Diff/Snapshot/PendingChange
    driver.py                       # BaseDriver verb contract + registry + capability_report()
    exceptions.py
    drivers/
      mock.py                       # ✅ reference driver: full transactional lifecycle in
                                    #    memory — the executable spec of the verb contract
      nokia_srlinux.py              # 🚧 gNMI skeleton; first containerlab milestone
                                    # next: juniper_junos (NETCONF), arista_eos (eAPI/gNMI),
                                    # Phase 2: API-vendor driver, Phase 3: controller driver
    transports/                     # shared protocol primitives as drivers need them
                                    # (pygnmi / ncclient / scrapli / httpx — ADR-0008)
  tests/                            # verb-contract tests (9) incl. the no-Prefect boundary check
```

Install: `pip install -e executor[dev]` (extras: `gnmi`, `netconf`, `ssh`, `http`).

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
