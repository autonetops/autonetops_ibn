"""autonetops-planner CLI.

Commands:
  plan           Diff two branches' artifacts and emit a Plan (YAML).
  export-schema  Regenerate contracts/plan/v1/plan.schema.json from the models.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

import typer
import yaml

from .artifact_source import ArtifactSource, InfrahubArtifactSource, StaticArtifactSource
from .diffing import diff_artifacts
from .models import Plan
from .plan_builder import build_plan
from .policies import load_canary_strategies, select_strategy

app = typer.Typer(help=__doc__, no_args_is_help=True)


@app.command("plan")
def plan_command(
    base: str = typer.Option("main", help="Base (deployed) branch"),
    candidate: str = typer.Option(..., help="Candidate Infrahub branch"),
    fixture: Optional[Path] = typer.Option(
        None, help="Static artifact fixture JSON (offline mode)"
    ),
    infrahub_url: Optional[str] = typer.Option(None, envvar="INFRAHUB_ADDRESS"),
    infrahub_token: Optional[str] = typer.Option(None, envvar="INFRAHUB_API_TOKEN"),
    policies_dir: Optional[Path] = typer.Option(
        None, help="Directory containing planner policy YAML files"
    ),
    output: Optional[Path] = typer.Option(None, "-o", help="Write plan YAML here"),
) -> None:
    """Diff BASE vs CANDIDATE artifacts and emit a Plan."""
    source: ArtifactSource
    if fixture is not None:
        source = StaticArtifactSource(fixture)
    elif infrahub_url and infrahub_token:
        source = InfrahubArtifactSource(infrahub_url, infrahub_token)
    else:
        raise typer.BadParameter("provide --fixture, or --infrahub-url and --infrahub-token")

    changes = diff_artifacts(
        source.list_artifacts(base), source.list_artifacts(candidate), base, candidate
    )
    if not changes.items:
        typer.echo("No artifact differences; nothing to plan.")
        raise typer.Exit(0)

    strategies = load_canary_strategies(policies_dir)
    from .blast_radius import compute_blast_radius

    strategy = select_strategy(strategies, compute_blast_radius(changes).classification)
    plan = build_plan(changes, strategy)
    plan.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    doc = yaml.safe_dump(plan.model_dump(mode="json", by_alias=True), sort_keys=False)
    if output:
        output.write_text(doc)
        typer.echo(f"{plan.id} written to {output}")
    else:
        typer.echo(doc)


@app.command("export-schema")
def export_schema(
    output: Path = typer.Option(
        Path("contracts/plan/v1/plan.schema.json"), "-o", help="Schema output path"
    ),
) -> None:
    """Regenerate the Plan JSON Schema from the pydantic models."""
    schema = Plan.model_json_schema(by_alias=True)
    schema["$id"] = "https://autonetops.dev/contracts/plan/v1/plan.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    typer.echo(f"schema written to {output}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
