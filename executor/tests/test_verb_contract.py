"""The verb contract, exercised through the reference (mock) driver, plus
registry/capability invariants every driver must satisfy."""

import sys

import pytest

from autonetops_executor import (
    ArtifactPayload,
    available_drivers,
    capability_report,
    get_driver_class,
)
from autonetops_executor.exceptions import ChangeNotFound, UnknownDriver, UnsupportedCapability

ARTIFACT = ArtifactPayload(
    definition="device-config",
    checksum="abc123def456",
    content="hostname leaf1\ninterface e1\n  description uplink\n",
)


@pytest.fixture()
def device():
    cls = get_driver_class("mock")
    return cls("leaf1-lab", {"initial_config": "hostname leaf1\n"})


def test_registry_and_capability_declarations():
    assert available_drivers() == ["mock", "srlinux"]
    for name, caps in capability_report().items():
        assert caps.protocols, f"driver {name} must declare at least one protocol"
    with pytest.raises(UnknownDriver):
        get_driver_class("does-not-exist")


def test_no_orchestrator_dependency():
    """ADR-0009 boundary: importing the executor must never pull Prefect."""
    assert "prefect" not in sys.modules


def test_dry_run_reports_diff_without_touching_state(device):
    result = device.dry_run(ARTIFACT)
    assert result.changed and "+interface e1" in result.diff
    assert device.running_config == "hostname leaf1\n"  # untouched
    assert result.evidence.operation == "dry_run" and result.evidence.success


def test_apply_confirm_lifecycle(device):
    pending = device.apply(ARTIFACT)
    assert device.running_config == ARTIFACT.content
    assert pending.rollback_strategy == "commit_confirmed"
    assert pending.confirm_deadline_seconds > 0
    assert not device.is_confirmed(pending.change_id)

    evidence = device.confirm(pending.change_id)
    assert evidence.success and device.is_confirmed(pending.change_id)


def test_rollback_of_unconfirmed_change_restores_previous(device):
    before = device.running_config
    pending = device.apply(ARTIFACT)
    evidence = device.rollback(pending.change_id)
    assert evidence.success and evidence.detail["restored"] == "change"
    assert device.running_config == before


def test_snapshot_revert_path(device):
    snap = device.snapshot()
    device.apply(ARTIFACT)
    evidence = device.rollback(snap.snapshot_id)
    assert evidence.success and evidence.detail["restored"] == "snapshot"
    assert device.running_config == "hostname leaf1\n"


def test_rollback_unknown_reference_raises(device):
    with pytest.raises(ChangeNotFound):
        device.rollback("chg-nope")


def test_undeclared_capabilities_refuse_loudly():
    srl = get_driver_class("srlinux")("srl1-lab")
    with pytest.raises(UnsupportedCapability):
        srl.dry_run(ARTIFACT)
    with pytest.raises(UnsupportedCapability):
        srl.confirm("chg-x")


def test_every_verb_result_is_serializable(device):
    """ADR-0009: outputs must survive a service boundary."""
    for result in (device.get_facts(), device.snapshot(), device.dry_run(ARTIFACT), device.apply(ARTIFACT)):
        assert result.model_dump_json()
