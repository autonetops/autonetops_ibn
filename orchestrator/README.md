# orchestrator/

The **workflow role** (ADR-0010): sequence and reaction for the closed loop.
Per ADR-0005 it ships as an independently runnable library + CLI first
(`autonetops-orchestrator`, command `ibn-orchestrate`); Prefect flows in
`flows/` wrap the same functions when the platform stack lands. No Prefect
imports exist in `src/`.

```
orchestrator/
  src/autonetops_orchestrator/
    render_source.py  # render artifacts per Infrahub branch, in-process
    windows.py        # OpsChangeWindow from the SoT: occurrences, freezes
    timeline.py       # fit stages into windows, chain soak (ADR-0013)
    strategy.py       # immediate | scheduled | needs_approval | blocked
    priority.py       # plan urgency inherited from the intent layer
    dispatch.py       # stage walker: run_step + validator gates + soak
    watch.py          # reconcile loop over proposed changes (ADR-0004)
    cli.py            # ibn-orchestrate windows|plan|dispatch|run|watch
  flows/              # Prefect packaging of the above (future)
```

## The flow

```
Infrahub branch/PC ──> plan      render base+candidate, diff, blast radius,
                                 canary stages (planner), timeline vs SoT
                                 change windows, dispatch decision
                       plans/<plan-id>/   plan.yaml timeline.yaml decision.yaml
                                          content/*.cfg expectations/*.yml
                  ──> dispatch   windows re-checked, approvals enforced,
                                 run_step per step, soak, expectations gate
                                 per stage, evidence.jsonl
                                 outcome persisted: plans/<id>/report.yaml +
                                 OpsPlanRecord upserted in the SoT (feedback.py;
                                 schema: infrahub/schemas/ops_plan_record.yml)
                  ──> watch      plan when a PC opens, dispatch when it merges
```

## Rules

1. Flows never talk to devices — only the executor does (ADR-0010/0011);
   dispatch calls `autonetops_executor.run_step` / `get_facts` exclusively.
2. Flows never decide *what* changes (Infrahub) or *whether it's safe*
   (planner + approved Plan). They decide *sequence and reaction* — and
   *when*, against `OpsChangeWindow` data in the SoT (ADR-0013).
3. Every phase is idempotent and resumable: plans are content-addressed,
   dispatch re-checks windows at execution time, watch keeps its state on
   disk and reconciles the full proposed-change list every pass.
