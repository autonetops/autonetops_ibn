"""ibnctl apply — drive a Plan through the executor, step by step."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from autonetops_executor import available_drivers, get_driver_class
from autonetops_planner.models import Plan

app = typer.Typer(help=__doc__, no_args_is_help=True)

DEVICE_QUERY = """
query Device($name: String!) {
  DcimDevice(name__value: $name) {
    edges {
      node {
        name { value }
        primary_address { node { address { value } } }
        platform { node { name { value } netmiko_device_type { value } } }
      }
    }
  }
}
"""


class Inventory:
    """control_point -> connection dict, resolved from the Infrahub SoT."""

    def __init__(self, address: str, token: str, username: str, password: str):
        from infrahub_sdk import Config, InfrahubClientSync

        self._client = InfrahubClientSync(address=address, config=Config(api_token=token))
        self._username = username
        self._password = password

    def connection_for(self, control_point: str) -> dict[str, Any]:
        result = self._client.execute_graphql(
            query=DEVICE_QUERY, variables={"name": control_point}
        )
        edges = result["DcimDevice"]["edges"]
        if not edges:
            raise KeyError(f"control point {control_point!r} not found in the SoT")
        node = edges[0]["node"]
        primary = (node.get("primary_address") or {}).get("node")
        if not primary:
            raise KeyError(f"{control_point} has no primary_address in the SoT")
        return {
            "host": primary["address"]["value"].split("/")[0],
            "username": self._username,
            "password": self._password,
        }

    def fetch_content(self, storage_id: str) -> str:
        return self._client.object_store.get(identifier=storage_id)


def _verify_checksum(content: str, expected: str) -> bool:
    digest = hashlib.md5 if len(expected) == 32 else hashlib.sha256
    return digest(content.encode()).hexdigest() == expected


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
    inventory = Inventory(infrahub_url, infrahub_token or "", username, password)

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

            if step.driver not in available_drivers():
                # undeliverable, not failed: nothing was attempted on the box.
                # Reported + nonzero exit, but the rest of the plan proceeds.
                typer.echo(f"{prefix} SKIP: no executor driver for "
                           f"driver={step.driver!r} platform={step.platform!r}")
                _emit(evidence_path, {
                    "operation": "skip", "target": target,
                    "reason": f"no driver {step.driver!r}", "success": False,
                })
                failures += 1
                continue

            try:
                connection = inventory.connection_for(target)
            except KeyError as exc:
                typer.echo(f"{prefix} SKIP: {exc}")
                failures += 1
                continue

            if content_dir is not None:
                content = (content_dir / f"{target}.cfg").read_text()
            else:
                if not step.storage_id:
                    typer.echo(f"{prefix} SKIP: no storage_id and no --content-dir")
                    failures += 1
                    continue
                content = inventory.fetch_content(step.storage_id)

            if not _verify_checksum(content, step.checksum_after):
                typer.echo(f"{prefix} ABORT: content checksum does not match the plan")
                raise typer.Exit(2)

            from autonetops_executor.models import ArtifactPayload

            artifact = ArtifactPayload(
                definition=step.artifact_definition,
                checksum=step.checksum_after,
                content=content,
            )
            driver = get_driver_class(step.driver)(target, connection)

            snap = driver.snapshot()
            _emit(evidence_path, snap.evidence)
            typer.echo(f"{prefix} snapshot {snap.snapshot_id}")

            if driver.capabilities.supports_dry_run:
                diff = driver.dry_run(artifact)
                _emit(evidence_path, diff.evidence)
                if not diff.changed:
                    typer.echo(f"{prefix} dry_run: no diff - already converged, skipping apply")
                    continue
                head = "\n".join(diff.diff.splitlines()[:12])
                typer.echo(f"{prefix} dry_run diff:\n{head}")

            if check:
                typer.echo(f"{prefix} --check: not applying")
                continue

            try:
                pending = driver.apply(artifact)
                _emit(evidence_path, pending.evidence)
                typer.echo(f"{prefix} APPLIED {pending.change_id} "
                           f"(rollback: {pending.rollback_strategy})")
                if pending.confirm_deadline_seconds:
                    confirmation = driver.confirm(pending.change_id)
                    _emit(evidence_path, confirmation)
                    typer.echo(f"{prefix} confirmed")
            except Exception as exc:  # noqa: BLE001 - rollback then abort
                typer.echo(f"{prefix} APPLY FAILED: {exc}")
                rollback = driver.rollback(snap.snapshot_id)
                _emit(evidence_path, rollback)
                typer.echo(f"{prefix} rolled back to {snap.snapshot_id}")
                failures += 1
                if step.abort_on_failure:
                    typer.echo("  abort_on_failure: stopping plan")
                    raise typer.Exit(2)

        gate = plan_stage.gate
        typer.echo(f"  gate: {gate.kind} (soak {gate.soak_minutes}m) - "
                   f"not evaluated, validator pending; verify expectations manually")

    typer.echo(f"\ndone. failures: {failures}")
    raise typer.Exit(1 if failures else 0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
