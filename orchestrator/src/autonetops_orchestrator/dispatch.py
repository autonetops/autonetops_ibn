"""Dispatch: drive an approved Plan through the executor, honoring windows,
gates and soak - the deploy flow of ADR-0005, as a plain library.

The boundary rules hold: run_step() (executor) performs the device-level
operations; everything here is sequence and reaction. Prefect can wrap
these functions later without touching them.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from autonetops_executor import get_driver_class, run_step
from autonetops_validator import ExpectationSet, evaluate_sessions, failing_keys

from .strategy import Decision
from .windows import ChangeWindow, next_slot


@dataclass
class DispatchOptions:
    check: bool = False  # dry_run everywhere, never apply
    override_windows: bool = False  # lab/emergency: ignore scheduling
    wait: bool = False  # sleep until the window opens instead of exiting
    soak_scale: float = 1.0  # workshop compression of soak_minutes
    approvals: tuple[str, ...] = ()
    horizon_days: int = 14


@dataclass
class StageReport:
    name: str
    outcomes: dict[str, str] = field(default_factory=dict)  # target -> status
    gate_passed: bool | None = None
    gate_summary: str | None = None
    scheduled_at: datetime.datetime | None = None
    window: str | None = None


@dataclass
class DispatchReport:
    plan_id: str
    stages: list[StageReport] = field(default_factory=list)
    failures: int = 0
    aborted: str | None = None  # reason, when the plan stopped early
    waiting: bool = False  # stopped because a window is not open yet

    @property
    def ok(self) -> bool:
        return self.aborted is None and self.failures == 0 and not self.waiting


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def collect_facts(
    devices: list[str],
    driver_by_device: dict[str, str],
    connection_for: Callable[[str], dict[str, Any]],
    emit: Callable[[Any], None],
) -> dict[str, dict[str, Any] | None]:
    """Per-device facts through the executor verb contract; None marks a
    device nobody could observe (no driver, unreachable) - the validator
    reports those as unverifiable, never as passing."""
    facts: dict[str, dict[str, Any] | None] = {}
    for device in devices:
        driver_name = driver_by_device.get(device)
        if not driver_name:
            facts[device] = None
            continue
        try:
            driver = get_driver_class(driver_name)(device, connection_for(device))
            result = driver.get_facts()
            emit(result.evidence)
            facts[device] = result.facts
        except Exception as exc:  # noqa: BLE001 - unobservable, not fatal
            emit({"operation": "get_facts", "target": device,
                  "success": False, "detail": {"error": str(exc)}})
            facts[device] = None
    return facts


def dispatch_plan(
    plan,
    decision: Decision,
    *,
    windows: list[ChangeWindow],
    connection_for: Callable[[str], dict[str, Any]],
    content_for: Callable[[Any], str],
    expectations: ExpectationSet,
    emit: Callable[[Any], None],
    echo: Callable[[str], None],
    options: DispatchOptions,
    now_fn: Callable[[], datetime.datetime] = _utc_now,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DispatchReport:
    report = DispatchReport(plan_id=plan.id)
    blast = plan.blast_radius.classification.value

    missing = [a for a in decision.approvals_required if a not in options.approvals]
    if missing and not options.check:
        report.aborted = "missing approvals: " + ", ".join(missing)
        echo(f"ABORT: {report.aborted}")
        return report

    if decision.emergency_override:
        emit({"operation": "emergency_override", "plan": plan.id,
              "success": True, "detail": {"reasons": decision.reasons}})
        echo("!! emergency override on record - windows bypassed")

    # drivers for every control point in the plan: a gate may need to observe
    # a device from a later stage (a CE change is proven on its PE)
    plan_drivers: dict[str, str] = {
        step.target.control_point: step.driver
        for stage in plan.stages for step in stage.steps if step.driver
    }

    # -- baseline: gates block on REGRESSIONS, not on history. Expectations
    #    already failing before step one are pre-existing drift - reported
    #    loudly, chased by the reconcile loop, but no reason to abort a
    #    rollout that did not cause them.
    baseline: set[tuple[str, str, str]] = set()
    plan_devices = {
        d for stage in plan.stages for step in stage.steps
        for d in (step.target.affected_devices or [step.target.control_point])
    }
    baseline_scope = expectations.for_devices(plan_devices, include_neighbors=True)
    if baseline_scope.sessions and not options.check:
        observe = sorted({s.device for s in baseline_scope.sessions})
        facts = collect_facts(observe, plan_drivers, connection_for, emit)
        before = evaluate_sessions(baseline_scope, facts)
        baseline = failing_keys(before)
        emit({"operation": "gate_baseline", "target": plan.id,
              "success": True,
              "detail": {"checks": [c.model_dump() for c in before.checks]}})
        echo(f"baseline: {before.summary}")
        for check in before.checks:
            if check.status == "fail":
                echo(f"  pre-existing: {check.device} -> {check.neighbor_ip} "
                     f"({check.contract}) is {check.actual or 'absent'}; "
                     f"gates will not block on it")

    for index, stage in enumerate(plan.stages, start=1):
        stage_report = StageReport(name=stage.name)
        report.stages.append(stage_report)
        devices = sorted({
            d for step in stage.steps
            for d in (step.target.affected_devices or [step.target.control_point])
        })
        echo(f"\n== stage {index}/{len(plan.stages)}: {stage.name} "
             f"({len(stage.steps)} step(s); devices: {', '.join(devices)})")

        # -- WHEN: the window is re-checked at execution time, not trusted
        #    from planning time - windows are data and data changes.
        if not (options.override_windows or decision.emergency_override or options.check):
            now = now_fn()
            slot = next_slot(windows, set(devices), blast, now,
                             horizon_days=options.horizon_days)
            if slot is None:
                report.aborted = (f"stage {stage.name!r}: no eligible window "
                                  f"within {options.horizon_days} days")
                echo(f"ABORT: {report.aborted}")
                return report
            window, start, _end = slot
            stage_report.window = window.name
            if start > now:
                stage_report.scheduled_at = start
                if not options.wait:
                    report.waiting = True
                    echo(f"  window {window.name!r} opens {start.isoformat()}; "
                         f"re-run then (or --wait / --override-windows)")
                    return report
                delay = (start - now).total_seconds()
                echo(f"  waiting {int(delay)}s for window {window.name!r} ...")
                sleep_fn(delay)

        # -- steps: the executor's verb sequence, one step at a time
        applied_any = False
        for step in stage.steps:
            target = step.target.control_point
            prefix = f"  {target} [{step.artifact_definition}]"
            try:
                connection = connection_for(target)
            except KeyError as exc:
                echo(f"{prefix} SKIP: {exc}")
                report.failures += 1
                stage_report.outcomes[target] = "skipped"
                continue
            try:
                content = content_for(step)
            except KeyError as exc:
                echo(f"{prefix} SKIP: {exc}")
                report.failures += 1
                stage_report.outcomes[target] = "skipped"
                continue

            outcome = run_step(step, connection, content,
                               check=options.check, emit=emit)
            stage_report.outcomes[target] = outcome.status
            if outcome.status == "checked":
                head = "\n".join(outcome.diff.splitlines()[:12])
                echo(f"{prefix} --check diff:\n{head}" if head
                     else f"{prefix} --check: {outcome.detail}")
            elif outcome.status == "applied":
                applied_any = True
                echo(f"{prefix} APPLIED {outcome.change_id} "
                     f"(snapshot {outcome.snapshot_id})")
            elif outcome.status == "converged":
                echo(f"{prefix} no diff - already converged")
            else:
                echo(f"{prefix} {outcome.status.upper()}: {outcome.detail}")
                report.failures += 1
                if step.abort_on_failure and outcome.status in ("failed", "rolled_back"):
                    report.aborted = f"step {target} {outcome.status}: {outcome.detail}"
                    echo("  abort_on_failure: stopping plan")
                    return report

        # -- gate: soak, then compare expectations against live facts
        if options.check:
            echo(f"  gate: skipped (--check)")
            continue
        gate = stage.gate
        if gate.kind != "validator.expectations_pass":
            echo(f"  gate: {gate.kind} - manual gate, pausing here")
            report.waiting = True
            return report
        scoped = expectations.for_devices(set(devices), include_neighbors=True)
        if not scoped.sessions:
            stage_report.gate_passed = True
            stage_report.gate_summary = "no expectations scoped to this stage"
            echo(f"  gate: {stage_report.gate_summary}")
            continue
        soak_seconds = gate.soak_minutes * 60 * options.soak_scale
        if applied_any and soak_seconds > 0:
            echo(f"  gate: soaking {int(soak_seconds)}s "
                 f"(soak {gate.soak_minutes}m x scale {options.soak_scale})")
            sleep_fn(soak_seconds)
        observe = sorted({s.device for s in scoped.sessions})
        facts = collect_facts(observe, plan_drivers, connection_for, emit)
        result = evaluate_sessions(scoped, facts, baseline=baseline)
        stage_report.gate_passed = result.passed
        stage_report.gate_summary = result.summary
        emit({"operation": "gate", "target": stage.name,
              "success": result.passed,
              "detail": {"checks": [c.model_dump() for c in result.checks]}})
        markers = {"pass": "ok", "fail": "FAIL",
                   "pre_existing": "pre", "unverifiable": "??"}
        for check in result.checks:
            echo(f"    [{markers[check.status]}] {check.device} -> "
                 f"{check.neighbor_ip} ({check.contract}): "
                 f"{check.actual or 'unobserved'}")
        echo(f"  gate: {result.summary}")
        if not result.passed:
            report.aborted = (f"gate failed after {stage.name}: {result.summary}; "
                              f"snapshots are on the devices for manual revert")
            echo(f"ABORT: {report.aborted}")
            return report

    return report
