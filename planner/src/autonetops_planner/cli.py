"""autonetops-planner CLI.

Commands:
  plan           Diff two branches' artifacts and emit a Plan (YAML).
  validate-pack  Validate an intent profile pack (ADR-0016) - the CI gate.
  export-schema  Regenerate contracts/*/plan|profile JSON Schemas.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

import typer
import yaml

from .artifact_source import ArtifactSource, InfrahubArtifactSource, StaticArtifactSource
from .change_classes import classify_changes
from .diffing import diff_artifacts
from .models import ChangeItem, ChangeSet, ContentFormat, Plan
from .plan_builder import PlanBuildError, build_plan
from .policies import select_strategy
from .profile import (
    IntentProfileDoc,
    ProfileError,
    ResolvedProfile,
    load_profile,
)

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
        None,
        envvar="IBN_POLICIES_DIR",
        help="Policy pack (dir with profile.yaml) or legacy policy YAML dir",
    ),
    tenant: Optional[str] = typer.Option(
        None, envvar="IBN_TENANT", help="Tenant guard: refuse packs of another tenant"
    ),
    output: Optional[Path] = typer.Option(None, "-o", help="Write plan YAML here"),
) -> None:
    """Diff BASE vs CANDIDATE artifacts and emit a Plan."""
    try:
        profile = load_profile(policies_dir, tenant=tenant)
    except ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    source: ArtifactSource
    if fixture is not None:
        source = StaticArtifactSource(fixture)
    elif infrahub_url and infrahub_token:
        source = InfrahubArtifactSource(
            infrahub_url,
            infrahub_token,
            sot=profile.sot,
            definition_formats=profile.definition_formats,
            strict=profile.strict,
        )
    else:
        raise typer.BadParameter("provide --fixture, or --infrahub-url and --infrahub-token")

    changes = diff_artifacts(
        source.list_artifacts(base), source.list_artifacts(candidate), base, candidate
    )
    if not changes.items:
        typer.echo("No artifact differences; nothing to plan.")
        raise typer.Exit(0)

    from .blast_radius import compute_blast_radius

    strategy = select_strategy(
        profile.strategies,
        compute_blast_radius(changes, profile.thresholds).classification,
    )
    try:
        plan = build_plan(changes, strategy, profile=profile)
    except PlanBuildError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    plan.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    doc = yaml.safe_dump(plan.model_dump(mode="json", by_alias=True), sort_keys=False)
    if output:
        output.write_text(doc)
        typer.echo(f"{plan.id} written to {output}")
    else:
        typer.echo(doc)


# -- validate-pack -----------------------------------------------------------


def _golden_fixture_findings(pack_dir: Path, profile: ResolvedProfile) -> list[str]:
    """ADR-0016 gate 5: every enabled change class carries executable proof.

    Fixture files live in tests/change_classes/<class>.match.yaml and
    <class>.refuse.yaml: {artifact_definition, content_format, before, after}.
    The match fixture must classify INTO the class; the refuse fixture must
    not. A class without both fixtures is invalid - the auto-approval
    surface is the one place a warning is not enough.
    """
    from .blast_radius import compute_blast_radius

    findings: list[str] = []
    fixtures_dir = pack_dir / "tests" / "change_classes"
    for cls in profile.change_classes.classes:
        if not cls.enabled:
            continue
        for kind in ("match", "refuse"):
            path = fixtures_dir / f"{cls.name}.{kind}.yaml"
            if not path.exists():
                findings.append(
                    f"change class {cls.name!r}: missing golden fixture "
                    f"tests/change_classes/{cls.name}.{kind}.yaml"
                )
                continue
            try:
                doc = yaml.safe_load(path.read_text()) or {}
                before, after = str(doc["before"]), str(doc["after"])
                item = ChangeItem(
                    target="golden-test",
                    definition=str(doc["artifact_definition"]),
                    checksum_before=hashlib.sha256(before.encode()).hexdigest(),
                    checksum_after=hashlib.sha256(after.encode()).hexdigest(),
                    content_format=ContentFormat(doc.get("content_format", "cli-text")),
                )
            except (KeyError, ValueError) as exc:
                findings.append(f"golden fixture {path.name}: malformed: {exc}")
                continue
            changes = ChangeSet(base_branch="golden-base", candidate_branch="golden",
                                items=[item])
            blast = compute_blast_radius(changes, profile.thresholds)
            result = classify_changes(
                changes, blast.classification, profile.change_classes,
                lambda _item: (before, after),
            )
            matched = result.change_class.name if result else None
            if kind == "match" and matched != cls.name:
                findings.append(
                    f"change class {cls.name!r}: match fixture classified as "
                    f"{matched!r} instead of the class itself"
                )
            if kind == "refuse" and matched == cls.name:
                findings.append(
                    f"change class {cls.name!r}: refuse fixture was NOT refused "
                    f"- the matcher is broader than its author believes"
                )
    return findings


def _sot_conformance_findings(
    profile: ResolvedProfile, infrahub_url: str, infrahub_token: str
) -> list[str]:
    """ADR-0016 gate 6 (advisory in pack CI, mandatory at onboarding):
    does the customer's Infrahub actually answer the declared bindings?"""
    findings: list[str] = []
    try:
        from infrahub_sdk import Config, InfrahubClientSync
    except ImportError:
        return ["sot check requested but infrahub-sdk is not installed "
                "(pip install autonetops-planner[infrahub])"]
    client = InfrahubClientSync(
        address=infrahub_url, config=Config(api_token=infrahub_token)
    )
    branch = profile.sot.default_base_branch
    try:
        result = client.execute_graphql(
            query="query { CoreArtifactDefinition { edges { node "
                  "{ artifact_name { value } } } } }",
            branch_name=branch,
        )
        known = {
            e["node"]["artifact_name"]["value"]
            for e in result["CoreArtifactDefinition"]["edges"]
        }
        for definition in profile.definition_formats:
            if definition not in known:
                findings.append(
                    f"artifact definition {definition!r} does not exist in the "
                    f"SoT (branch {branch!r}); known: {sorted(known) or 'none'}"
                )
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        findings.append(f"could not list artifact definitions: {exc}")
    try:
        source = InfrahubArtifactSource(
            infrahub_url, infrahub_token,
            sot=profile.sot, definition_formats=profile.definition_formats,
        )
        source.list_artifacts(branch)
    except Exception as exc:  # noqa: BLE001
        findings.append(
            f"artifact query with the declared sot binding failed on branch "
            f"{branch!r}: {exc}"
        )
    return findings


@app.command("validate-pack")
def validate_pack(
    pack_dir: Path = typer.Argument(..., help="Pack root (contains profile.yaml)"),
    infrahub_url: Optional[str] = typer.Option(None, envvar="INFRAHUB_ADDRESS"),
    infrahub_token: Optional[str] = typer.Option(None, envvar="INFRAHUB_API_TOKEN"),
) -> None:
    """Validate an intent profile pack (ADR-0016). This is the CI gate a
    customer pack must pass before the engine honors it; all findings are
    fatal except the SoT check, which runs only when Infrahub is reachable."""
    try:
        profile = load_profile(pack_dir)
    except ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    if profile.ref.source == "legacy-policies-dir":
        typer.echo(
            f"{pack_dir}: no profile.yaml - legacy mode (lenient, deprecated)."
        )
        for assumption in profile.load_assumptions:
            typer.echo(f"  assumption: {assumption}")
        raise typer.Exit(0)

    findings = _golden_fixture_findings(pack_dir, profile)
    if findings:
        for finding in findings:
            typer.echo(f"  - {finding}", err=True)
        raise typer.Exit(1)

    if infrahub_url and infrahub_token:
        sot_findings = _sot_conformance_findings(profile, infrahub_url, infrahub_token)
        for finding in sot_findings:
            typer.echo(f"  - sot: {finding}", err=True)
        if sot_findings:
            raise typer.Exit(1)

    ref = profile.ref
    typer.echo(
        f"pack ok: {ref.tenant}/{ref.name}@{ref.version} ({ref.checksum[:19]}...)\n"
        f"  strategies: {', '.join(s.name for s in profile.strategies)}\n"
        f"  change classes: "
        f"{', '.join(c.name for c in profile.change_classes.classes) or 'none'}\n"
        f"  platforms: {', '.join(sorted(profile.platforms)) or 'none'}"
    )


# -- export-schema -----------------------------------------------------------


@app.command("export-schema")
def export_schema(
    contract: str = typer.Option(
        "plan", "--contract", help="Which contract to export: plan | profile"
    ),
    output: Optional[Path] = typer.Option(None, "-o", help="Schema output path"),
) -> None:
    """Regenerate a contract JSON Schema from the pydantic models."""
    if contract == "plan":
        model, default_path = Plan, Path("contracts/plan/v1/plan.schema.json")
        schema_id = "https://autonetops.dev/contracts/plan/v1/plan.schema.json"
    elif contract == "profile":
        model, default_path = (
            IntentProfileDoc,
            Path("contracts/profile/v1/profile.schema.json"),
        )
        schema_id = "https://autonetops.dev/contracts/profile/v1/profile.schema.json"
    else:
        raise typer.BadParameter("contract must be 'plan' or 'profile'")
    target = output or default_path
    schema = model.model_json_schema(by_alias=True)
    schema["$id"] = schema_id
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    typer.echo(f"schema written to {target}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
