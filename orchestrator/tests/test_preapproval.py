"""Pre-approved plan classes at runtime (ADR-0014): decide, re-verify,
tighten, watch hold — and the dispatch-time window-duration re-check."""

from __future__ import annotations

import datetime
import hashlib
import json

from autonetops_planner.change_classes import ChangeClass, ChangeClassPolicy
from autonetops_planner.models import (
    BlastRadius,
    BlastRadiusClass,
    Plan,
    PlanSource,
    PolicyEvaluation,
    PreApproval,
    RollbackSpec,
    Stage,
    Step,
    StepTarget,
)
from autonetops_planner.policies import DEFAULT_STRATEGIES, CanaryStage, CanaryStrategy
from autonetops_validator import ExpectationSet

from autonetops_orchestrator.dispatch import DispatchOptions, dispatch_plan
from autonetops_orchestrator.preapproval import (
    UNVERIFIABLE,
    recent_pre_approved,
    tighten_approvals,
    verify_pre_approval,
)
from autonetops_orchestrator.strategy import Decision, decide
from autonetops_orchestrator.timeline import evaluate_timeline
from autonetops_orchestrator.watch import watch_loop
from autonetops_orchestrator.windows import ChangeWindow

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 14, 21, 30, tzinfo=UTC)  # Tuesday night

ALL_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")
OPEN_WINDOW = ChangeWindow(name="always", max_blast_radius="high",
                           days=ALL_DAYS, start_utc="00:00",
                           duration_minutes=1440)

BEFORE = """interface eth1
 description old uplink
 mtu 9000
"""
AFTER = BEFORE.replace("old uplink", "new uplink")
AFTER_MIXED = AFTER.replace("mtu 9000", "mtu 9100")

DESCRIPTIONS = ChangeClass(
    name="interface-descriptions",
    artifact_definitions=["device-configuration"],
    cli_text_allow=[r"^\s*interface \S+$", r"^\s*description .+$"],
    max_blast_radius=BlastRadiusClass.HIGH,
)
POLICY = ChangeClassPolicy(version="1", classes=[DESCRIPTIONS])
CLAIM = PreApproval(class_name="interface-descriptions", policy_version="1")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _plan(*, pre=CLAIM, strategy="builtin-single-target-canary",
          before=BEFORE, after=AFTER) -> Plan:
    step = Step(
        target=StepTarget(control_point="pe-1"),
        driver="mock", platform="mock",
        artifact_definition="device-configuration",
        checksum_before=_sha(before), checksum_after=_sha(after),
        rollback=RollbackSpec(strategy="commit_confirmed"),
    )
    stages = [Stage(name="stage-1", steps=[step])]
    source = PlanSource(base_branch="main", candidate_branch="chg")
    return Plan(
        id=Plan.deterministic_id(source, stages), source=source,
        blast_radius=BlastRadius(classification=BlastRadiusClass.LOW,
                                 device_count=1, devices=["pe-1"]),
        policy_evaluation=PolicyEvaluation(canary_strategy=strategy,
                                           pre_approved=pre),
        stages=stages,
    )


def _bundle(tmp_path, *, before=BEFORE, after=AFTER):
    (tmp_path / "content").mkdir(exist_ok=True)
    (tmp_path / "content_base").mkdir(exist_ok=True)
    name = "pe-1__device-configuration.cfg"
    (tmp_path / "content" / name).write_text(after)
    (tmp_path / "content_base" / name).write_text(before)
    return tmp_path


# -- decide() ---------------------------------------------------------------

def test_decide_waives_approvals_for_pre_approved_class():
    strategies = [CanaryStrategy(
        name="builtin-single-target-canary",
        applies_to=[BlastRadiusClass.LOW],
        stages=[CanaryStage(select="one_target")],
        requires_approvals=["platform-lead"],
    )]
    plan = _plan()
    timeline = evaluate_timeline(plan, [OPEN_WINDOW], now=NOW)
    decision = decide(plan, timeline, now=NOW, strategies=strategies)
    assert decision.mode == "immediate"  # not needs_approval
    assert decision.approvals_required == []
    assert decision.pre_approved_class == "interface-descriptions"
    assert any("ADR-0014" in reason for reason in decision.reasons)


def test_decide_emergency_never_combines_with_pre_approval():
    strategies = [CanaryStrategy(
        name="builtin-single-target-canary",
        applies_to=[BlastRadiusClass.LOW],
        stages=[CanaryStage(select="one_target")],
        requires_approvals=["platform-lead"],
    )]
    plan = _plan()
    timeline = evaluate_timeline(plan, [], now=NOW)  # blocked
    decision = decide(plan, timeline, now=NOW, priority="critical",
                      emergency=True, strategies=strategies)
    assert decision.emergency_override
    assert decision.pre_approved_class is None
    assert decision.approvals_required == ["platform-lead"]


# -- re-verification from the frozen bundle ----------------------------------

def test_verify_pre_approval_roundtrip(tmp_path):
    _bundle(tmp_path)
    assert verify_pre_approval(tmp_path, _plan(), POLICY)


def test_verify_refuses_tampered_content_base(tmp_path):
    _bundle(tmp_path)
    # same description-only shape, but not the bytes the plan hashed
    (tmp_path / "content_base" / "pe-1__device-configuration.cfg").write_text(
        BEFORE.replace("old uplink", "innocent-looking"))
    assert not verify_pre_approval(tmp_path, _plan(), POLICY)


def test_verify_refuses_when_bytes_do_not_prove_the_class(tmp_path):
    _bundle(tmp_path, after=AFTER_MIXED)  # checksums consistent, diff not routine
    assert not verify_pre_approval(
        tmp_path, _plan(after=AFTER_MIXED), POLICY)


def test_kill_switch_disables_already_planned_bundles(tmp_path):
    _bundle(tmp_path)
    disabled = ChangeClassPolicy(version="2", classes=[
        ChangeClass(name="interface-descriptions", enabled=False,
                    cli_text_allow=DESCRIPTIONS.cli_text_allow,
                    max_blast_radius=BlastRadiusClass.HIGH)])
    assert not verify_pre_approval(tmp_path, _plan(), disabled)


# -- the approval bar only tightens at dispatch -------------------------------

def test_tighten_keeps_verified_pre_approval(tmp_path):
    _bundle(tmp_path)
    decision = Decision(mode="immediate", approvals_required=[],
                        pre_approved_class="interface-descriptions")
    required, notes, verified = tighten_approvals(
        _plan(), decision, tmp_path, POLICY, DEFAULT_STRATEGIES)
    assert required == []
    assert verified is True
    assert any("re-verified" in note for note in notes)


def test_tighten_restores_strategy_floor_on_failed_claim(tmp_path):
    _bundle(tmp_path, after=AFTER_MIXED)
    plan = _plan(strategy="builtin-high-blast-radius", after=AFTER_MIXED)
    decision = Decision(mode="immediate", approvals_required=[])
    required, notes, verified = tighten_approvals(
        plan, decision, tmp_path, POLICY, DEFAULT_STRATEGIES)
    assert required == ["domain-owner", "platform-lead"]
    assert verified is False
    assert any("did NOT re-verify" in note for note in notes)


def test_tighten_refuses_unknown_strategy_on_failed_claim(tmp_path):
    _bundle(tmp_path, after=AFTER_MIXED)
    plan = _plan(strategy="custom-not-loaded", after=AFTER_MIXED)
    required, _, verified = tighten_approvals(
        plan, Decision(mode="immediate"), tmp_path, POLICY, DEFAULT_STRATEGIES)
    assert UNVERIFIABLE in required
    assert verified is False


def test_tighten_restores_floor_on_edited_decision_without_claim(tmp_path):
    plan = _plan(pre=None, strategy="builtin-high-blast-radius")
    tampered = Decision(mode="immediate", approvals_required=[])
    required, notes, verified = tighten_approvals(
        plan, tampered, tmp_path, ChangeClassPolicy(), DEFAULT_STRATEGIES)
    assert required == ["domain-owner", "platform-lead"]
    assert verified is None
    assert any("tightened to the floor" in note for note in notes)


# -- rate limit ---------------------------------------------------------------

def test_recent_pre_approved_counts_only_recent_same_class(tmp_path):
    def bundle(name, created_at, cls):
        plan_dir = tmp_path / name
        plan_dir.mkdir()
        doc = {"created_at": created_at, "policy_evaluation": {}}
        if cls:
            doc["policy_evaluation"]["pre_approved"] = {
                "class": cls, "policy_version": "1"}
        (plan_dir / "plan.yaml").write_text(json.dumps(doc))

    bundle("plan-recent", (NOW - datetime.timedelta(minutes=10)).isoformat(),
           "interface-descriptions")
    bundle("plan-old", (NOW - datetime.timedelta(hours=2)).isoformat(),
           "interface-descriptions")
    bundle("plan-other", (NOW - datetime.timedelta(minutes=5)).isoformat(),
           "different-class")
    bundle("plan-human", (NOW - datetime.timedelta(minutes=5)).isoformat(), None)
    assert recent_pre_approved(tmp_path, "interface-descriptions", NOW) == 1


# -- watch: needs_approval is non-terminal ------------------------------------

class _FakeClient:
    def __init__(self):
        self.pc_state = "merged"

    def execute_graphql(self, query):
        return {"CoreProposedChange": {"edges": [{"node": {
            "id": "pc-1", "name": {"value": "desc-change"},
            "state": {"value": self.pc_state},
            "source_branch": {"value": "chg"},
            "destination_branch": {"value": "main"},
        }}]}}


def test_watch_holds_needs_approval_until_manual_dispatch(tmp_path):
    plan_dir = tmp_path / "plan-x"
    plan_dir.mkdir()
    (tmp_path / ".watch-state.json").write_text(json.dumps(
        {"pc-1": {"name": "desc-change", "branch": "chg",
                  "plan_dir": str(plan_dir)}}))
    calls: list = []

    def one_pass(exit_code=4):
        watch_loop(
            client=_FakeClient(),
            plan_fn=lambda branch: (None, None, None),
            dispatch_fn=lambda p: calls.append(p) or exit_code,
            plans_dir=tmp_path, once=True, echo=lambda m: None,
        )
        return json.loads((tmp_path / ".watch-state.json").read_text())["pc-1"]

    record = one_pass()
    assert calls and record["approval_hold"] and not record["dispatched"]

    # held: watch does not hammer dispatch (no evidence churn every pass)
    record = one_pass()
    assert len(calls) == 1 and record["approval_hold"]

    # a manual `dispatch --approve ...` leaves a real outcome: hold released
    (plan_dir / "report.yaml").write_text("status: succeeded\n")
    record = one_pass()
    assert len(calls) == 1 and record["dispatched"] is True
    assert "approval_hold" not in record


def test_watch_still_holds_after_missing_approvals_report(tmp_path):
    plan_dir = tmp_path / "plan-y"
    plan_dir.mkdir()
    (plan_dir / "report.yaml").write_text(
        "status: aborted\naborted: 'missing approvals: platform-lead'\n")
    (tmp_path / ".watch-state.json").write_text(json.dumps(
        {"pc-1": {"name": "desc-change", "branch": "chg",
                  "plan_dir": str(plan_dir), "approval_hold": True}}))
    watch_loop(
        client=_FakeClient(),
        plan_fn=lambda branch: (None, None, None),
        dispatch_fn=lambda p: 0,
        plans_dir=tmp_path, once=True, echo=lambda m: None,
    )
    record = json.loads((tmp_path / ".watch-state.json").read_text())["pc-1"]
    assert record["approval_hold"] and not record.get("dispatched")


# -- window fit is re-checked with the stage duration, not just openness ------

def test_dispatch_refuses_window_too_short_for_stage():
    # open RIGHT NOW, but only 2 minutes long - a 1-step stage needs 3
    short = ChangeWindow(name="sliver", days=ALL_DAYS, start_utc="21:29",
                         duration_minutes=2, max_blast_radius="high")
    report = dispatch_plan(
        _plan(pre=None), Decision(mode="immediate"), windows=[short],
        connection_for=lambda t: {"initial_config": ""},
        content_for=lambda s: AFTER,
        expectations=ExpectationSet(), emit=lambda r: None, echo=lambda m: None,
        options=DispatchOptions(), now_fn=lambda: NOW,
    )
    assert report.aborted and "no eligible window" in report.aborted
    assert not report.stages[0].outcomes  # nothing touched the network
