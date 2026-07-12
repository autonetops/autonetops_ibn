# plans/

Approved and pending rollout Plans (see ADR-0003; full lifecycle in
`docs/architecture/plan-lifecycle.md`).

- Each Plan is a **bundle directory** `plans/<plan-id>/`, generated — never
  written by hand:
  - `plan.yaml` — the Plan (`contracts/plan/v1/plan.schema.json`)
  - `timeline.yaml` — per-stage window fit
  - `decision.yaml` — dispatch decision (mode, approvals, priority)
  - `content/` — frozen rendered artifacts, checksum-pinned by the plan
  - `content_base/` — pre-approved plans only (ADR-0014): frozen base bytes
    so dispatch can re-prove the change class from the bundle alone
  - `expectations/` — rendered contract expectations for the stage gates
  - `evidence.jsonl` — appended by dispatch; `report.yaml` — written by
    dispatch; both are committed (the existing example bundle predates
    `report.yaml` and does not contain one)

  Only `.watch-state.json` (orchestrator runtime state) stays out of Git.
- A Plan arrives as a **PR**; approval = PR review (approval bar scales with
  the blast radius annotated on the PR), or unattended when the diff matches
  a pre-approved change class (ADR-0014); **merge = execution trigger** for
  the deployment flow (ADR-0004/0005).
- Plans are **immutable post-merge**. Changing a rollout means a new Plan PR
  that supersedes the old one. The bundle is the immutable hand-off to
  dispatch (ADR-0013 §3): a merged (deleted) branch can no longer change what
  was approved, and every payload is checksum-verified before it touches a
  device.
