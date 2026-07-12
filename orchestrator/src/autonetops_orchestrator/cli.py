"""ibn-orchestrate — the orchestrator flow, one command per phase.

  windows   show SoT change windows and their next occurrences
  plan      render branch vs base, build Plan, evaluate timeline, decide
  dispatch  execute a saved plan (windows re-checked at execution time)
  run       plan + dispatch in one motion
  watch     follow Infrahub proposed changes: plan on open, dispatch on merge

The plan directory (plans/<plan-id>/) is the hand-off contract between the
phases: plan.yaml + timeline.yaml + decision.yaml + content/ + expectations/.
Everything the dispatcher needs is inside - a merged (deleted) branch can no
longer change what was approved.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Optional

import typer
import yaml

from autonetops_executor.inventory import SotInventory
from autonetops_planner.blast_radius import compute_blast_radius
from autonetops_planner.diffing import diff_artifacts
from autonetops_planner.models import Plan
from autonetops_planner.plan_builder import build_plan
from autonetops_planner.policies import (
    load_canary_strategies,
    load_delivery_preferences,
    select_strategy,
)
from autonetops_validator import ExpectationSet

from .dispatch import DispatchOptions, dispatch_plan
from .priority import intent_priority_for
from .render_source import RenderedArtifactSource
from .strategy import Decision, apply_to_plan, decide
from .timeline import Timeline, evaluate_timeline
from .windows import load_windows, next_slot

app = typer.Typer(help=__doc__, no_args_is_help=True)

DEFAULT_REPO = Path(os.environ.get("IBN_SOT_REPO", "/root/autonetops_infrahub"))
DEFAULT_PLANS_DIR = Path(os.environ.get("IBN_PLANS_DIR", "plans"))


def _client(url: str, token: str):
    from infrahub_sdk import Config, InfrahubClientSync

    return InfrahubClientSync(address=url, config=Config(api_token=token))


def _now(at: Optional[str]) -> datetime.datetime:
    if at:
        parsed = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    return datetime.datetime.now(datetime.timezone.utc)


def _dump(path: Path, model) -> None:
    path.write_text(yaml.safe_dump(
        model.model_dump(mode="json", by_alias=True), sort_keys=False))


InfrahubUrl = typer.Option("http://localhost:8000", envvar="INFRAHUB_ADDRESS")
InfrahubToken = typer.Option(..., envvar="INFRAHUB_API_TOKEN")


@app.command("windows")
def windows_command(
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
    at: Optional[str] = typer.Option(None, help="Evaluate as if now were this ISO time"),
) -> None:
    """List SoT change windows and when each next opens."""
    now = _now(at)
    for window in load_windows(_client(infrahub_url, infrahub_token)):
        occurrence = next(iter(window.occurrences(now)), None)
        when = (f"{occurrence[0].isoformat()} .. {occurrence[1].isoformat()}"
                if occurrence else "no upcoming occurrence")
        scope = ", ".join(sorted(window.devices)) or "all devices"
        typer.echo(f"{window.name:32} {window.window_type:12} "
                   f"max_blast={window.max_blast_radius:9} next: {when}")
        typer.echo(f"{'':32} scope: {scope}")


def _build(
    base: str, candidate: str, repo: Path, policies_dir: Optional[Path],
    plans_dir: Path, at: Optional[str], emergency: bool,
    infrahub_url: str, infrahub_token: str,
) -> tuple[Optional[Path], Optional[Plan], Optional[Decision]]:
    """The plan phase; returns (plan_dir, plan, decision) or Nones when
    there is nothing to deploy."""
    now = _now(at)
    client = _client(infrahub_url, infrahub_token)
    source = RenderedArtifactSource(client, repo)

    typer.echo(f"rendering artifacts: base={base!r} candidate={candidate!r} ...")
    base_artifacts = source.list_artifacts(base)
    candidate_artifacts = source.list_artifacts(candidate)
    changes = diff_artifacts(base_artifacts, candidate_artifacts, base, candidate)
    if not changes.items:
        typer.echo("no artifact differences; nothing to plan")
        return None, None, None

    strategies = load_canary_strategies(policies_dir)
    blast = compute_blast_radius(changes)
    strategy = select_strategy(strategies, blast.classification)
    plan = build_plan(changes, strategy, load_delivery_preferences(policies_dir))
    plan.created_at = now.isoformat(timespec="seconds")

    windows = load_windows(client)
    timeline = evaluate_timeline(plan, windows, now=now)
    priority, intents = intent_priority_for(client, set(blast.devices), branch=candidate)
    decision = decide(plan, timeline, now=now, priority=priority,
                      emergency=emergency, strategies=strategies)
    if intents:
        decision.reasons.append(
            f"priority {priority!r} inherited from intent(s): " + ", ".join(intents))
    apply_to_plan(plan, decision)

    plan_dir = plans_dir / plan.id
    (plan_dir / "content").mkdir(parents=True, exist_ok=True)
    (plan_dir / "expectations").mkdir(exist_ok=True)
    _dump(plan_dir / "plan.yaml", plan)
    _dump(plan_dir / "timeline.yaml", timeline)
    _dump(plan_dir / "decision.yaml", decision)

    by_target = {a.target: a for a in candidate_artifacts}
    for stage in plan.stages:
        for step in stage.steps:
            artifact = by_target[step.target.control_point]
            (plan_dir / "content" / f"{artifact.target}.cfg").write_text(
                source.fetch_content(artifact, branch=candidate))
    for contract, text in source.render_expectations(candidate).items():
        (plan_dir / "expectations" / f"{contract}.yml").write_text(text)

    # -- human summary ---------------------------------------------------
    typer.echo(f"\nplan {plan.id}")
    typer.echo(f"  blast radius : {blast.classification.value} "
               f"({blast.device_count} devices: {', '.join(blast.devices)})")
    typer.echo(f"  strategy     : {strategy.name}")
    typer.echo(f"  priority     : {priority}" +
               (f" (from {', '.join(intents)})" if intents else ""))
    for entry in timeline.entries:
        when = (f"{entry.starts_at.isoformat()} via {entry.window}"
                if entry.starts_at else "UNSCHEDULABLE")
        notes = f"  [{'; '.join(entry.notes)}]" if entry.notes else ""
        typer.echo(f"  {entry.stage:28} -> {when}{notes}")
    if plan.removed_targets:
        typer.echo(f"  removed targets (decommission explicitly): "
                   f"{', '.join(plan.removed_targets)}")
    typer.echo(f"  decision     : {decision.mode}")
    for reason in decision.reasons:
        typer.echo(f"      - {reason}")
    typer.echo(f"  saved to     : {plan_dir}/")
    return plan_dir, plan, decision


@app.command("plan")
def plan_command(
    candidate: str = typer.Option(..., help="Candidate Infrahub branch"),
    base: str = typer.Option("main", help="Base (deployed) branch"),
    repo: Path = typer.Option(DEFAULT_REPO, help="SoT repo checkout (queries/ + transforms/)"),
    policies_dir: Optional[Path] = typer.Option(None, help="Planner policy YAML dir"),
    plans_dir: Path = typer.Option(DEFAULT_PLANS_DIR),
    at: Optional[str] = typer.Option(None, help="Evaluate timeline as if now were this ISO time"),
    emergency: bool = typer.Option(False, help="Record an emergency override (critical intents only)"),
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
) -> None:
    """Render, diff, build the Plan, evaluate its timeline, decide."""
    _build(base, candidate, repo, policies_dir, plans_dir, at, emergency,
           infrahub_url, infrahub_token)


def _dispatch(
    plan_dir: Path, check: bool, override_windows: bool, wait: bool,
    soak_scale: float, approvals: list[str],
    infrahub_url: str, infrahub_token: str, username: str, password: str,
) -> int:
    plan = Plan.model_validate(yaml.safe_load((plan_dir / "plan.yaml").read_text()))
    decision = Decision.model_validate(
        yaml.safe_load((plan_dir / "decision.yaml").read_text()))

    client = _client(infrahub_url, infrahub_token)
    windows = load_windows(client)
    inventory = SotInventory(infrahub_url, infrahub_token, username, password)

    expectation_docs = [p.read_text()
                        for p in sorted((plan_dir / "expectations").glob("*.yml"))]
    expectations = ExpectationSet.from_artifacts(expectation_docs)

    evidence_path = plan_dir / "evidence.jsonl"

    def emit(record) -> None:
        payload = (record.model_dump(mode="json")
                   if hasattr(record, "model_dump") else record)
        with evidence_path.open("a") as fh:
            fh.write(json.dumps(payload) + "\n")

    def content_for(step) -> str:
        path = plan_dir / "content" / f"{step.target.control_point}.cfg"
        if not path.exists():
            raise KeyError(f"no saved content for {step.target.control_point!r}")
        return path.read_text()

    typer.echo(f"plan {plan.id} ({plan.source.base_branch} -> "
               f"{plan.source.candidate_branch})")
    typer.echo(f"decision: {decision.mode}; evidence -> {evidence_path}")

    report = dispatch_plan(
        plan, decision,
        windows=windows,
        connection_for=inventory.connection_for,
        content_for=content_for,
        expectations=expectations,
        emit=emit,
        echo=typer.echo,
        options=DispatchOptions(
            check=check, override_windows=override_windows, wait=wait,
            soak_scale=soak_scale, approvals=tuple(approvals),
        ),
    )

    if report.waiting:
        typer.echo("\nstopped: waiting on a window/manual gate (nothing failed)")
        return 3
    if report.aborted:
        typer.echo(f"\naborted: {report.aborted}")
        return 2
    typer.echo(f"\ndone. failures: {report.failures}")
    return 2 if report.failures else 0


@app.command("dispatch")
def dispatch_command(
    plan_dir: Path = typer.Option(..., help="plans/<plan-id> directory from `plan`"),
    check: bool = typer.Option(False, "--check", help="dry_run only; never apply"),
    override_windows: bool = typer.Option(
        False, help="Ignore change windows (lab only; the override is recorded)"),
    wait: bool = typer.Option(False, help="Sleep until each window opens"),
    soak_scale: float = typer.Option(
        1.0, help="Multiply soak times (0.01 turns 30m into 18s for demos)"),
    approve: list[str] = typer.Option([], help="Approval name (repeatable)"),
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
    username: str = typer.Option("admin", envvar="IBN_USERNAME"),
    password: str = typer.Option("admin", envvar="IBN_PASSWORD"),
) -> None:
    """Execute a saved plan; windows are re-checked at execution time."""
    raise typer.Exit(_dispatch(plan_dir, check, override_windows, wait,
                               soak_scale, approve,
                               infrahub_url, infrahub_token, username, password))


@app.command("run")
def run_command(
    candidate: str = typer.Option(..., help="Candidate Infrahub branch"),
    base: str = typer.Option("main"),
    repo: Path = typer.Option(DEFAULT_REPO),
    policies_dir: Optional[Path] = typer.Option(None),
    plans_dir: Path = typer.Option(DEFAULT_PLANS_DIR),
    check: bool = typer.Option(False, "--check"),
    override_windows: bool = typer.Option(False),
    wait: bool = typer.Option(False),
    soak_scale: float = typer.Option(1.0),
    approve: list[str] = typer.Option([]),
    emergency: bool = typer.Option(False),
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
    username: str = typer.Option("admin", envvar="IBN_USERNAME"),
    password: str = typer.Option("admin", envvar="IBN_PASSWORD"),
) -> None:
    """plan + dispatch in one motion."""
    plan_dir, _plan, _decision = _build(
        base, candidate, repo, policies_dir, plans_dir, None, emergency,
        infrahub_url, infrahub_token)
    if plan_dir is None:
        raise typer.Exit(0)
    raise typer.Exit(_dispatch(plan_dir, check, override_windows, wait,
                               soak_scale, approve,
                               infrahub_url, infrahub_token, username, password))


@app.command("watch")
def watch_command(
    interval: int = typer.Option(15, help="Poll interval seconds"),
    once: bool = typer.Option(False, help="One pass, then exit (demo/CI)"),
    auto_dispatch: bool = typer.Option(
        True, help="Dispatch plans when their proposed change merges"),
    repo: Path = typer.Option(DEFAULT_REPO),
    plans_dir: Path = typer.Option(DEFAULT_PLANS_DIR),
    soak_scale: float = typer.Option(1.0),
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
    username: str = typer.Option("admin", envvar="IBN_USERNAME"),
    password: str = typer.Option("admin", envvar="IBN_PASSWORD"),
) -> None:
    """Follow Infrahub proposed changes: plan on open, dispatch on merge."""
    from .watch import watch_loop

    watch_loop(
        client=_client(infrahub_url, infrahub_token),
        plan_fn=lambda branch: _build(
            "main", branch, repo, None, plans_dir, None, False,
            infrahub_url, infrahub_token),
        dispatch_fn=lambda plan_dir: _dispatch(
            plan_dir, False, False, False, soak_scale, [],
            infrahub_url, infrahub_token, username, password),
        plans_dir=plans_dir,
        interval=interval,
        once=once,
        auto_dispatch=auto_dispatch,
        echo=typer.echo,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
