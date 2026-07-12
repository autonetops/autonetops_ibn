# tools/

Operator-facing tooling and one-off-but-versioned helpers.

```
tools/
  ibnctl/            # the platform CLI. Implemented today: `ibnctl --plan
                     # plan.yaml [--check]` walks a Plan through the executor
                     # (snapshot -> dry_run -> apply -> rollback-on-failure),
                     # resolving device addresses from the Infrahub SoT and
                     # artifact content from object storage or --content-dir,
                     # writing evidence JSONL per verb. Planned: inspect
                     # plans, abort rollouts, query compliance, explain drift
  migration/         # brownfield adoption + schema evolution helpers
    # import_existing_configs  — parse device configs into Infrahub intent/SoT
    # schema_upgrade_assistant — migrate data across schema versions
```

Adoption is never clean; `migration/` is where the mess is handled explicitly
instead of leaking into the platform.
