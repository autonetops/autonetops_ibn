"""ibnctl apply — drive a Plan through the executor, step by step.

The manual, break-glass path (ADR-0005): same verb sequence as the
orchestrator's dispatch (both call autonetops_executor.run_step), none of
the scheduling. Windows, gates and soak belong to `ibn-orchestrate`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from autonetops_executor import run_step
from autonetops_executor.inventory import SotInventory
from autonetops_planner.models import Plan

app = typer.Typer(help=__doc__, no_args_is_help=True)


def _emit(evidence_path: Path, record: Any) -> None:
    payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
    with evidence_path.open("a") as fh:
        fh.write(json.dumps(payload) + "\n")


@app.command("apply")
def apply_command(
    plan_path: Path = typer.Option(..., "--plan", help="Plan YAML (planner output)"),
    infrahub_url: str = typer.Option("http://localhost:8000", envvar="INFRAHUB_ADDRESS"),
    infrahub_token: Optional[str] = typer.Option(None, envvar="INFRAHUB_API_TOKEN"),
    username: str = typer.Option("admin", envvar="IBN_USERNAME"),
    password: str = typer.Option("admin", envvar="IBN_PASSWORD"),
    content_dir: Optional[Path] = typer.Option(
        None, help="Serve artifact content from <dir>/<target>.cfg instead of Infrahub storage"
    ),
    check: bool = typer.Option(False, "--check", help="dry_run only; never apply"),
    stage: Optional[int] = typer.Option(None, help="Run only this stage (1-based)"),
    evidence: Optional[Path] = typer.Option(None, help="Evidence JSONL path"),
) -> None:
    """Execute (or --check) an approved Plan against the network."""
    plan = Plan.model_validate(yaml.safe_load(plan_path.read_text()))
    evidence_path = evidence or Path(f"evidence-{plan.id}.jsonl")
    inventory = SotInventory(infrahub_url, infrahub_token or "", username, password)

    typer.echo(f"plan {plan.id}  ({plan.source.base_branch} -> {plan.source.candidate_branch})")
    typer.echo(f"blast radius: {plan.blast_radius.classification.value} "
               f"({plan.blast_radius.device_count} devices); "
               f"strategy: {plan.policy_evaluation.canary_strategy}")
    if plan.removed_targets:
        typer.echo(f"removed targets (NOT touched, decommission explicitly): "
                   f"{', '.join(plan.removed_targets)}")
    typer.echo(f"evidence -> {evidence_path}")

    failures = 0
    for index, plan_stage in enumerate(plan.stages, start=1):
        if stage is not None and index != stage:
            continue
        typer.echo(f"\n== stage {index}/{len(plan.stages)}: {plan_stage.name} "
                   f"({len(plan_stage.steps)} step(s))")

        for step in plan_stage.steps:
            target = step.target.control_point
            prefix = f"  {target} [{step.artifact_definition}]"

            try:
                connection = inventory.connection_for(target)
            except KeyError as exc:
                typer.echo(f"{prefix} SKIP: {exc}")
                failures += 1
                continue

            if content_dir is not None:
                content = (content_dir / f"{target}.cfg").read_text()
            elif step.storage_id:
                content = inventory.fetch_content(step.storage_id)
            else:
                typer.echo(f"{prefix} SKIP: no storage_id and no --content-dir")
                failures += 1
                continue

            outcome = run_step(step, connection, content, check=check,
                               emit=lambda record: _emit(evidence_path, record))

            if outcome.status == "skipped":
                typer.echo(f"{prefix} SKIP: {outcome.detail}")
                failures += 1
            elif outcome.status == "converged":
                typer.echo(f"{prefix} dry_run: no diff - already converged")
            elif outcome.status == "checked":
                head = "\n".join(outcome.diff.splitlines()[:12])
                typer.echo(f"{prefix} dry_run diff:\n{head}" if head
                           else f"{prefix} --check: {outcome.detail}")
            elif outcome.status == "applied":
                typer.echo(f"{prefix} APPLIED {outcome.change_id} "
                           f"(snapshot {outcome.snapshot_id})")
            else:  # failed | rolled_back
                typer.echo(f"{prefix} {outcome.status.upper()}: {outcome.detail}")
                failures += 1
                if outcome.status == "failed" and "checksum" in outcome.detail:
                    typer.echo("  ABORT: content does not match the plan")
                    raise typer.Exit(2)
                if step.abort_on_failure:
                    typer.echo("  abort_on_failure: stopping plan")
                    raise typer.Exit(2)

        gate = plan_stage.gate
        typer.echo(f"  gate: {gate.kind} (soak {gate.soak_minutes}m) - "
                   f"evaluated by ibn-orchestrate dispatch, not by ibnctl")

    typer.echo(f"\ndone. failures: {failures}")
    raise typer.Exit(1 if failures else 0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
