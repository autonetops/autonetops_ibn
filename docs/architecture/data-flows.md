# Data Flows

## Flow 1 — Intent change (the happy path)

1. Engineer creates an Infrahub **branch**, edits intent (tenant, routing
   contract, security policy…).
2. Engineer opens a **proposed change** in Infrahub.
3. Infrahub runs repository **checks** (`infrahub/checks/`) — policy-as-code
   merge gates (IPAM bounds, invariant removal, redundancy floors…).
4. Artifacts regenerate on the branch: configs + expectations.
5. **Planner** diffs branch artifacts vs. deployed state → Plan with blast
   radius annotation. High blast radius ⇒ higher approval bar.
6. Proposed change is merged; the Plan is approved (process TBD — see ADR
   backlog) and handed to the **orchestrator**.
7. The deploy flow executes canary stage 1 via the executor → validator gates
   → next stage → … done.
8. Validator confirms expectations; compliance status lands back in Infrahub.

## Flow 2 — Drift detection (no change requested)

1. Telemetry pipelines continuously normalize observed state.
2. Validator evaluates expectations on a schedule / on events.
3. Drift found → classified:
   - **Benign** → recorded, dashboard only.
   - **Dangerous, auto-fixable** → remediation playbook proposes a Plan
     (re-deploy authoritative artifact) — still goes through planner policy.
   - **Dangerous, not auto-fixable** → quarantine + human escalation.

## Flow 3 — Emergency change

Reality includes 03:00 incidents. The emergency path is *documented, not
improvised* (see `docs/runbooks/emergency-changes.md`):

1. Manual change is permitted under incident conditions.
2. The validator will flag the resulting drift (by design).
3. The follow-up obligation is **backporting the change into intent** in
   Infrahub within the defined SLA, after which drift clears.
4. The incident becomes a candidate **simulation scenario**.

## Flow 4 — Platform change (this repo)

Changes to transforms/templates/schemas in `infrahub/` alter what gets rendered
for *existing* intent — they are production-affecting even with zero intent
edits. Therefore:

1. Golden tests (`infrahub/tests/`) pin intent → rendered output per vendor.
2. CI regenerates artifacts for a sample intent corpus and diffs them; any
   diff must be explicitly acknowledged in review.
3. Schema changes follow the versioning policy in ADR-0002.
