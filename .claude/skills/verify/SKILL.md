---
name: verify
description: Drive the ibn-orchestrate / ibnctl CLIs end-to-end without a lab, using the mock driver and a fake Infrahub GraphQL server.
---

# Verifying this repo without a lab

The real user surfaces are the `ibn-orchestrate` and `ibnctl` CLIs
(installed by `pip install -e ./validator -e ./planner -e ./executor
-e ./orchestrator -e ./tools/ibnctl`). Everything Infrahub-shaped the CLIs
need can be faked with a ~70-line HTTP server; everything device-shaped runs
against the registered `mock` driver (the executable spec of the verb
contract).

## Recipe

1. **Fake Infrahub**: a `http.server` answering POSTs with
   `{"data": {...}}` keyed on the query text. Four shapes cover dispatch and
   watch:
   - `OpsChangeWindow` → one always-open maintenance window
     (`days` = all seven, `start_utc: 00:00`, `duration_minutes: 1440`,
     `max_blast_radius: high`, `devices: {edges: []}`)
   - `DcimDevice` → node with `primary_address.node.address.value`
     ("127.0.0.1/32") and `platform.node.{name,netmiko_device_type}`
   - `OpsPlanRecordUpsert` → `{"ok": true, "object": {"id": "x"}}`
   - `CoreProposedChange` → one PC with `state.value` open/merged
   Every field is Infrahub-attribute-shaped: `{"value": ...}`. Log request
   bodies to a file — they are your evidence of what the CLI actually sent.
   Auth is ignored; `--infrahub-token` can be any string.

2. **Plan bundle**: build it through the real code path (ChangeSet →
   `build_plan` → `decide` → `model_dump(mode="json", by_alias=True)` to
   YAML), steps with `platform="mock"` (falls through to the `mock` driver)
   and checksums = `sha256(content)` so the executor's checksum gate passes.
   Content files: `content/{target}__{definition}.cfg` (+ `content_base/`
   for pre-approved plans). An empty `expectations/` dir means gates pass
   with "no expectations scoped".

3. **Drive**:
   ```
   export INFRAHUB_ADDRESS=http://127.0.0.1:<port> INFRAHUB_API_TOKEN=t
   export IBN_POLICIES_DIR=planner/policies   # pre-approval needs this on BOTH plan and dispatch
   ibn-orchestrate dispatch --plan-dir <bundle> --soak-scale 0
   ibn-orchestrate watch --once --plans-dir <dir>   # seed plans/.watch-state.json to skip planning
   ```
   Exit codes: 0 ok, 2 aborted/failed, 3 waiting on window, 4 missing
   approvals.

## Gotchas

- `ibn-orchestrate plan` / `run` / `watch`-planning need a real SoT repo
  checkout (`IBN_SOT_REPO`) with queries/transforms — not fakeable this way;
  bypass by writing the bundle directly (step 2) and driving `dispatch`.
- `watch --once` with a pre-seeded `.watch-state.json` (record with
  `plan_dir`) skips plan_fn entirely — that's how to test dispatch reactions
  without renderable branches.
- MockDriver accepts any connection dict (uses `initial_config` if present);
  SotInventory's `{host, username, password}` works as-is.
