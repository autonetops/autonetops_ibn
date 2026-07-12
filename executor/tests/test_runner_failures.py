"""run_step failure containment: no driver/transport exception may escape.

A blowup mid-plan must surface as a StepOutcome the orchestrator can reason
about (and abort on), never as a traceback that kills the dispatch with no
report. rollback_failed is the highest-severity outcome: device state UNKNOWN.
"""

from __future__ import annotations

import hashlib

import pytest

from autonetops_executor import run_step
from autonetops_executor.driver import _REGISTRY, register
from autonetops_executor.drivers.mock import MockDriver
from autonetops_planner.models import RollbackSpec, Step, StepTarget

CONTENT = "hostname dev-1\n"


def _step(driver: str) -> Step:
    return Step(
        target=StepTarget(control_point="dev-1"),
        driver=driver,
        platform="mock",
        artifact_definition="device-configuration",
        checksum_after=hashlib.sha256(CONTENT.encode()).hexdigest(),
        rollback=RollbackSpec(strategy="commit_confirmed"),
    )


@pytest.fixture()
def scratch_registry():
    """Register throwaway driver classes; leave the registry as we found it."""
    added: list[str] = []

    def add(cls):
        register(cls)
        added.append(cls.name)
        return cls

    yield add
    for name in added:
        _REGISTRY.pop(name, None)


def test_snapshot_failure_is_contained(scratch_registry):
    @scratch_registry
    class SnapshotBlowsUp(MockDriver):
        name = "test-snap-fail"

        def snapshot(self):
            raise ConnectionError("ssh timeout")

    records = []
    outcome = run_step(_step("test-snap-fail"), {}, CONTENT, emit=records.append)
    assert outcome.status == "failed"
    assert "snapshot failed" in outcome.detail
    assert records[-1]["success"] is False


def test_dry_run_failure_is_contained(scratch_registry):
    @scratch_registry
    class DryRunBlowsUp(MockDriver):
        name = "test-dry-fail"

        def dry_run(self, artifact):
            raise TimeoutError("candidate hung")

    outcome = run_step(_step("test-dry-fail"), {}, CONTENT)
    assert outcome.status == "failed"
    assert "dry_run failed" in outcome.detail
    assert outcome.snapshot_id  # snapshot was taken before the blowup


def test_apply_failure_rolls_back(scratch_registry):
    @scratch_registry
    class ApplyBlowsUp(MockDriver):
        name = "test-apply-fail"

        def apply(self, artifact):
            raise RuntimeError("commit rejected")

    device = {"initial_config": "hostname old\n"}
    outcome = run_step(_step("test-apply-fail"), device, CONTENT)
    assert outcome.status == "rolled_back"
    assert "commit rejected" in outcome.detail


def test_rollback_failure_is_the_loudest_outcome(scratch_registry):
    @scratch_registry
    class EverythingBlowsUp(MockDriver):
        name = "test-rollback-fail"

        def apply(self, artifact):
            raise RuntimeError("commit rejected")

        def rollback(self, reference):
            raise ConnectionError("device unreachable mid-revert")

    records = []
    outcome = run_step(_step("test-rollback-fail"), {}, CONTENT, emit=records.append)
    assert outcome.status == "rollback_failed"
    assert not outcome.ok
    assert "UNKNOWN" in outcome.detail
    # evidence carries both errors for the human who gets paged
    failure = records[-1]
    assert failure["operation"] == "rollback" and failure["success"] is False
    assert "apply_error" in failure["detail"]
