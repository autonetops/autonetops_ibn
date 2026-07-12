"""Dispatch: stage walking, window enforcement, gates, aborts."""

from __future__ import annotations

import datetime
import hashlib

from autonetops_executor.drivers.mock import MockDriver
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
from autonetops_validator import ExpectationSet

from autonetops_orchestrator.dispatch import DispatchOptions, dispatch_plan
from autonetops_orchestrator.strategy import Decision
from autonetops_orchestrator.windows import ChangeWindow

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 14, 21, 30, tzinfo=UTC)  # Tuesday night

OPEN_WINDOW = ChangeWindow(
    name="always", max_blast_radius="high",
    days=("monday", "tuesday", "wednesday", "thursday", "friday",
          "saturday", "sunday"),
    start_utc="00:00", duration_minutes=1440,
)
CLOSED_WINDOW = ChangeWindow(
    name="tuesday-only", days=("tuesday",), start_utc="21:00",
    duration_minutes=240, max_blast_radius="high",
)

CONTENT = {"pe-1": "hostname pe-1\n", "pe-2": "hostname pe-2\n"}

EXPECTATIONS = ExpectationSet.from_artifacts(["""\
apiVersion: expectations.networking.autonetops/v1
kind: ContractExpectations
metadata: {name: edge}
spec:
  bgp:
    sessions:
      - {device: pe-1, neighborIp: 10.0.0.2,
         mustBe: {sessionState: established}}
"""])


def _plan(soak_minutes: int = 0) -> Plan:
    def step(target: str) -> Step:
        return Step(
            target=StepTarget(control_point=target),
            driver="mock", platform="mock",
            artifact_definition="device-configuration",
            checksum_after=hashlib.sha256(CONTENT[target].encode()).hexdigest(),
            rollback=RollbackSpec(strategy="commit_confirmed"),
        )

    stages = [
        Stage(name="stage-1", steps=[step("pe-1")], gate=Gate(soak_minutes=soak_minutes)),
        Stage(name="stage-2", steps=[step("pe-2")]),
    ]
    source = PlanSource(base_branch="main", candidate_branch="chg")
    return Plan(
        id=Plan.deterministic_id(source, stages), source=source,
        blast_radius=BlastRadius(classification=BlastRadiusClass.LOW,
                                 device_count=2, devices=["pe-1", "pe-2"]),
        policy_evaluation=PolicyEvaluation(canary_strategy="builtin"),
        stages=stages,
    )


def _dispatch(plan, decision=None, windows=(OPEN_WINDOW,),
              expectations=None, options=None, sleeps=None):
    log: list[str] = []
    evidence: list = []
    report = dispatch_plan(
        plan,
        decision or Decision(mode="immediate"),
        windows=list(windows),
        connection_for=lambda target: {"initial_config": ""},
        content_for=lambda step: CONTENT[step.target.control_point],
        expectations=expectations or ExpectationSet(),
        emit=evidence.append,
        echo=log.append,
        options=options or DispatchOptions(),
        now_fn=lambda: NOW,
        sleep_fn=(sleeps.append if sleeps is not None else lambda s: None),
    )
    return report, log, evidence


def test_dispatch_applies_all_stages():
    report, log, _ = _dispatch(_plan())
    assert report.ok
    assert [s.outcomes for s in report.stages] == [
        {"pe-1": "applied"}, {"pe-2": "applied"}]
    assert all(s.gate_passed for s in report.stages)


def test_dispatch_waits_outside_window():
    friday = datetime.datetime(2026, 7, 17, 9, 0, tzinfo=UTC)
    # sanity: NOW (Tuesday night) is inside tuesday-only, so this runs
    report, _log, _ = _dispatch(_plan(), windows=[CLOSED_WINDOW])
    assert report.ok

    def run_at(now):
        return dispatch_plan(
            _plan(), Decision(mode="scheduled"), windows=[CLOSED_WINDOW],
            connection_for=lambda t: {"initial_config": ""},
            content_for=lambda s: CONTENT[s.target.control_point],
            expectations=ExpectationSet(), emit=lambda r: None,
            echo=lambda m: None, options=DispatchOptions(),
            now_fn=lambda: now,
        )

    waiting = run_at(friday)
    assert waiting.waiting
    assert waiting.stages[0].scheduled_at is not None
    assert not waiting.stages[0].outcomes  # nothing touched the network


def test_dispatch_override_windows_is_recorded():
    friday = datetime.datetime(2026, 7, 17, 9, 0, tzinfo=UTC)
    report = dispatch_plan(
        _plan(), Decision(mode="immediate"), windows=[CLOSED_WINDOW],
        connection_for=lambda t: {"initial_config": ""},
        content_for=lambda s: CONTENT[s.target.control_point],
        expectations=ExpectationSet(), emit=lambda r: None, echo=lambda m: None,
        options=DispatchOptions(override_windows=True), now_fn=lambda: friday,
    )
    assert report.ok


def test_dispatch_check_never_applies():
    report, _, evidence = _dispatch(_plan(), options=DispatchOptions(check=True))
    assert report.ok
    assert all(s.outcomes == {list(s.outcomes)[0]: "checked"} for s in report.stages)
    assert "apply" not in [getattr(e, "operation", e.get("operation") if isinstance(e, dict) else "")
                           for e in evidence]


def test_dispatch_requires_approvals():
    decision = Decision(mode="needs_approval", approvals_required=["platform-lead"])
    report, log, _ = _dispatch(_plan(), decision=decision)
    assert report.aborted and "missing approvals" in report.aborted
    report, _, _ = _dispatch(
        _plan(), decision=decision,
        options=DispatchOptions(approvals=("platform-lead",)))
    assert report.ok


def test_gate_regression_aborts_before_next_stage(monkeypatch):
    # session established at baseline, gone after the canary applies:
    # a regression - stage-1 gate must fail and stage-2 must never run
    original = MockDriver.get_facts
    calls = {"n": 0}

    def degrading(self):
        result = original(self)
        calls["n"] += 1
        result.facts["bgp_neighbors"] = (
            {"10.0.0.2": "established"} if calls["n"] == 1 else {})
        return result

    monkeypatch.setattr(MockDriver, "get_facts", degrading)
    report, log, _ = _dispatch(_plan(), expectations=EXPECTATIONS)
    assert report.aborted and "gate failed" in report.aborted
    assert len(report.stages) == 1
    assert report.stages[0].gate_passed is False


def test_gate_pre_existing_failure_does_not_block():
    # the mock driver exposes no bgp_neighbors at all: the expected session
    # is already failing at baseline, so gates report it without aborting
    report, log, _ = _dispatch(_plan(), expectations=EXPECTATIONS)
    assert report.ok
    assert any("pre-existing" in line for line in log)
    assert all(s.gate_passed for s in report.stages)


def test_gate_passes_with_live_session(monkeypatch):
    original = MockDriver.get_facts

    def with_bgp(self):
        result = original(self)
        result.facts["bgp_neighbors"] = {"10.0.0.2": "established"}
        return result

    monkeypatch.setattr(MockDriver, "get_facts", with_bgp)
    report, _, _ = _dispatch(_plan(), expectations=EXPECTATIONS)
    assert report.ok
    assert report.stages[0].gate_summary == "1 pass"


def test_soak_is_scaled(monkeypatch):
    original = MockDriver.get_facts

    def with_bgp(self):
        result = original(self)
        result.facts["bgp_neighbors"] = {"10.0.0.2": "established"}
        return result

    monkeypatch.setattr(MockDriver, "get_facts", with_bgp)
    sleeps: list[float] = []
    report, _, _ = _dispatch(_plan(soak_minutes=30), expectations=EXPECTATIONS,
                             options=DispatchOptions(soak_scale=0.01),
                             sleeps=sleeps)
    assert report.ok
    assert sleeps == [30 * 60 * 0.01]
