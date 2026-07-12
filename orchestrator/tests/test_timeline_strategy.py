"""Timeline evaluation + dispatch decisions."""

from __future__ import annotations

import datetime
import hashlib

from autonetops_planner.models import (
    BlastRadius,
    BlastRadiusClass,
    Gate,
    Plan,
    PlanSource,
    PolicyEvaluation,
    RollbackSpec,
    Stage,
    Step,
    StepTarget,
)
from autonetops_planner.policies import CanaryStage, CanaryStrategy

from autonetops_orchestrator.strategy import apply_to_plan, decide
from autonetops_orchestrator.timeline import evaluate_timeline
from autonetops_orchestrator.windows import ChangeWindow

UTC = datetime.timezone.utc


def dt(spec: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(spec).replace(tzinfo=UTC)


def _step(target: str) -> Step:
    return Step(
        target=StepTarget(control_point=target),
        driver="mock",
        platform="mock",
        artifact_definition="device-configuration",
        checksum_after=hashlib.sha256(target.encode()).hexdigest(),
        rollback=RollbackSpec(strategy="commit_confirmed"),
    )


def _plan(classification=BlastRadiusClass.MODERATE) -> Plan:
    stages = [
        Stage(name="stage-1-one_target", steps=[_step("pe-emea-01")],
              gate=Gate(soak_minutes=30)),
        Stage(name="stage-2-remainder", steps=[_step("pe-emea-02")],
              gate=Gate(soak_minutes=0)),
    ]
    source = PlanSource(base_branch="main", candidate_branch="change")
    return Plan(
        id=Plan.deterministic_id(source, stages),
        source=source,
        blast_radius=BlastRadius(
            classification=classification,
            device_count=2,
            devices=["pe-emea-01", "pe-emea-02"],
        ),
        policy_evaluation=PolicyEvaluation(canary_strategy="builtin-single-target-canary"),
        stages=stages,
    )


TUESDAY_NIGHT = ChangeWindow(
    name="emea-standard-maintenance",
    days=("tuesday",), start_utc="21:00", duration_minutes=240,
    max_blast_radius="high",
)


def test_timeline_defers_to_window_and_chains_soak():
    now = dt("2026-07-13T09:00:00")  # Monday
    timeline = evaluate_timeline(_plan(), [TUESDAY_NIGHT], now=now)
    assert timeline.feasible
    first, second = timeline.entries
    assert first.starts_at == dt("2026-07-14T21:00:00")
    assert first.notes and "deferred" in first.notes[0]
    # stage 2 starts after stage 1's soak, inside the same window
    assert second.starts_at == first.soak_until
    assert second.window == "emea-standard-maintenance"


def test_timeline_infeasible_when_no_window_admits_blast():
    low_only = ChangeWindow(
        name="low-only", days=("monday",), start_utc="08:00",
        duration_minutes=600, max_blast_radius="low",
    )
    timeline = evaluate_timeline(_plan(), [low_only], now=dt("2026-07-13T09:00:00"))
    assert not timeline.feasible
    assert "no maintenance window" in timeline.reasons[0]


def test_decide_immediate_scheduled_blocked():
    plan = _plan()
    now = dt("2026-07-14T21:30:00")  # inside the Tuesday window
    timeline = evaluate_timeline(plan, [TUESDAY_NIGHT], now=now)
    assert decide(plan, timeline, now=now).mode == "immediate"

    now = dt("2026-07-13T09:00:00")  # Monday: window opens tomorrow
    timeline = evaluate_timeline(plan, [TUESDAY_NIGHT], now=now)
    decision = decide(plan, timeline, now=now)
    assert decision.mode == "scheduled"
    assert decision.starts_at == dt("2026-07-14T21:00:00")

    timeline = evaluate_timeline(plan, [], now=now)
    assert decide(plan, timeline, now=now).mode == "blocked"


def test_decide_needs_approval_from_strategy():
    plan = _plan()
    strategies = [CanaryStrategy(
        name="builtin-single-target-canary",
        applies_to=[BlastRadiusClass.MODERATE],
        stages=[CanaryStage(select="one_target")],
        requires_approvals=["platform-lead"],
    )]
    now = dt("2026-07-14T21:30:00")
    timeline = evaluate_timeline(plan, [TUESDAY_NIGHT], now=now)
    decision = decide(plan, timeline, now=now, strategies=strategies)
    assert decision.mode == "needs_approval"
    assert decision.approvals_required == ["platform-lead"]


def test_emergency_override_requires_critical():
    plan = _plan()
    now = dt("2026-07-13T09:00:00")
    timeline = evaluate_timeline(plan, [], now=now)  # blocked
    assert decide(plan, timeline, now=now, priority="high",
                  emergency=True).mode == "blocked"
    decision = decide(plan, timeline, now=now, priority="critical", emergency=True)
    assert decision.mode == "immediate"
    assert decision.emergency_override


def test_apply_to_plan_records_evaluation():
    plan = _plan()
    now = dt("2026-07-13T09:00:00")
    timeline = evaluate_timeline(plan, [TUESDAY_NIGHT], now=now)
    decision = decide(plan, timeline, now=now)
    apply_to_plan(plan, decision)
    assert "scheduled" in plan.policy_evaluation.change_window
    assert "emea-standard-maintenance" in plan.policy_evaluation.change_window
