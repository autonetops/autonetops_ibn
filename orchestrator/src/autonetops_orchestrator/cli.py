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
from autonetops_planner.change_classes import classify_changes
from autonetops_planner.diffing import diff_artifacts
from autonetops_planner.models import Plan, PreApproval
from autonetops_planner.plan_builder import PlanBuildError, build_plan
from autonetops_planner.policies import select_strategy, strategy_by_name
from autonetops_planner.profile import ProfileError, ResolvedProfile, load_profile
from autonetops_validator import ExpectationSet

from .dispatch import DispatchOptions, dispatch_plan, write_report
from .feedback import record_dispatch
from .preapproval import recent_pre_approved, tighten_approvals
from .priority import intent_priority_for
from .render_source import RenderedArtifactSource
from .strategy import Decision, apply_to_plan, decide
from .timeline import evaluate_timeline
from .windows import load_windows

app = typer.Typer(help=__doc__, no_args_is_help=True)

DEFAULT_REPO = Path(os.environ.get("IBN_SOT_REPO", "/root/autonetops_infrahub"))
DEFAULT_PLANS_DIR = Path(os.environ.get("IBN_PLANS_DIR", "plans"))
# One policy source for plan AND dispatch: classification at plan time and
# re-verification at dispatch time must read the same reviewed data, or every
# pre-approval claim fails its re-check (ADR-0014). A dir with profile.yaml
# is an intent profile pack (ADR-0016); without one, legacy mode applies.
DEFAULT_POLICIES_DIR: Optional[Path] = (
    Path(os.environ["IBN_POLICIES_DIR"]) if os.environ.get("IBN_POLICIES_DIR") else None
)
# Tenant guard (ADR-0016): when set, packs and plan bundles of another tenant
# are refused loudly - cross-tenant reuse must never be quiet.
DEFAULT_TENANT: Optional[str] = os.environ.get("IBN_TENANT") or None


def _load_profile_or_exit(policies_dir: Optional[Path]) -> ResolvedProfile:
    """F14: an unloadable/invalid/tenant-mismatched pack stops the phase -
    never a silent fallback to builtin behavior."""
    try:
        return load_profile(policies_dir, tenant=DEFAULT_TENANT)
    except ProfileError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(4) from exc


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
    profile = _load_profile_or_exit(policies_dir)
    client = _client(infrahub_url, infrahub_token)
    source = RenderedArtifactSource(client, repo)

    typer.echo(f"rendering artifacts: base={base!r} candidate={candidate!r} ...")
    base_artifacts = source.list_artifacts(base)
    candidate_artifacts = source.list_artifacts(candidate)
    changes = diff_artifacts(base_artifacts, candidate_artifacts, base, candidate)
    if not changes.items:
        typer.echo("no artifact differences; nothing to plan")
        return None, None, None

    strategies = profile.strategies
    blast = compute_blast_radius(changes, profile.thresholds)

    # -- pre-approved change classes (ADR-0014): prove the diff is routine.
    #    Fail-closed: unfetchable bytes, emergency, or a spent rate limit all
    #    fall back to the normal approval path. Fetched pairs are cached so
    #    the base bytes can be frozen into the bundle below without a re-fetch.
    class_policy = profile.change_classes
    content_cache: dict[tuple[str, str], tuple[str, str]] = {}
    pre = None
    if class_policy.classes and not emergency:
        base_by_key = {(a.target, a.definition): a for a in base_artifacts}
        cand_by_key = {(a.target, a.definition): a for a in candidate_artifacts}

        def pair_for(item):
            key = (item.target, item.definition)
            if key in content_cache:
                return content_cache[key]
            before_art, after_art = base_by_key.get(key), cand_by_key.get(key)
            if before_art is None or after_art is None:
                return None
            try:
                pair = (source.fetch_content(before_art, branch=base),
                        source.fetch_content(after_art, branch=candidate))
            except Exception:  # noqa: BLE001 - unfetchable bytes fail closed
                return None
            content_cache[key] = pair
            return pair

        pre = classify_changes(changes, blast.classification, class_policy, pair_for)
        if pre and pre.change_class.max_plans_per_hour is not None:
            recent = recent_pre_approved(plans_dir, pre.change_class.name, now)
            if recent >= pre.change_class.max_plans_per_hour:
                typer.echo(
                    f"change class {pre.change_class.name!r} rate limit reached "
                    f"({recent} plan(s) in the last hour); normal approval path")
                pre = None

    if pre and pre.change_class.canary_strategy:
        strategy = strategy_by_name(strategies, pre.change_class.canary_strategy)
    else:
        strategy = select_strategy(strategies, blast.classification)
    try:
        plan = build_plan(
            changes, strategy,
            pre_approved=(PreApproval(class_name=pre.change_class.name,
                                      policy_version=pre.policy_version)
                          if pre else None),
            profile=profile)
    except PlanBuildError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    plan.created_at = now.isoformat(timespec="seconds")
    for assumption in plan.policy_evaluation.assumptions:
        typer.echo(f"  assumption: {assumption}")

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
    # profile.lock.yaml: the resolved profile frozen into the bundle -
    # symmetric with content_base/, for audit and re-derivation, never
    # authority (dispatch judges under the CURRENT profile, ADR-0016).
    (plan_dir / "profile.lock.yaml").write_text(yaml.safe_dump(
        {"ref": profile.ref.model_dump(mode="json"),
         "resolved": profile.resolved_doc},
        sort_keys=False))

    # one file per (target, definition): a target carrying two artifact
    # definitions (device-config + telemetry-subs) must not overwrite itself
    by_key = {(a.target, a.definition): a for a in candidate_artifacts}
    for stage in plan.stages:
        for step in stage.steps:
            artifact = by_key[(step.target.control_point, step.artifact_definition)]
            name = f"{artifact.target}__{artifact.definition}.cfg"
            (plan_dir / "content" / name).write_text(
                source.fetch_content(artifact, branch=candidate))
    for contract, text in source.render_expectations(candidate).items():
        (plan_dir / "expectations" / f"{contract}.yml").write_text(text)

    # pre-approved plans also freeze the BASE bytes: dispatch re-derives the
    # classification from the bundle alone (ADR-0014) - the branches may be
    # gone, and decision.yaml is not integrity-protected
    if plan.policy_evaluation.pre_approved:
        (plan_dir / "content_base").mkdir(exist_ok=True)
        for stage in plan.stages:
            for step in stage.steps:
                key = (step.target.control_point, step.artifact_definition)
                name = f"{key[0]}__{key[1]}.cfg"
                (plan_dir / "content_base" / name).write_text(content_cache[key][0])

    # -- human summary ---------------------------------------------------
    typer.echo(f"\nplan {plan.id}")
    typer.echo(f"  blast radius : {blast.classification.value} "
               f"({blast.device_count} devices: {', '.join(blast.devices)})")
    typer.echo(f"  strategy     : {strategy.name}")
    if pre:
        typer.echo(f"  pre-approved : change class {pre.change_class.name!r} "
                   f"(policy v{pre.policy_version})")
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
    policies_dir: Optional[Path] = typer.Option(DEFAULT_POLICIES_DIR, help="Planner policy YAML dir"),
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
    policies_dir: Optional[Path] = None,
) -> int:
    plan = Plan.model_validate(yaml.safe_load((plan_dir / "plan.yaml").read_text()))
    decision = Decision.model_validate(
        yaml.safe_load((plan_dir / "decision.yaml").read_text()))
    profile = _load_profile_or_exit(policies_dir)

    # -- fail-closed profile holds (ADR-0016, F14): a bundle planned under a
    #    real pack must dispatch under a real pack, and never under another
    #    tenant's. Nothing ran, nothing broke - exit 4 (approval-hold).
    recorded_profile = plan.policy_evaluation.profile
    if recorded_profile is not None:
        if DEFAULT_TENANT and recorded_profile.tenant not in (
                DEFAULT_TENANT, "_platform", "_legacy"):
            typer.echo(
                f"HOLD: bundle was planned for tenant "
                f"{recorded_profile.tenant!r}, this deployment is "
                f"{DEFAULT_TENANT!r} (IBN_TENANT) - refusing cross-tenant "
                f"dispatch", err=True)
            return 4
        if recorded_profile.source == "pack" and profile.ref.source != "pack":
            typer.echo(
                f"HOLD: bundle was planned under pack "
                f"{recorded_profile.name!r}@{recorded_profile.version} but no "
                f"pack is loaded now (set --policies-dir or IBN_POLICIES_DIR) "
                f"- refusing to dispatch under weaker policy", err=True)
            return 4

    # -- the approval bar can only tighten at dispatch time (ADR-0014 §5):
    #    decision.yaml is not integrity-protected, so a pre-approval claim is
    #    re-derived from the frozen bundle bytes and anything else is raised
    #    to the current floor before a single verb runs.
    required, notes, claim_verified = tighten_approvals(
        plan, decision, plan_dir, profile)
    for note in notes:
        typer.echo(f"approval bar: {note}")
    decision.approvals_required = required
    if claim_verified is False:
        # a failed claim must not reach the audit trail as an auto-approval:
        # whatever happens next was human-approved (or aborted), not the class
        decision.pre_approved_class = None

    client = _client(infrahub_url, infrahub_token)
    windows = load_windows(client)
    inventory = SotInventory(
        infrahub_url, infrahub_token, username, password,
        platform_drivers={
            platform: binding.driver
            for platform, binding in profile.platforms.items()
            if binding.driver
        },
    )

    expectation_docs = [p.read_text()
                        for p in sorted((plan_dir / "expectations").glob("*.yml"))]
    expectations = ExpectationSet.from_artifacts(expectation_docs)

    evidence_path = plan_dir / "evidence.jsonl"

    def emit(record) -> None:
        payload = (record.model_dump(mode="json")
                   if hasattr(record, "model_dump") else record)
        with evidence_path.open("a") as fh:
            fh.write(json.dumps(payload) + "\n")

    # -- profile drift is recorded, never blocking by itself (ADR-0016):
    #    the tighten-only rules above already re-proved everything that
    #    matters under the current pack; blocking on a checksum change
    #    would freeze operations on every pack bump.
    if (recorded_profile is not None
            and recorded_profile.checksum != profile.ref.checksum):
        drift = {
            "recorded": f"{recorded_profile.tenant}/{recorded_profile.name}"
                        f"@{recorded_profile.version} {recorded_profile.checksum}",
            "current": f"{profile.ref.tenant}/{profile.ref.name}"
                       f"@{profile.ref.version} {profile.ref.checksum}",
        }
        emit({"operation": "profile_drift", "target": plan.id,
              "success": True, "detail": drift})
        decision.reasons.append(
            f"profile drift: planned under {drift['recorded']}, "
            f"dispatched under {drift['current']}")
        typer.echo(f"profile drift: planned under {drift['recorded']}, "
                   f"dispatching under {drift['current']} (re-proved above)")

    def content_for(step) -> str:
        target = step.target.control_point
        candidates = (
            plan_dir / "content" / f"{target}__{step.artifact_definition}.cfg",
            plan_dir / "content" / f"{target}.cfg",  # pre-definition-suffix plans
        )
        for path in candidates:
            if path.exists():
                return path.read_text()
        raise KeyError(f"no saved content for {target!r}")

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
        driver_for=inventory.driver_for,
    )

    # -- the outcome is a record, not scrollback: report.yaml next to the
    #    plan, and (unless this was a --check) an OpsPlanRecord in the SoT.
    report_path = write_report(plan_dir, report)
    typer.echo(f"report -> {report_path}")
    if not check:
        record_dispatch(client, plan, decision, report, emit=emit, echo=typer.echo)

    if report.waiting:
        typer.echo("\nstopped: waiting on a window/manual gate (nothing failed)")
        return 3
    if report.aborted and report.aborted.startswith("missing approvals"):
        # 4 = approvals, not failure: watch holds the plan instead of
        # dead-ending it (nothing ran, nothing broke)
        typer.echo(f"\naborted: {report.aborted}")
        return 4
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
    policies_dir: Optional[Path] = typer.Option(
        DEFAULT_POLICIES_DIR, help="Planner policy YAML dir (approval floor + change classes)"),
    infrahub_url: str = InfrahubUrl,
    infrahub_token: str = InfrahubToken,
    username: str = typer.Option("admin", envvar="IBN_USERNAME"),
    password: str = typer.Option("admin", envvar="IBN_PASSWORD"),
) -> None:
    """Execute a saved plan; windows are re-checked at execution time."""
    raise typer.Exit(_dispatch(plan_dir, check, override_windows, wait,
                               soak_scale, approve,
                               infrahub_url, infrahub_token, username, password,
                               policies_dir=policies_dir))


@app.command("run")
def run_command(
    candidate: str = typer.Option(..., help="Candidate Infrahub branch"),
    base: str = typer.Option("main"),
    repo: Path = typer.Option(DEFAULT_REPO),
    policies_dir: Optional[Path] = typer.Option(DEFAULT_POLICIES_DIR),
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
                               infrahub_url, infrahub_token, username, password,
                               policies_dir=policies_dir))


@app.command("watch")
def watch_command(
    interval: int = typer.Option(15, help="Poll interval seconds"),
    once: bool = typer.Option(False, help="One pass, then exit (demo/CI)"),
    auto_dispatch: bool = typer.Option(
        True, help="Dispatch plans when their proposed change merges"),
    repo: Path = typer.Option(DEFAULT_REPO),
    plans_dir: Path = typer.Option(DEFAULT_PLANS_DIR),
    policies_dir: Optional[Path] = typer.Option(
        DEFAULT_POLICIES_DIR, help="Planner policy YAML dir - custom strategies and "
                   "pre-approved change classes apply in the automated path"),
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
            "main", branch, repo, policies_dir, plans_dir, None, False,
            infrahub_url, infrahub_token),
        dispatch_fn=lambda plan_dir: _dispatch(
            plan_dir, False, False, False, soak_scale, [],
            infrahub_url, infrahub_token, username, password,
            policies_dir=policies_dir),
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
