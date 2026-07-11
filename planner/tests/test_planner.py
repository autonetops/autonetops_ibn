from pathlib import Path

import pytest

from autonetops_planner.artifact_source import StaticArtifactSource
from autonetops_planner.blast_radius import Thresholds, compute_blast_radius
from autonetops_planner.diffing import diff_artifacts
from autonetops_planner.models import BlastRadiusClass, ControlPointKind, Plan
from autonetops_planner.plan_builder import build_plan
from autonetops_planner.policies import load_canary_strategies, select_strategy

FIXTURE = Path(__file__).parent / "fixtures" / "artifacts.json"


@pytest.fixture()
def changeset():
    source = StaticArtifactSource(FIXTURE)
    return diff_artifacts(
        source.list_artifacts("main"),
        source.list_artifacts("add-customer-c"),
        "main",
        "add-customer-c",
    )


def test_diff_finds_changed_added_removed(changeset):
    kinds = {(i.target, i.change_kind) for i in changeset.items}
    assert ("pe1-gru", "changed") in kinds
    assert ("cvp-gig", "changed") in kinds
    assert ("pe3-gru", "added") in kinds
    assert ("old-rr", "removed") in kinds
    # unchanged target produces no item
    assert all(i.target != "pe2-gru" for i in changeset.items)


def test_removals_never_deployable(changeset):
    assert {i.target for i in changeset.removed} == {"old-rr"}
    assert all(i.target != "old-rr" for i in changeset.deployable)


def test_blast_radius_counts_devices_behind_controllers(changeset):
    blast = compute_blast_radius(changeset)
    # 3 control points, but the controller fans out to 2 leaves -> 4 devices
    assert blast.control_points == ["cvp-gig", "pe1-gru", "pe3-gru"]
    assert blast.devices == ["leaf1-gig", "leaf2-gig", "pe1-gru", "pe3-gru"]
    assert blast.device_count == 4
    # 2 regions -> high by default thresholds
    assert blast.classification == BlastRadiusClass.HIGH
    assert blast.regions == ["gig", "gru"]

    relaxed = compute_blast_radius(changeset, Thresholds(high_min_regions=5))
    assert relaxed.classification == BlastRadiusClass.MODERATE


def test_plan_stages_targets_and_rollback(changeset):
    strategy = select_strategy(
        load_canary_strategies(None), compute_blast_radius(changeset).classification
    )
    plan = build_plan(changeset, strategy)

    # every deployable control point appears exactly once across stages
    deployed = [step.target.control_point for stage in plan.stages for step in stage.steps]
    assert sorted(deployed) == ["cvp-gig", "pe1-gru", "pe3-gru"]

    # first stage is a single-target canary with soak
    assert len(plan.stages[0].steps) == 1
    assert plan.stages[0].gate.soak_minutes > 0

    steps = {s.target.control_point: s for st in plan.stages for s in st.steps}

    # controller step: kind, fan-out, and controller rollback semantics
    controller = steps["cvp-gig"]
    assert controller.target.kind == ControlPointKind.CONTROLLER
    assert controller.target.affected_devices == ["leaf1-gig", "leaf2-gig"]
    assert controller.rollback.strategy == "controller_revision"

    # direct step: device == its own affected scope, vendor rollback mapping
    direct = steps["pe1-gru"]
    assert direct.target.kind == ControlPointKind.DIRECT
    assert direct.target.affected_devices == ["pe1-gru"]
    assert direct.rollback.strategy == "commit_confirmed"  # junos
    assert direct.driver == "junos"

    assert plan.removed_targets == ["old-rr"]


def test_plan_id_deterministic_and_roundtrips(changeset):
    strategy = select_strategy(
        load_canary_strategies(None), compute_blast_radius(changeset).classification
    )
    plan_a, plan_b = build_plan(changeset, strategy), build_plan(changeset, strategy)
    assert plan_a.id == plan_b.id

    # serializes with the "class" alias and validates back
    dumped = plan_a.model_dump(mode="json", by_alias=True)
    assert dumped["blast_radius"]["class"] == "high"
    restored = Plan.model_validate(dumped)
    assert restored.id == plan_a.id


def test_committed_schema_matches_models():
    """CI drift gate: contracts/plan/v1/plan.schema.json is generated output."""
    import json

    committed = Path(__file__).parents[2] / "contracts" / "plan" / "v1" / "plan.schema.json"
    if not committed.exists():
        pytest.skip("schema not exported yet")
    schema = Plan.model_json_schema(by_alias=True)
    schema["$id"] = "https://autonetops.dev/contracts/plan/v1/plan.schema.json"
    assert json.loads(committed.read_text()) == schema
